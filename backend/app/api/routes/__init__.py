from fastapi import APIRouter

from app.api.routes import (
    auth_router,
    camera_router,
    event_router,
    lostfound_router,
    system_router,
    user_router,
)
from app.core.config import config

# Everything hangs off the versioned API prefix.
router = APIRouter(prefix=config.app_api_prefix)

router.include_router(auth_router.router)
router.include_router(user_router.router)
router.include_router(camera_router.router)
router.include_router(event_router.router)
router.include_router(lostfound_router.router)
router.include_router(system_router.router)
