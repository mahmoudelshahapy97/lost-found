# app/schemas/event_schemas.py
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class EventStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class EventStatusUpdate(BaseModel):
    status: EventStatus


class EventResponse(BaseModel):
    event_id: UUID
    camera_id: Optional[UUID] = None
    camera_name: Optional[str] = None
    track_key: Optional[str] = None
    class_name: str
    confidence: Optional[float] = None
    bbox: Optional[Dict[str, float]] = None
    owner_track_id: Optional[int] = None
    first_seen_at: Optional[datetime] = None
    abandoned_at: Optional[datetime] = None
    status: str
    found_id: Optional[UUID] = None
    dominant_color: Optional[str] = None
    frame_base64: Optional[str] = None


class EventListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    events: List[EventResponse]


class EventStats(BaseModel):
    total: int = 0
    open: int = 0
    last_24h: int = 0
    last_event_at: Optional[datetime] = None
    by_camera: Optional[List[Dict[str, Any]]] = None
