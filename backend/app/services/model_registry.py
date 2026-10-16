# app/services/model_registry.py
"""Thread-safe loading of the YOLO detector and resolution of the model device.

YOLO is stateful: ``model.track(persist=True)`` keeps tracker state on the model
object, so each camera worker gets its own detector instance to prevent
track-id crosstalk.
"""

import logging
import os
import threading
from typing import Any, Optional

from app.core.config import config

logger = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(self) -> None:
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

        with self._yolo_lock:  # serialise the first download across workers
            # Fetch a missing pretrained checkpoint to the configured path, so it
            # lands in the mounted models/ dir instead of the working directory.
            if not os.path.exists(weights):
                from ultralytics.utils.downloads import attempt_download_asset

                logger.info("Weights %s not present; downloading.", weights)
                os.makedirs(os.path.dirname(weights) or ".", exist_ok=True)
                weights = str(attempt_download_asset(weights))
            model = YOLO(weights)

        logger.info("YOLO loaded (%s) on %s", weights, self.device)
        return model


model_registry = ModelRegistry()
