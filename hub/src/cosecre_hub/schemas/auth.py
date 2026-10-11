from __future__ import annotations

from datetime import datetime

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field

#: Administrador/a runs the hub and its accounts; Secretaria runs the register,
#: statements and requests; Professor/a only sends requests and invoices in.
Role = Literal["admin", "secretaria", "professor"]
AccountStatus = Literal["active", "pending", "disabled"]


class UserRead(BaseModel):
    id: int
    email: EmailStr
    display_name: str | None = None
    is_admin: bool
    role: Role = "secretaria"
    is_active: bool = True
    #: Computed on the row (``User.account_status``), not stored.
    status: AccountStatus = Field(
        default="active", validation_alias=AliasChoices("status", "account_status")
    )
    created_at: datetime
    last_login_at: datetime | None = None
    password_set_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PersonBrief(BaseModel):
    """Who someone is, as far as another person needs to know: a name and a role."""

    id: int
    name: str
    role: Role

    @classmethod
    def of(cls, user: Any) -> PersonBrief | None:
        if user is None:
            return None
        return cls(id=user.id, name=user.display_name or user.email, role=user.role)


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


class ProfileUpdate(BaseModel):
    """What anyone may change about their own account; the role stays an admin's call."""

    display_name: str | None = Field(default=None, max_length=255)


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
    #: Leave empty and the owner chooses one on their first sign-in.
    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)
    role: Role | None = None
    #: Older clients send this instead of ``role``.
    is_admin: bool = False

    @property
    def resolved_role(self) -> str:
        return self.role or ("admin" if self.is_admin else "secretaria")


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    role: Role | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @property
    def resolved_role(self) -> str | None:
        if self.role is not None:
            return self.role
        if self.is_admin is True:
            return "admin"
        if self.is_admin is False:
            return "secretaria"
        return None


class SetPasswordRequest(BaseModel):
    """A pending account's first sign-in: the e-mail an admin enabled and a new password."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    client: str | None = Field(default=None, max_length=64)
    client_label: str | None = Field(default=None, max_length=255)
