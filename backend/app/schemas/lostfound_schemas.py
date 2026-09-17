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
    image_similarity: float
    text_similarity: Optional[float] = None
    same_class: bool = False
    same_color: bool = False
    score: float


class MatchListResponse(BaseModel):
    lost_id: Optional[UUID] = None
    count: int
    matches: List[MatchCandidate]


class TextSearchRequest(BaseModel):
    description: str = Field(..., min_length=2, description="e.g. 'black leather backpack'")
    class_name: Optional[str] = None
    top_k: Optional[int] = Field(None, ge=1, le=50)
    min_similarity: Optional[float] = Field(None, ge=0.0, le=1.0)


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
