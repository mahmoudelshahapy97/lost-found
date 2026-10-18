# app/api/routes/system_router.py
import logging
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_workspace_id, require_role
from app.core.config import config
from app.services.model_registry import model_registry
from app.services.object_store import object_store
from app.services.stream_manager import stream_manager
from app.services.workspace_service import workspace_service
from app.utils.response import create_response

logger = logging.getLogger(__name__)
router = APIRouter(
    tags=["system"], prefix="/system", dependencies=[Depends(require_role("viewer"))]
)


@router.get("/workers")
async def worker_status(workspace_id: UUID = Depends(get_workspace_id)) -> Dict[str, Any]:
    """State of the active workspace's camera workers held by the stream manager."""
    cameras = {str(camera_id) for camera_id in await workspace_service.camera_ids(workspace_id)}
    workers = [w for w in stream_manager.status() if str(w.get("camera_id")) in cameras]
    return create_response(
        True,
        f"{len(workers)} worker(s).",
        {
            "count": len(workers),
            "running": sum(1 for w in workers if w["running"]),
            "connected": sum(1 for w in workers if w["connected"]),
            "workers": workers,
        },
    )


@router.get("/config")
async def effective_config() -> Dict[str, Any]:
    """The tuning values in force - useful when an event fires later than expected."""
    return create_response(
        True,
        "Effective configuration.",
        {
            "environment": config.environment,
            "device": model_registry.device,
            "detection": {
                "yolo_model_path": config.yolo_model_path,
                "yolo_confidence": config.yolo_confidence,
                "yolo_input_size": config.yolo_input_size,
                "tracker": config.yolo_tracker,
                "tracked_class_ids": config.tracked_class_ids,
            },
            "abandonment": {
                "static_tolerance_px": config.static_tolerance_px,
                "static_window_seconds": config.static_window_seconds,
                "owner_distance_px": config.owner_distance_px,
                "abandon_distance_px": config.abandon_distance_px,
                "abandon_seconds": config.abandon_seconds,
                "event_cooldown_seconds": config.event_cooldown_seconds,
            },
            "stream": {
                "frame_skip": config.frame_skip,
                "target_process_fps": config.target_process_fps,
            },
            "storage": {
                # Images and videos in MinIO; records and object keys in Postgres.
                "object_store": "minio" if object_store.enabled else "disabled",
                "endpoint": config.minio_endpoint or None,
                "bucket": config.minio_bucket if object_store.enabled else None,
                "reachable": await object_store.healthy() if object_store.enabled else False,
            },
            "matching": {
                "match_top_k": config.match_top_k,
                "match_class_weight": config.match_class_weight,
                "match_color_weight": config.match_color_weight,
                "match_time_weight": config.match_time_weight,
                "match_window_hours": config.match_window_hours,
                "match_min_score": config.match_min_score,
            },
        },
    )
