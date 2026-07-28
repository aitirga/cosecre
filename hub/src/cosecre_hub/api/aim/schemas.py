"""AIM's wire shapes.

Kept beside the routes rather than in the shared ``schemas/`` package, for the
same reason the models are — see :mod:`cosecre_hub.api.aim.models`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...services.aim import AimPlotSpec, RefinedExercise

AimRole = Literal["teacher", "student"]
AimExerciseStatus = Literal["draft", "published", "archived"]


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


# ── Exercises ───────────────────────────────────────────────────────────────
class AimTopicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    label: str


class AimExerciseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class AimExerciseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    topics: list[str] | None = None
    level: str | None = None


class AimExerciseSummary(BaseModel):
    id: int
    title: str
    status: AimExerciseStatus
    topics: list[str]
    level: str
    owner_id: int
    owner_name: str
    #: True once a version carries a refined body, which is what the wizard's
    #: "ready to run" state actually means.
    refined: bool
    version: int
    updated_at: datetime


class AimVersionRead(BaseModel):
    id: int
    version: int
    raw_blocks: dict[str, Any]
    refined: RefinedExercise | None
    plots: list[AimPlotSpec]


class AimExerciseDetail(AimExerciseSummary):
    current: AimVersionRead | None


class AimDraftWrite(BaseModel):
    raw_blocks: dict[str, Any]


class AimRefineRequest(BaseModel):
    raw_blocks: dict[str, Any]
    #: Free text steering a re-run — "fes-lo més curt", "més graons".
    focus: str | None = None


class AimUsageRead(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class AimRefineResponse(BaseModel):
    version: AimVersionRead
    usage: AimUsageRead


class AimPlotRequest(BaseModel):
    requests: list[str] = Field(default_factory=list)


class AimPlotResponse(BaseModel):
    version: AimVersionRead
    usage: AimUsageRead


class AimPublishRequest(BaseModel):
    topics: list[str] = Field(default_factory=list)
    level: str = ""


# ── Sessions ────────────────────────────────────────────────────────────────
AimSessionStatus = Literal["waiting", "live", "ended"]
AimParticipantStatus = Literal["waiting", "active", "finished"]


class AimSessionCreate(BaseModel):
    exercise_id: int
    token_budget: int | None = Field(default=None, ge=1_000)


class AimSessionRead(BaseModel):
    id: str
    exercise_id: int
    exercise_title: str
    status: AimSessionStatus
    join_code: str
    token_budget: int
    participant_count: int
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None


class AimParticipantRead(BaseModel):
    id: int
    user_id: int
    display_name: str
    status: AimParticipantStatus
    tokens_used: int
    #: Summary refreshes. Billed, but kept off the student's own progress bar.
    context_tokens: int
    effective_budget: int
    turn_count: int
    last_activity_at: datetime | None
    last_message_preview: str
    #: Derived, never stored: several turns with no sign of moving on.
    stuck: bool


class AimParticipantUpdate(BaseModel):
    token_budget_override: int | None = Field(default=None, ge=0)
    status: AimParticipantStatus | None = None


class AimMonitorRead(BaseModel):
    session: AimSessionRead
    participants: list[AimParticipantRead]


class AimJoinRequest(BaseModel):
    code: str = Field(min_length=1, max_length=8)


class AimStudentExercise(BaseModel):
    """What the student is allowed to see: the problem, never the ladder.

    The difficulty ladder and the anticipated issues are the tutor's script.
    Handing them over would be handing over the answers.
    """

    title: str
    statement_md: str
    plots: list[AimPlotSpec]


class AimStudentState(BaseModel):
    state: Literal["idle", "waiting", "live", "ended"]
    session: AimSessionRead | None = None
    participant_id: int | None = None
    exercise: AimStudentExercise | None = None
    tokens_used: int = 0
    effective_budget: int = 0
