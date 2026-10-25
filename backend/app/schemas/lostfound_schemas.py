# app/schemas/lostfound_schemas.py
from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LostStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class FoundStatus(str, Enum):
    UNCLAIMED = "UNCLAIMED"
    CLAIMED = "CLAIMED"
    DISCARDED = "DISCARDED"


class LostStatusUpdate(BaseModel):
    status: LostStatus


class FoundStatusUpdate(BaseModel):
    status: FoundStatus


class LostItemResponse(BaseModel):
    lost_id: UUID
    reporter_name: Optional[str] = None
    reporter_email: Optional[str] = None
    description: Optional[str] = None
    class_name: Optional[str] = None
    dominant_color: Optional[str] = None
    lost_after: Optional[datetime] = None
    reported_at: datetime
    status: str
    # When the reporter was emailed that the item was found; detail view only.
    reporter_notified_at: Optional[datetime] = None
    photo_base64: Optional[str] = None


class LostItemListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    lost_items: List[LostItemResponse]


class FoundItemResponse(BaseModel):
    found_id: UUID
    event_id: Optional[UUID] = None
    camera_id: Optional[UUID] = None
    camera_name: Optional[str] = None
    class_name: str
    dominant_color: Optional[str] = None
    found_at: datetime
    status: str


class FoundItemListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    found_items: List[FoundItemResponse]


class MatchCandidate(BaseModel):
    found_id: UUID
    event_id: Optional[UUID] = None
    camera_id: Optional[UUID] = None
    camera_name: Optional[str] = None
    class_name: str
    dominant_color: Optional[str] = None
    found_at: datetime
    status: str
    same_class: bool = False
    same_color: bool = False
    # Likeness of the report's photo to the found crop (perceptual hash + colour
    # histogram), 0-1; None when the report has no photo.
    visual_similarity: Optional[float] = None
    # Weighted mean of type, colour, timing and photo likeness (see matching_service), 0-1.
    score: float
    # Repeat sightings of the same object on the same camera, folded into this one.
    sightings: int = 1
    last_seen_at: Optional[datetime] = None


class MatchListResponse(BaseModel):
    lost_id: Optional[UUID] = None
    count: int
    matches: List[MatchCandidate]


class MatchConfirmRequest(BaseModel):
    lost_id: UUID
    found_id: UUID
    score: float = Field(1.0, ge=0.0, le=1.0)


class ReporterContact(BaseModel):
    """Documents the multipart fields accepted by POST /lost-items."""

    reporter_name: Optional[str] = None
    reporter_email: Optional[EmailStr] = None
    description: Optional[str] = None
    class_name: Optional[str] = None
    lost_after: Optional[datetime] = None
