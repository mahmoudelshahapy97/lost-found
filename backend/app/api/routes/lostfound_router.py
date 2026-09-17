# app/api/routes/lostfound_router.py
"""Reporting lost items and matching them against the auto-harvested found gallery."""

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
    LostItemListResponse,
    MatchConfirmRequest,
    MatchListResponse,
    TextSearchRequest,
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
    description: Optional[str] = Form(None, description="e.g. 'black leather backpack'"),
    reporter_name: Optional[str] = Form(None),
    reporter_email: Optional[str] = Form(None),
    class_name: Optional[str] = Form(None, description="backpack | handbag | suitcase"),
    lost_after: Optional[datetime] = Form(
        None, description="Only consider items found after this time"
    ),
    current_user: Dict[str, Any] = Depends(require_role("operator")),
) -> Dict[str, Any]:
    """Report a lost item with a photo, a description, or both.

    The photo is embedded with CLIP into the same 512-d space as the object crops
    harvested from the cameras, which is what makes cross-matching possible.
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


@router.get("/lost-items/{lost_id}/matches", response_model=MatchListResponse)
async def get_matches(
    lost_id: UUID,
    top_k: Optional[int] = Query(None, ge=1, le=50),
    min_similarity: Optional[float] = Query(None, ge=0.0, le=1.0),
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
            lost_id, top_k=top_k, min_similarity=min_similarity, persist=persist
        )
        return {"lost_id": lost_id, "count": len(matches), "matches": matches}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error matching lost item %s: %s", lost_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not run matching."
        )


# =================================================================== ad-hoc search
@router.post("/search/image", response_model=MatchListResponse)
async def search_by_image(
    photo: UploadFile = File(..., description="Photo to search the found gallery with"),
    description: Optional[str] = Form(None),
    class_name: Optional[str] = Form(None),
    top_k: Optional[int] = Form(None),
    min_similarity: Optional[float] = Form(None),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    """Search the found gallery with a photo without filing a lost report."""
    try:
        image = await _read_image(photo)
        matches = await matching_service.search_by_image(
            image,
            description=description,
            class_name=class_name,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        return {"lost_id": None, "count": len(matches), "matches": matches}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Image search failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Image search failed."
        )


@router.post("/search/text", response_model=MatchListResponse)
async def search_by_text(
    payload: TextSearchRequest,
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    """Search the found gallery by description alone - CLIP shares one text/image space."""
    try:
        matches = await matching_service.search_by_text(
            payload.description,
            class_name=payload.class_name,
            top_k=payload.top_k,
            min_similarity=payload.min_similarity,
        )
        return {"lost_id": None, "count": len(matches), "matches": matches}
    except Exception as e:
        logger.error("Text search failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Text search failed."
        )


# ================================================================== found items
@router.get("/found-items", response_model=FoundItemListResponse)
async def list_found_items(
    status_filter: Optional[str] = Query(None, alias="status"),
    camera_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> Dict[str, Any]:
    """The found gallery, populated automatically from abandoned-object events."""
    return await matching_service.list_found_items(
        status=status_filter, camera_id=camera_id, page=page, per_page=per_page
    )


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
