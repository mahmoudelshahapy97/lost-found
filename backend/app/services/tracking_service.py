# app/services/tracking_service.py
"""Thin wrapper turning ultralytics tracking output into plain ``Detection`` records.

Keeping the ultralytics types confined to this module lets the abandonment state
machine be exercised with synthetic detections and no model at all.
"""

import logging
from dataclasses import dataclass
from typing import Any, List, Optional

import numpy as np

from app.core.config import config
from app.services.model_registry import model_registry
from app.utils.geometry_utils import Box

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    track_id: int
    class_id: int
    class_name: str
    confidence: float
    box: Box

    @property
    def is_person(self) -> bool:
        return self.class_id == config.person_class_id


class ObjectTracker:
    """Per-camera detector + tracker. Not thread-safe by design: one per worker."""

    def __init__(self, model: Optional[Any] = None) -> None:
        self.model = model if model is not None else model_registry.create_yolo()
        self._names = getattr(self.model, "names", {}) or {}

    def track(self, frame: np.ndarray) -> List[Detection]:
        """Detect and track people plus the watched object classes in one frame."""
        if frame is None or frame.size == 0:
            return []

        results = self.model.track(
            frame,
            persist=True,
            tracker=config.yolo_tracker,
            classes=config.tracked_class_ids,
            conf=config.yolo_confidence,
            imgsz=config.yolo_input_size,
            device=model_registry.device,
            verbose=False,
        )

        if not results:
            return []
        return self._parse(results[0])

    def _parse(self, result: Any) -> List[Detection]:
        boxes = getattr(result, "boxes", None)
        if boxes is None or boxes.id is None or len(boxes) == 0:
            # boxes.id is None when the tracker produced no confirmed tracks yet.
            return []

        try:
            xyxy = boxes.xyxy.cpu().numpy()
            track_ids = boxes.id.int().cpu().numpy()
            class_ids = boxes.cls.int().cpu().numpy()
            confidences = boxes.conf.cpu().numpy()
        except Exception as e:
            logger.error("Failed to read tracking results: %s", e, exc_info=True)
            return []

        names = getattr(result, "names", None) or self._names
        detections: List[Detection] = []

        for box, track_id, class_id, confidence in zip(xyxy, track_ids, class_ids, confidences):
            cid = int(class_id)
            detections.append(
                Detection(
                    track_id=int(track_id),
                    class_id=cid,
                    class_name=str(names.get(cid, cid)),
                    confidence=float(confidence),
                    box=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
                )
            )

        return detections

    def reset(self) -> None:
        """Drop tracker state, e.g. after a stream reconnect where ids are meaningless."""
        try:
            predictor = getattr(self.model, "predictor", None)
            trackers = getattr(predictor, "trackers", None) if predictor else None
            if trackers:
                for tracker in trackers:
                    tracker.reset()
                logger.debug("Tracker state reset.")
        except Exception as e:
            logger.debug("Tracker reset skipped: %s", e)
