# app/api/routes/user_router.py
"""Account management. Every route here requires the admin role."""

import logging
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_role
from app.core.security import validate_password_strength
from app.schemas.auth_schemas import AuthUser
from app.schemas.user_schemas import AdminPasswordReset, UserCreate, UserUpdate
from app.services.user_service import user_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["users"], prefix="/users", dependencies=[Depends(require_role("admin"))])


@router.post("", response_model=AuthUser, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate) -> Dict[str, Any]:
    try:
        if await user_service.get_by_username(payload.username):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{payload.username}' is already taken.",
            )
        if await user_service.get_by_email(payload.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{payload.email}' is already registered.",
            )
        ok, message = validate_password_strength(payload.password)
        if not ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

        return await user_service.create_user(
            username=payload.username,
            email=payload.email,
            password=payload.password,
            role=payload.role,
            full_name=payload.full_name,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating user: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create user."
        )


@router.get("", response_model=List[AuthUser])
async def list_users() -> List[Dict[str, Any]]:
    try:
        return await user_service.list_users()
    except Exception as e:
        logger.error("Error listing users: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list users."
        )


@router.get("/{user_id}", response_model=AuthUser)
async def get_user(user_id: UUID) -> Dict[str, Any]:
    user = await user_service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


@router.patch("/{user_id}", response_model=AuthUser)
async def update_user(
    user_id: UUID, payload: UserUpdate, current_user: Dict[str, Any] = Depends(require_role("admin"))
) -> Dict[str, Any]:
    """Demoting or deactivating the last active admin is refused, or an admin
    could lock every admin -- including themself -- out of the console."""
    try:
        target = await user_service.get_by_id(user_id)
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        loses_admin = target["role"] == "admin" and (
            (payload.role is not None and payload.role != "admin")
            or payload.is_active is False
        )
        if loses_admin and await user_service.count_admins(exclude_user_id=user_id) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot remove the last active admin account.",
            )

        updated = await user_service.update_user(
            user_id, full_name=payload.full_name, role=payload.role, is_active=payload.is_active
        )
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating user %s: %s", user_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update user."
        )


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: UUID, payload: AdminPasswordReset) -> Dict[str, Any]:
    try:
        if not await user_service.get_by_id(user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        ok, message = validate_password_strength(payload.new_password)
        if not ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

        await user_service.set_password(user_id, payload.new_password)
        return {"success": True, "message": "Password reset. All of the user's sessions were signed out."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error resetting password for %s: %s", user_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not reset password."
        )


@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID, current_user: Dict[str, Any] = Depends(require_role("admin"))
) -> Dict[str, Any]:
    try:
        target = await user_service.get_by_id(user_id)
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        if user_id == current_user["user_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account."
            )
        if target["role"] == "admin" and await user_service.count_admins(exclude_user_id=user_id) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete the last active admin account.",
            )

        await user_service.delete_user(user_id)
        return {"success": True, "message": "User deleted."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting user %s: %s", user_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete user."
        )
