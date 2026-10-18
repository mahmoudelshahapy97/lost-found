# app/api/routes/lostfound_router.py
"""Lost reports, the searchable found gallery, and rule-based lost <-> found matching."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status

from app.api.deps import get_image_viewer, require_role
from app.core.config import config
from app.schemas.lostfound_schemas import (
    FoundItemListResponse,
    FoundItemResponse,
    FoundStatusUpdate,
    LostItemListResponse,
    LostStatusUpdate,
    MatchConfirmRequest,
    MatchListResponse,
)
from app.services.matching_service import matching_service
from app.utils.image_utils import decode_jpeg
from app.utils.response import create_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["lost-and-found"])

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/bmp"}


async def _read_image(upload: UploadFile) -> np.ndarray:
    """Validate and decode an uploaded photo into a BGR frame."""
    if upload.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported image type '{upload.content_type}'.",
        )

    data = await upload.read()
    if len(data) > config.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image exceeds {config.max_upload_bytes // (1024 * 1024)} MB.",
        )

    image = decode_jpeg(data)
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Could not decode the uploaded image."
        )
    return image


# ============================================================ lost item intake
@router.post("/lost-items", status_code=status.HTTP_201_CREATED)
async def report_lost_item(
    photo: Optional[UploadFile] = File(None, description="Photo of the lost item"),
    description: Optional[str] = Form(None, description="e.g. 'black leather bag'"),
    reporter_name: Optional[str] = Form(None),
    reporter_email: Optional[str] = Form(None),
    class_name: Optional[str] = Form(None, description="wallet | hand_watch | key | Glasses | bag | umbrella | mobile_phone"),
    lost_after: Optional[datetime] = Form(
        None, description="Only consider items found after this time"
    ),
    current_user: Dict[str, Any] = Depends(require_role("operator")),
) -> Dict[str, Any]:
    """Report a lost item with a photo, a description, or both.

    Matching uses the object type, the colour (read from the photo, or a colour
    word in the description) and ``lost_after``; the photo is kept for staff.
    """
    if photo is None and not description:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a photo, a description, or both.",
        )

    try:
        image = await _read_image(photo) if photo is not None else None
        lost_item = await matching_service.create_lost_item(
            image=image,
            description=description,
            reporter_name=reporter_name,
            reporter_email=reporter_email,
            class_name=class_name,
            lost_after=lost_after,
        )
        return create_response(True, "Lost item reported.", dict(lost_item))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error reporting lost item: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not report lost item."
        )


@router.get("/lost-items", response_model=LostItemListResponse)
async def list_lost_items(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    return await matching_service.list_lost_items(
        status=status_filter, page=page, per_page=per_page
    )


@router.get("/lost-items/{lost_id}")
async def get_lost_item(
    lost_id: UUID,
    include_photo: bool = Query(False),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    item = await matching_service.get_lost_item(lost_id, include_photo=include_photo)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lost item not found.")
    return dict(item)


@router.patch("/lost-items/{lost_id}")
async def set_lost_item_status(
    lost_id: UUID,
    payload: LostStatusUpdate,
    current_user: Dict[str, Any] = Depends(require_role("operator")),
) -> Dict[str, Any]:
    """Close a report (OPEN / MATCHED / RESOLVED / CLOSED), or reopen it."""
    updated = await matching_service.set_lost_status(lost_id, payload.status.value)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lost item not found.")
    return create_response(True, "Lost report updated.", updated)


@router.get("/lost-items/{lost_id}/matches", response_model=MatchListResponse)
async def get_matches(
    lost_id: UUID,
    top_k: Optional[int] = Query(None, ge=1, le=50),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    persist: bool = Query(True, description="Store the shortlist for later review"),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    """Rank unclaimed found items against this lost report."""
    try:
        if not await matching_service.get_lost_item(lost_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Lost item not found."
            )

        matches = await matching_service.find_matches_for_lost_item(
            lost_id, top_k=top_k, min_score=min_score, persist=persist
        )
        return {"lost_id": lost_id, "count": len(matches), "matches": matches}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error matching lost item %s: %s", lost_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not run matching."
        )


# ================================================================== found items
@router.get("/found-items", response_model=FoundItemListResponse)
async def list_found_items(
    status_filter: Optional[str] = Query(None, alias="status"),
    camera_id: Optional[UUID] = Query(None),
    class_name: Optional[str] = Query(None, description="wallet | hand_watch | key | Glasses | bag | umbrella | mobile_phone"),
    color: Optional[str] = Query(None, description="Dominant colour, e.g. black, blue, red"),
    start: Optional[datetime] = Query(None, description="ISO8601 lower bound on found_at"),
    end: Optional[datetime] = Query(None, description="ISO8601 upper bound on found_at"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    """The found gallery and the search page: filter by camera, time, type, colour, status."""
    if start and end and start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="'start' is after 'end'."
        )
    return await matching_service.list_found_items(
        status=status_filter,
        camera_id=camera_id,
        class_name=class_name,
        color=color,
        start=start,
        end=end,
        page=page,
        per_page=per_page,
    )


@router.get("/found-items/{found_id}", response_model=FoundItemResponse)
async def get_found_item(
    found_id: UUID,
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    item = await matching_service.get_found_item(found_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Found item not found.")
    return item


@router.patch("/found-items/{found_id}")
async def set_found_item_status(
    found_id: UUID,
    payload: FoundStatusUpdate,
    current_user: Dict[str, Any] = Depends(require_role("operator")),
) -> Dict[str, Any]:
    """Discard an item, restore it to UNCLAIMED, or mark it CLAIMED by hand."""
    updated = await matching_service.set_found_status(found_id, payload.status.value)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Found item not found.")
    return create_response(True, "Found item updated.", updated)


@router.get(
    "/found-items/{found_id}/crop",
    responses={200: {"content": {"image/jpeg": {}}, "description": "Cropped object image"}},
)
async def get_found_crop(
    found_id: UUID, current_user: Dict[str, Any] = Depends(get_image_viewer)
) -> Response:
    jpeg = await matching_service.get_found_crop(found_id)
    if not jpeg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No crop stored for this item."
        )
    return Response(content=jpeg, media_type="image/jpeg")


# ====================================================================== matches
@router.post("/matches/confirm")
async def confirm_match(
    payload: MatchConfirmRequest,
    current_user: Dict[str, Any] = Depends(require_role("operator")),
) -> Dict[str, Any]:
    """Confirm a pairing: the lost report is resolved and the found item is claimed."""
    try:
        match = await matching_service.confirm_match(
            payload.lost_id, payload.found_id, payload.score
        )
        return create_response(True, "Match confirmed.", dict(match) if match else None)
    except Exception as e:
        logger.error("Error confirming match: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not confirm match."
        )


@router.delete("/matches")
async def reject_match(
    lost_id: UUID = Query(...),
    found_id: UUID = Query(...),
    current_user: Dict[str, Any] = Depends(require_role("operator")),
) -> Dict[str, Any]:
    """Remove a suggested pairing so it stops resurfacing."""
    removed = await matching_service.reject_match(lost_id, found_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found.")
    return create_response(True, "Match rejected.")
