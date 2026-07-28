"""AIM's wire shapes.

Kept beside the routes rather than in the shared ``schemas/`` package, for the
same reason the models are — see :mod:`cosecre_hub.api.aim.models`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

AimRole = Literal["teacher", "student"]


class AimIdentityRead(BaseModel):
    """Who the caller is, as far as AIM is concerned.

    ``role`` is null for someone with a hub account and no business in AIM — an
    invoice clerk on a shared hub — and the client uses that to hide the module
    entirely rather than show them a maths waiting room.
    """

    user_id: int
    role: AimRole | None
    is_hub_admin: bool
    #: True when the role was inferred from hub admin rather than granted, which
    #: is what lets the roster screen show it as a default rather than a choice.
    implicit: bool


class AimMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: str
    display_name: str | None
    role: AimRole
    implicit: bool


class AimMemberUpdate(BaseModel):
    role: AimRole


class AimCandidateRead(BaseModel):
    """A hub user who is not yet in AIM.

    Three fields and no more: an AIM teacher is not necessarily a hub admin, so
    this deliberately exposes far less than ``GET /users`` does.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None
