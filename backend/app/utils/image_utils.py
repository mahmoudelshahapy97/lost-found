# app/utils/image_utils.py
"""Image processing utilities for frame conversion, cropping and annotation."""

import base64
import logging
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

from app.core.config import config
from app.utils.geometry_utils import Box, clamp_box

logger = logging.getLogger(__name__)


def encode_jpeg(frame: np.ndarray, quality: Optional[int] = None) -> Optional[bytes]:
    """Encode a BGR frame as JPEG bytes."""
    if frame is None or frame.size == 0:
        return None
    success, buffer = cv2.imencode(
        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality or config.jpeg_quality]
    )
    if not success:
        logger.error("cv2.imencode failed during JPEG encoding.")
        return None
    return buffer.tobytes()


def decode_jpeg(data: bytes) -> Optional[np.ndarray]:
    """Decode JPEG/PNG bytes into a BGR frame."""
    if not data:
        return None
    try:
        nparr = np.frombuffer(data, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.error("Error decoding image bytes: %s", e, exc_info=True)
        return None


def frame_to_base64(frame: np.ndarray) -> str:
    """Converts an OpenCV frame (numpy array) to a base64 encoded string."""
    data = encode_jpeg(frame)
    return base64.b64encode(data).decode("utf-8") if data else ""


def base64_to_frame(base64_string: str) -> Optional[np.ndarray]:
    """Converts a base64 encoded string back to an OpenCV frame."""
    if not base64_string:
        return None
    try:
        return decode_jpeg(base64.b64decode(base64_string))
    except Exception as e:
        logger.error("Error decoding base64 string to frame: %s", e, exc_info=True)
        return None


def bytes_to_base64(data: Optional[bytes]) -> Optional[str]:
    """Postgres BYTEA -> base64 string for JSON responses."""
    if not data:
        return None
    return base64.b64encode(bytes(data)).decode("utf-8")


def crop_box(frame: np.ndarray, box: Box, padding: int = 8) -> Optional[np.ndarray]:
    """Crop a padded region of the frame; returns None when the crop is empty."""
    if frame is None or frame.size == 0:
        return None

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = box
    padded = (x1 - padding, y1 - padding, x2 + padding, y2 + padding)
    x1, y1, x2, y2 = clamp_box(padded, width, height)

    crop = frame[int(y1) : int(y2), int(x1) : int(x2)]
    return crop if crop.size else None


# BGR colours
_COLOR_OBJECT = (0, 165, 255)      # orange - tracked object
_COLOR_ABANDONED = (0, 0, 255)     # red - abandoned
_COLOR_PERSON = (0, 200, 0)        # green - person
_COLOR_ROI = (255, 200, 0)         # cyan-ish - region of interest


def draw_box(
    frame: np.ndarray,
    box: Box,
    label: str = "",
    color: Tuple[int, int, int] = _COLOR_OBJECT,
    thickness: int = 2,
) -> np.ndarray:
    """Draw a labelled rectangle in place and return the frame."""
    x1, y1, x2, y2 = (int(v) for v in box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

    if label:
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        top = max(0, y1 - th - baseline - 4)
        cv2.rectangle(frame, (x1, top), (x1 + tw + 6, top + th + baseline + 4), color, -1)
        cv2.putText(
            frame,
            label,
            (x1 + 3, top + th + 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return frame


def draw_roi(frame: np.ndarray, polygon: Sequence[Sequence[float]]) -> np.ndarray:
    """Outline the configured region of interest."""
    if not polygon or len(polygon) < 3:
        return frame
    points = np.array([[int(p[0]), int(p[1])] for p in polygon], dtype=np.int32)
    cv2.polylines(frame, [points], isClosed=True, color=_COLOR_ROI, thickness=2)
    return frame


def annotate_abandoned(
    frame: np.ndarray,
    box: Box,
    class_name: str,
    unattended_seconds: float,
) -> np.ndarray:
    """Produce the alert frame stored alongside an abandoned event."""
    annotated = frame.copy()
    draw_box(
        annotated,
        box,
        f"ABANDONED {class_name} ({unattended_seconds:.0f}s)",
        _COLOR_ABANDONED,
        thickness=3,
    )
    return annotated
