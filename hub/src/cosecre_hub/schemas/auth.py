from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRead(BaseModel):
    id: int
    email: EmailStr
    display_name: str | None = None
    is_admin: bool
    is_active: bool = True
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    #: Which app is signing in ("web", "desktop", …). Recorded on the session so
    #: a user can see and revoke individual devices.
    client: str | None = Field(default=None, max_length=64)
    client_label: str | None = Field(default=None, max_length=255)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)
    client: str | None = Field(default=None, max_length=64)
    client_label: str | None = Field(default=None, max_length=255)


class RefreshRequest(BaseModel):
    refresh_token: str


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class SessionRead(BaseModel):
    id: int
    client: str | None = None
    client_label: str | None = None
    created_at: datetime
    expires_at: datetime
    current: bool = False


# ------------------------------------------------------------ admin user management


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)
    is_admin: bool = False


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    is_admin: bool | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
