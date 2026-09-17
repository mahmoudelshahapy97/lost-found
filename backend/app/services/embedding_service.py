# app/services/embedding_service.py
"""CLIP embeddings for visual lost/found matching.

Image and text share one 512-d space, so a photo of a lost bag and the phrase
"black leather backpack" can both be searched against the found-item gallery.
All vectors are L2-normalised, which makes pgvector's cosine distance
(``<=>``) a direct similarity measure: ``similarity = 1 - distance``.
"""

import asyncio
import logging
from typing import List, Optional

import numpy as np

from app.core.config import config
from app.services.model_registry import model_registry

logger = logging.getLogger(__name__)


class EmbeddingService:
    def _normalize(self, vector: np.ndarray) -> List[float]:
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector = vector / norm
        return vector.astype(np.float32).tolist()

    # ------------------------------------------------------------------ sync
    def embed_image(self, image_bgr: np.ndarray) -> Optional[List[float]]:
        """Embed an OpenCV BGR image (a crop or an uploaded photo)."""
        if image_bgr is None or image_bgr.size == 0:
            return None

        try:
            import cv2
            import torch
            from PIL import Image

            model, preprocess, _ = model_registry.get_clip()
            pil = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
            tensor = preprocess(pil).unsqueeze(0).to(model_registry.device)

            with torch.no_grad():
                features = model.encode_image(tensor)

            return self._normalize(features[0].cpu().numpy())
        except Exception as e:
            logger.error("Image embedding failed: %s", e, exc_info=True)
            return None

    def embed_text(self, text: str) -> Optional[List[float]]:
        """Embed a free-text description into the same space as the images."""
        if not text or not text.strip():
            return None

        try:
            import torch

            model, _, tokenizer = model_registry.get_clip()
            tokens = tokenizer([text.strip()]).to(model_registry.device)

            with torch.no_grad():
                features = model.encode_text(tokens)

            return self._normalize(features[0].cpu().numpy())
        except Exception as e:
            logger.error("Text embedding failed: %s", e, exc_info=True)
            return None

    # ----------------------------------------------------------------- async
    async def embed_image_async(self, image_bgr: np.ndarray) -> Optional[List[float]]:
        """Off-load the forward pass so the event loop is not blocked."""
        return await asyncio.to_thread(self.embed_image, image_bgr)

    async def embed_text_async(self, text: str) -> Optional[List[float]]:
        return await asyncio.to_thread(self.embed_text, text)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """Similarity between two already-normalised vectors."""
        if not a or not b:
            return 0.0
        return float(np.dot(np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)))

    @property
    def dim(self) -> int:
        return config.embedding_dim


embedding_service = EmbeddingService()
