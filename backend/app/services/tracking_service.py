# app/services/tracking_service.py
"""Thin wrapper turning ultralytics tracking output into plain ``Detection`` records.

Keeping the ultralytics types confined to this module lets the abandonment state
machine be exercised with synthetic detections and no model at all.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.config import config
from app.services.model_registry import model_registry
from app.utils.geometry_utils import Box, iou

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
    """Per-camera detector + tracker. Not thread-safe by design: one per worker.

    Runs the detector and ByteTrack as separate steps rather than through
    ``model.track()``, because ByteTrack only reports confirmed tracks: a small
    bag on the floor scoring 0.1-0.3 flickers in and out, never confirms, and
    so never reached the abandonment logic although the detector kept seeing
    it. Object detections the tracker leaves unmatched are followed here by box
    overlap instead - reliable precisely for the still objects that matter.
    """

    def __init__(self, model: Optional[Any] = None) -> None:
        self.model = model if model is not None else model_registry.create_yolo()
        self._names = getattr(self.model, "names", {}) or {}
        self._tracker = self._new_tracker()
        # Unconfirmed still objects: negative id -> (box, last frame seen).
        self._loose: Dict[int, Tuple[Box, int]] = {}
        self._next_loose_id = -1
        self._frame = 0

    @staticmethod
    def _new_tracker() -> Any:
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.utils import YAML, IterableSimpleNamespace
        from ultralytics.utils.checks import check_yaml

        cfg = IterableSimpleNamespace(**YAML.load(check_yaml(config.yolo_tracker)))
        return BYTETracker(args=cfg)

    def track(self, frame: np.ndarray) -> List[Detection]:
        """Detect and track people plus the watched object classes in one frame."""
        if frame is None or frame.size == 0:
            return []

        device = model_registry.device
        results = self.model.predict(
            frame,
            classes=config.tracked_class_ids,
            conf=config.yolo_confidence,
            imgsz=config.yolo_input_size,
            agnostic_nms=config.yolo_agnostic_nms,
            quantize=16 if config.yolo_half and device.startswith("cuda") else None,
            device=device,
            verbose=False,
        )
        if not results:
            return []

        self._frame += 1
        try:
            boxes = results[0].boxes.cpu().numpy()
            tracks = self._tracker.update(boxes, frame)
            xyxy, class_ids, confidences = boxes.xyxy, boxes.cls.astype(int), boxes.conf
        except Exception as e:
            logger.error("Failed to track detections: %s", e, exc_info=True)
            return []

        names = getattr(results[0], "names", None) or self._names
        detections: List[Detection] = []
        matched = set()
        for row in tracks:
            idx = int(row[-1])
            matched.add(idx)
            detections.append(self._detection(int(row[4]), int(class_ids[idx]), confidences[idx], xyxy[idx], names))

        tracked_boxes = [d.box for d in detections]
        for idx in range(len(xyxy)):
            cid = int(class_ids[idx])
            if idx in matched or cid == config.person_class_id:
                continue
            box = tuple(float(v) for v in xyxy[idx])
            # Overlapping a box already reported this frame: the same object twice.
            if any(iou(box, other) >= config.loose_track_iou for other in tracked_boxes):
                continue
            tracked_boxes.append(box)
            detections.append(self._detection(self._loose_id(box), cid, confidences[idx], xyxy[idx], names))

        self._forget_loose()
        return detections

    def _detection(self, track_id: int, cid: int, confidence: float, box: Any, names: Dict) -> Detection:
        name = str(names.get(cid, cid))
        return Detection(
            track_id=track_id,
            class_id=cid,
            class_name=config.class_name_map.get(name, name),
            confidence=float(confidence),
            box=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
        )

    def _loose_id(self, box: Box) -> int:
        """Same id as the overlapping loose object seen recently, else a new one."""
        best, best_iou = None, config.loose_track_iou
        for track_id, (other, _) in self._loose.items():
            overlap = iou(box, other)
            if overlap >= best_iou:
                best, best_iou = track_id, overlap
        if best is None:
            best = self._next_loose_id
            self._next_loose_id -= 1
        self._loose[best] = (box, self._frame)
        return best

    def _forget_loose(self) -> None:
        # Short on purpose: this only bridges flicker. Longer gaps of a still
        # object are bridged by the abandonment tracker, which checks the object
        # was still; reusing an id here for whatever appears at a spot many
        # seconds later handed a carried bag's owners to a different object.
        horizon = config.loose_track_max_gap_frames
        for track_id in [k for k, (_, seen) in self._loose.items() if self._frame - seen > horizon]:
            del self._loose[track_id]

    def reset(self) -> None:
        """Drop tracker state, e.g. after a stream reconnect where ids are meaningless."""
        self._tracker.reset()
        self._loose.clear()
        self._next_loose_id = -1
        self._frame = 0
