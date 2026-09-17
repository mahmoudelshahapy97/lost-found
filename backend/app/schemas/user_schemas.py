# app/schemas/user_schemas.py
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

_VALID_ROLES = {"admin", "operator", "viewer"}


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = Field(None, max_length=120)
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return value


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=120)
    role: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return value


class AdminPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=8)
