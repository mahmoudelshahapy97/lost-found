# app/api/routes/event_router.py
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import get_image_viewer, require_role
from app.schemas.event_schemas import EventListResponse, EventStatusUpdate
from app.services.event_service import event_service
from app.services.object_store import object_store
from app.services.stream_manager import clip_root
from app.utils.response import create_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"], prefix="/events")


@router.get("", response_model=EventListResponse)
async def list_events(
    camera_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    class_name: Optional[str] = Query(None, description="wallet | hand_watch | key | Glasses | bag | umbrella | mobile_phone"),
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


@router.get(
    "/{event_id}/clip",
    responses={200: {"content": {"video/mp4": {}}, "description": "Evidence clip"}},
)
async def get_event_clip(
    event_id: UUID,
    range_header: Optional[str] = Header(None, alias="Range"),
    current_user: Dict[str, Any] = Depends(get_image_viewer),
) -> Response:
    """Annotated mp4 from before the item was left until after the alert.

    Served with Range support, so a ``<video>`` element can seek - from MinIO,
    or from disk for a clip saved while MinIO was unreachable.
    """
    key, relative = await event_service.get_clip_location(event_id)
    if key:
        size = await object_store.size(key)
        if size:
            return _stream_object(key, size, range_header, event_id)
    if not relative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No clip recorded for this event."
        )

    root = clip_root().resolve()
    path = (root / relative).resolve()
    # clip_path is written by the worker, but never trust a path from the DB
    # to stay inside the clip directory.
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Clip file is missing."
        )
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"event-{event_id}.mp4",
        content_disposition_type="inline",
    )


@router.patch("/{event_id}/status")
async def update_event_status(
    event_id: UUID,
    payload: EventStatusUpdate,
    current_user: Dict[str, Any] = Depends(require_role("operator")),
) -> Dict[str, Any]:
    """Acknowledge, resolve, or dismiss an event as a false positive.

    Optional `action_taken` / `description` record how it was handled. A false
    positive also discards the event's unclaimed found item.
    """
    updated = await event_service.update_status(
        event_id,
        payload.status.value,
        action_taken=(payload.action_taken or "").strip() or None,
        description=(payload.description or "").strip() or None,
        user_id=current_user["user_id"],
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    return create_response(True, "Event status updated.", updated)


def parse_range(header: Optional[str], size: int) -> Optional[tuple]:
    """(start, end) inclusive for a single ``bytes=`` range, None for the whole file.

    Raises ValueError for a range that cannot be satisfied.
    """
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[len("bytes="):].strip().partition("-")
    if not first:  # suffix range: the last N bytes
        length = int(last)
        if length <= 0:
            raise ValueError("empty suffix range")
        return max(0, size - length), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise ValueError("range outside the file")
    return start, end


def _stream_object(key: str, size: int, range_header: Optional[str], event_id: UUID) -> Response:
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="event-{event_id}.mp4"',
    }
    try:
        span = parse_range(range_header, size)
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    start, end = span if span else (0, size - 1)
    length = end - start + 1
    headers["Content-Length"] = str(length)
    if span:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        object_store.iter_range(key, start, length),
        status_code=206 if span else 200,
        media_type="video/mp4",
        headers=headers,
    )
