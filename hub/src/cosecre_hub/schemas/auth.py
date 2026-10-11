from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, model_validator

#: Administrador/a runs the hub and its accounts; Secretaria runs the register,
#: statements and requests; Professor/a only sends requests and invoices in.
Role = Literal["admin", "secretaria", "professor"]
AccountStatus = Literal["active", "pending", "expired", "disabled"]


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
    #: Leave empty to invite: the account waits for its owner to choose one.
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


class InviteIssued(BaseModel):
    """Shown to the admin once, right after it is made: only hashes are kept."""

    user: UserRead
    token: str
    code: str
    expires_at: datetime


class InvitePreview(BaseModel):
    """What the activation page shows before a password is chosen."""

    email: EmailStr
    display_name: str | None = None
    role: Role


class ActivateRequest(BaseModel):
    """Open an invitation — by the link's token, or by e-mail plus code."""

    token: str | None = None
    email: EmailStr | None = None
    code: str | None = Field(default=None, max_length=12)
    password: str = Field(min_length=8, max_length=128)
    client: str | None = Field(default=None, max_length=64)
    client_label: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _one_way_in(self):
        if not self.token and not (self.email and self.code):
            raise ValueError("Cal l'enllaç d'invitació o el correu amb el codi.")
        return self
