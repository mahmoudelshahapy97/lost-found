# app/api/routes/analytics_router.py
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_workspace_id, require_role
from app.services.analytics_service import analytics_service
from app.utils.response import create_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analytics"], prefix="/analytics")


@router.get("/summary")
async def analytics_summary(
    days: int = Query(7, ge=1, le=90, description="1 = last 24 hourly buckets, otherwise daily"),
    camera_id: Optional[UUID] = Query(None),
    tz: str = Query("UTC", max_length=64, description="IANA timezone the buckets are cut in"),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
    workspace_id: UUID = Depends(get_workspace_id),
) -> Dict[str, Any]:
    """Everything the Analytics page charts, for one window: KPIs, the alert
    series, the weekday x hour heatmap, per-camera and per-class breakdowns, and
    the detection-to-reunion funnel."""
    try:
        data = await analytics_service.summary(
            days=days, camera_id=camera_id, tz=tz, workspace_id=workspace_id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error("Error computing analytics: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not compute analytics."
        )
    return create_response(True, "Analytics summary.", data)


@router.get("/confidence-audit")
async def confidence_audit(
    days: int = Query(7, ge=1, le=90),
    camera_id: Optional[UUID] = Query(None),
    tz: str = Query("UTC", max_length=64),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
    workspace_id: UUID = Depends(get_workspace_id),
) -> Dict[str, Any]:
    """Model accuracy & confidence audit for the window: detector confidence
    totals, a histogram, the per-camera spread and the latest scored alerts,
    each with the false positives operators marked."""
    try:
        data = await analytics_service.confidence_audit(
            days=days, camera_id=camera_id, tz=tz, workspace_id=workspace_id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error("Error computing the confidence audit: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not compute the confidence audit.",
        )
    return create_response(True, "Confidence audit.", data)
