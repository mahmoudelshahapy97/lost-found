# app/schemas/camera_schemas.py
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CameraCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    rtsp_url: str = Field(..., description="rtsp://user:pass@host:554/stream, or a local file path")
    location: Optional[str] = Field(None, max_length=200)
    enabled: bool = True
    roi: Optional[List[List[float]]] = Field(
        None, description="Optional polygon [[x,y], ...] limiting where detections count"
    )
    settings: Optional[Dict[str, Any]] = Field(
        None,
        description="Per-camera overrides, e.g. {'abandon_seconds': 45, 'owner_distance_px': 220}",
    )

    @field_validator("roi")
    @classmethod
    def validate_roi(cls, value: Optional[List[List[float]]]) -> Optional[List[List[float]]]:
        if value is None:
            return None
        if len(value) < 3:
            raise ValueError("roi needs at least 3 points")
        if any(len(point) != 2 for point in value):
            raise ValueError("each roi point must be [x, y]")
        return value


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    rtsp_url: Optional[str] = None
    location: Optional[str] = None
    enabled: Optional[bool] = None
    roi: Optional[List[List[float]]] = None
    settings: Optional[Dict[str, Any]] = None


class CameraResponse(BaseModel):
    camera_id: UUID
    name: str
    rtsp_url: str
    location: Optional[str] = None
    enabled: bool
    roi: Optional[Any] = None
    settings: Optional[Any] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TrackedObject(BaseModel):
    track_id: int
    class_name: str
    status: str
    box: List[float]
    owner_track_id: Optional[int] = None
    static_seconds: float = 0.0
    unattended_seconds: float = 0.0


class WorkerStatus(BaseModel):
    camera_id: str
    name: str
    running: bool
    connected: bool
    started_at: Optional[str] = None
    frames_processed: int = 0
    events_emitted: int = 0
    last_error: Optional[str] = None
    tracked_objects: List[TrackedObject] = []
