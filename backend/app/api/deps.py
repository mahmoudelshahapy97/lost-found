# app/api/deps.py
"""Route guards: who is calling, and what role does this route require.

HTTPBearer (not OAuth2PasswordBearer) because there is no OAuth2 flow here,
just a bearer token issued by /auth/login -- OAuth2PasswordBearer would add a
form-encoded token endpoint and a Swagger login box neither of which apply.

Every guard re-reads the app_user row rather than trusting the token's role
claim, so deactivating an account or changing its role takes effect on the
very next request instead of waiting for the token to expire.
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import config
from app.core.security import decode_token
from app.services.user_service import user_service

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

ROLE_LEVEL = {"viewer": 1, "operator": 2, "admin": 3}

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def _load_active_user(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not payload:
        raise _UNAUTHORIZED
    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError):
        raise _UNAUTHORIZED

    user = await user_service.get_by_id(user_id)
    if not user or not user["is_active"]:
        raise _UNAUTHORIZED
    if user["token_version"] != payload.get("tv"):
        # Password changed, role changed, or "log out everywhere" was used --
        # this token was minted before that and is no longer good.
        raise _UNAUTHORIZED
    return user


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """Base guard: any authenticated, active account. Every route below
    `require_role` and every route that just needs "logged in" depends on
    this."""
    if not credentials:
        raise _UNAUTHORIZED
    payload = decode_token(credentials.credentials, "access")
    return await _load_active_user(payload)


def require_role(minimum: str):
    """Dependency factory: `Depends(require_role("operator"))` etc. Roles form
    a single ladder (viewer < operator < admin), so "requires operator" also
    admits admin."""

    async def _guard(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if ROLE_LEVEL[user["role"]] < ROLE_LEVEL[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the '{minimum}' role or higher.",
            )
        return user

    return _guard


async def get_image_viewer(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """Guard for the three <img src> endpoints only (camera snapshot, event
    frame, found-item crop): accepts either the bearer header (used by every
    other authenticated fetch) or the httpOnly cookie set at login, since a
    plain <img> tag cannot attach an Authorization header.

    Never use this for a route that changes state -- the cookie is sent
    automatically by the browser on any same-origin request, so trusting it
    for a write would be a CSRF hole. It is safe here only because these three
    routes are pure reads.
    """
    token = credentials.credentials if credentials else request.cookies.get(config.auth_cookie_name)
    if not token:
        raise _UNAUTHORIZED
    payload = decode_token(token, "access")
    return await _load_active_user(payload)
