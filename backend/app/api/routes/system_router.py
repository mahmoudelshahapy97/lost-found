# app/api/routes/system_router.py
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.api.deps import require_role
from app.core.config import config
from app.services.model_registry import model_registry
from app.services.stream_manager import stream_manager
from app.utils.response import create_response

logger = logging.getLogger(__name__)
router = APIRouter(
    tags=["system"], prefix="/system", dependencies=[Depends(require_role("viewer"))]
)


@router.get("/workers")
async def worker_status() -> Dict[str, Any]:
    """State of every camera worker currently held by the stream manager."""
    workers = stream_manager.status()
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
            "matching": {
                "clip_model": f"{config.clip_model_name}/{config.clip_pretrained}",
                "embedding_dim": config.embedding_dim,
                "match_top_k": config.match_top_k,
                "match_min_similarity": config.match_min_similarity,
            },
        },
    )
