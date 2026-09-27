from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    user_id: UUID | None = None
    email: str | None = None


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=255)
    company_name: str | None = Field(None, max_length=255)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str | None
    company_name: str | None
    is_active: bool
    is_verified: bool
    tier: str
    current_period_end: datetime | None
    created_at: datetime


class APIKeyCreate(BaseModel):
    name: str | None = Field(None, max_length=255)
    expires_in_days: int | None = Field(None, ge=1, le=365)


class APIKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key_prefix: str
    key: str | None = None  # Only returned on creation
    name: str | None
    is_active: bool
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class APIKeyList(BaseModel):
    api_keys: list[APIKeyResponse]
    total: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str
