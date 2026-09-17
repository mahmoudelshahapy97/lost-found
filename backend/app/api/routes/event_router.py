# app/api/routes/event_router.py
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import get_image_viewer, require_role
from app.schemas.event_schemas import EventListResponse, EventStatusUpdate
from app.services.event_service import event_service
from app.utils.response import create_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"], prefix="/events")


@router.get("", response_model=EventListResponse)
async def list_events(
    camera_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    class_name: Optional[str] = Query(None, description="backpack | handbag | suitcase"),
    start: Optional[datetime] = Query(None, description="ISO8601 lower bound on abandoned_at"),
    end: Optional[datetime] = Query(None, description="ISO8601 upper bound on abandoned_at"),
    include_frame: bool = Query(False, description="Embed the annotated frame as base64"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    """Abandoned-object events, newest first."""
    try:
        return await event_service.list_events(
            camera_id=camera_id,
            status=status_filter,
            class_name=class_name,
            start=start,
            end=end,
            include_frame=include_frame,
            page=page,
            per_page=per_page,
        )
    except Exception as e:
        logger.error("Error listing events: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list events."
        )


@router.get("/stats")
async def event_stats(
    camera_id: Optional[UUID] = Query(None),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    """Totals used by dashboards: all-time, currently open, and last 24 hours."""
    try:
        return create_response(True, "Event statistics.", await event_service.stats(camera_id))
    except Exception as e:
        logger.error("Error computing event stats: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not compute stats."
        )


@router.get("/{event_id}")
async def get_event(
    event_id: UUID,
    include_frame: bool = Query(True),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    event = await event_service.get_event(event_id, include_frame=include_frame)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    return event


@router.get(
    "/{event_id}/frame",
    responses={200: {"content": {"image/jpeg": {}}, "description": "Annotated alert frame"}},
)
async def get_event_frame(
    event_id: UUID, current_user: Dict[str, Any] = Depends(get_image_viewer)
) -> Response:
    """The annotated frame captured at the moment the object was declared abandoned."""
    jpeg = await event_service.get_event_frame(event_id)
    if not jpeg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No frame stored for this event."
        )
    return Response(content=jpeg, media_type="image/jpeg")


@router.patch("/{event_id}/status")
async def update_event_status(
    event_id: UUID,
    payload: EventStatusUpdate,
    current_user: Dict[str, Any] = Depends(require_role("operator")),
) -> Dict[str, Any]:
    """Acknowledge, resolve, or dismiss an event as a false positive."""
    updated = await event_service.update_status(event_id, payload.status.value)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    return create_response(True, "Event status updated.", updated)
