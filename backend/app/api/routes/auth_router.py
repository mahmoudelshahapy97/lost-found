# app/api/routes/auth_router.py
"""Login, refresh, logout, and the current user's own profile."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import get_current_user
from app.core.config import config
from app.core.security import validate_password_strength, verify_password
from app.schemas.auth_schemas import (
    AuthUser,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.services.auth_service import auth_service
from app.services.user_service import user_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"], prefix="/auth")


def _set_auth_cookie(response: Response, access_token: str) -> None:
    """The bearer token, mirrored into an httpOnly cookie so the three
    <img src> endpoints (snapshot/frame/crop) can authenticate. See
    app/api/deps.py:get_image_viewer for why this is safe only for reads."""
    response.set_cookie(
        key=config.auth_cookie_name,
        value=access_token,
        httponly=True,
        secure=config.auth_cookie_secure,
        samesite=config.auth_cookie_samesite,
        max_age=config.access_token_expire_minutes * 60,
        path="/",
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, response: Response) -> Dict[str, Any]:
    try:
        result = await auth_service.login(
            payload.username,
            payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password."
            )
        access_token, refresh_token, user = result
        _set_auth_cookie(response, access_token)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": user,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error during login: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login failed.")


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, request: Request, response: Response) -> Dict[str, Any]:
    """Refresh token travels in the body, not the Authorization header -- a
    header is for the access token, and mixing the two makes it easy for a
    client to send the wrong one to the wrong route."""
    try:
        result = await auth_service.refresh(
            payload.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, expired, or already-used refresh token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        access_token, refresh_token, user = result
        _set_auth_cookie(response, access_token)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": user,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error refreshing token: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not refresh token."
        )


@router.post("/logout")
async def logout(payload: RefreshRequest, response: Response) -> Dict[str, Any]:
    """Revokes only this session. Other devices stay logged in -- see
    /logout-all for revoking everywhere."""
    try:
        await auth_service.logout(payload.refresh_token)
        response.delete_cookie(config.auth_cookie_name, path="/")
        return {"success": True, "message": "Logged out."}
    except Exception as e:
        logger.error("Error during logout: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Logout failed.")


@router.post("/logout-all")
async def logout_all(
    response: Response, current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        await auth_service.logout_all(current_user["user_id"])
        response.delete_cookie(config.auth_cookie_name, path="/")
        return {"success": True, "message": "Logged out on every device."}
    except Exception as e:
        logger.error("Error during logout-all: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Logout failed.")


@router.get("/me", response_model=AuthUser)
async def me(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Hydrates the frontend's auth state on load/refresh."""
    return current_user


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest, current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        if not verify_password(payload.current_password, current_user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect."
            )
        ok, message = validate_password_strength(payload.new_password)
        if not ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

        await user_service.set_password(current_user["user_id"], payload.new_password)
        # set_password already bumped token_version; this session's own token
        # is now stale too, so revoke every refresh session for a clean slate.
        await auth_service.logout_all(current_user["user_id"])
        return {"success": True, "message": "Password changed. Please log in again."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error changing password: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not change password."
        )
