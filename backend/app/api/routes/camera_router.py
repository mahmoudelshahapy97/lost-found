# app/api/routes/camera_router.py
import asyncio
import logging
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import get_image_viewer, require_role
from app.schemas.camera_schemas import CameraCreate, CameraResponse, CameraUpdate
from app.services.camera_service import camera_service
from app.services.rtsp_reader import grab_single_frame
from app.services.stream_manager import stream_manager
from app.utils.image_utils import encode_jpeg
from app.utils.response import create_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cameras"], prefix="/cameras")


@router.post("", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(
    payload: CameraCreate, current_user: Dict[str, Any] = Depends(require_role("admin"))
) -> Dict[str, Any]:
    """Register an RTSP camera. Enabled cameras start processing immediately."""
    try:
        if await camera_service.get_camera_by_name(payload.name):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A camera named '{payload.name}' already exists.",
            )

        camera = await camera_service.create_camera(
            name=payload.name,
            rtsp_url=payload.rtsp_url,
            location=payload.location,
            enabled=payload.enabled,
            roi=payload.roi,
            settings=payload.settings,
        )

        if camera["enabled"]:
            await stream_manager.start_camera(camera)

        return camera
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating camera: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create camera."
        )


@router.get("", response_model=List[CameraResponse])
async def list_cameras(
    enabled_only: bool = Query(False),
    current_user: Dict[str, Any] = Depends(require_role("viewer")),
) -> List[Dict[str, Any]]:
    try:
        return await camera_service.list_cameras(enabled_only=enabled_only)
    except Exception as e:
        logger.error("Error listing cameras: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list cameras."
        )


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: UUID, current_user: Dict[str, Any] = Depends(require_role("viewer"))
) -> Dict[str, Any]:
    camera = await camera_service.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")
    return camera


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: UUID,
    payload: CameraUpdate,
    current_user: Dict[str, Any] = Depends(require_role("admin")),
) -> Dict[str, Any]:
    """Patch a camera. A running worker is restarted so changes take effect at once."""
    try:
        if not await camera_service.get_camera(camera_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")

        camera = await camera_service.update_camera(
            camera_id, **payload.model_dump(exclude_unset=True)
        )

        was_running = stream_manager.get_worker(camera_id) is not None
        if was_running:
            await stream_manager.stop_camera(camera_id)
        if camera["enabled"] and was_running:
            await stream_manager.start_camera(camera)

        return camera
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating camera %s: %s", camera_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update camera."
        )


@router.delete("/{camera_id}")
async def delete_camera(
    camera_id: UUID, current_user: Dict[str, Any] = Depends(require_role("admin"))
) -> Dict[str, Any]:
    """Delete a camera and, by cascade, all of its events and found items."""
    try:
        await stream_manager.stop_camera(camera_id)
        deleted = await camera_service.delete_camera(camera_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")
        return create_response(True, "Camera deleted.", {"camera_id": str(camera_id)})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting camera %s: %s", camera_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete camera."
        )


@router.post("/{camera_id}/start")
async def start_camera(
    camera_id: UUID, current_user: Dict[str, Any] = Depends(require_role("operator"))
) -> Dict[str, Any]:
    """Start the detection worker for a camera."""
    try:
        camera = await camera_service.get_camera(camera_id)
        if not camera:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")

        worker_status = await stream_manager.start_camera(camera)
        return create_response(True, "Camera worker started.", worker_status)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error starting camera %s: %s", camera_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not start camera."
        )


@router.post("/{camera_id}/stop")
async def stop_camera(
    camera_id: UUID, current_user: Dict[str, Any] = Depends(require_role("operator"))
) -> Dict[str, Any]:
    stopped = await stream_manager.stop_camera(camera_id)
    if not stopped:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No running worker for this camera."
        )
    return create_response(True, "Camera worker stopped.", {"camera_id": str(camera_id)})


@router.get("/{camera_id}/status")
async def camera_status(
    camera_id: UUID, current_user: Dict[str, Any] = Depends(require_role("viewer"))
) -> Dict[str, Any]:
    """Live worker state including every object currently being tracked."""
    worker = stream_manager.get_worker(camera_id)
    if worker is None:
        return create_response(
            True, "Camera worker is not running.", {"camera_id": str(camera_id), "running": False}
        )
    return create_response(True, "Camera worker status.", worker.status())


@router.get(
    "/{camera_id}/snapshot",
    responses={200: {"content": {"image/jpeg": {}}, "description": "Latest frame"}},
)
async def camera_snapshot(
    camera_id: UUID, current_user: Dict[str, Any] = Depends(get_image_viewer)
) -> Response:
    """Latest frame from the running worker, or a one-shot grab when it is stopped."""
    camera = await camera_service.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")

    worker = stream_manager.get_worker(camera_id)
    frame = worker.last_frame() if worker else None

    if frame is None:
        frame = await asyncio.to_thread(grab_single_frame, camera["rtsp_url"])

    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not read a frame from this camera.",
        )

    jpeg = await asyncio.to_thread(encode_jpeg, frame)
    if not jpeg:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not encode frame."
        )
    return Response(content=jpeg, media_type="image/jpeg")
