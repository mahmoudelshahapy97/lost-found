# app/services/model_registry.py
"""Lazy, thread-safe loading of the YOLO detector and the CLIP embedder.

CLIP is stateless, so a single shared instance serves every request. YOLO is
*not*: ``model.track(persist=True)`` keeps tracker state on the model object, so
each camera worker gets its own detector instance to prevent track-id crosstalk.
"""

import logging
import os
import threading
from typing import Any, Optional, Tuple

from app.core.config import config

logger = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(self) -> None:
        self._clip_bundle: Optional[Tuple[Any, Any, Any]] = None
        self._clip_lock = threading.Lock()
        self._yolo_lock = threading.Lock()
        self._device: Optional[str] = None

    # ------------------------------------------------------------------ device
    @property
    def device(self) -> str:
        """Resolve the configured device once, falling back to CPU when CUDA is absent."""
        if self._device is not None:
            return self._device

        requested = (config.model_device or "cpu").lower()
        if requested.startswith("cuda"):
            try:
                import torch

                if not torch.cuda.is_available():
                    logger.warning("MODEL_DEVICE=%s but CUDA is unavailable; using cpu.", requested)
                    requested = "cpu"
            except Exception as e:
                logger.warning("Could not probe CUDA (%s); using cpu.", e)
                requested = "cpu"

        self._device = requested
        return self._device

    # -------------------------------------------------------------------- yolo
    def create_yolo(self) -> Any:
        """Build a fresh YOLO instance. One per camera worker."""
        from ultralytics import YOLO

        weights = config.yolo_model_path
        # Ultralytics downloads a missing pretrained checkpoint by basename.
        if not os.path.exists(weights):
            fallback = os.path.basename(weights)
            logger.info("Weights %s not present; ultralytics will fetch '%s'.", weights, fallback)
            weights = fallback

        with self._yolo_lock:  # serialise the first download across workers
            model = YOLO(weights)

        logger.info("YOLO loaded (%s) on %s", weights, self.device)
        return model

    # -------------------------------------------------------------------- clip
    def get_clip(self) -> Tuple[Any, Any, Any]:
        """Return the shared ``(model, preprocess, tokenizer)`` triple."""
        if self._clip_bundle is not None:
            return self._clip_bundle

        with self._clip_lock:
            if self._clip_bundle is not None:
                return self._clip_bundle

            import open_clip
            import torch

            os.makedirs(config.model_cache_dir, exist_ok=True)
            model, _, preprocess = open_clip.create_model_and_transforms(
                config.clip_model_name,
                pretrained=config.clip_pretrained,
                cache_dir=config.model_cache_dir,
            )
            tokenizer = open_clip.get_tokenizer(config.clip_model_name)

            model = model.to(self.device)
            model.eval()
            torch.set_grad_enabled(False)

            self._clip_bundle = (model, preprocess, tokenizer)
            logger.info(
                "CLIP loaded (%s / %s) on %s",
                config.clip_model_name,
                config.clip_pretrained,
                self.device,
            )
            return self._clip_bundle

    def warmup(self, load_clip: bool = True) -> None:
        """Pay the model-loading cost at startup rather than on the first request."""
        if load_clip:
            try:
                self.get_clip()
            except Exception as e:
                logger.error("CLIP warmup failed: %s", e, exc_info=True)


model_registry = ModelRegistry()
