"""AIM's database schema.

Unlike the documents module, whose tables live in the shared ``models.py``
because it inherited a schema that must stay byte-compatible with the original
backend, AIM keeps its ORM, its schemas and its routes inside this one package.
It has no such history, and it is meant to be liftable into a standalone
deployment — which the hub's own "Adding a Cosecre app" contract promises and
nothing has yet had to honour.

Every table is prefixed ``aim_``. All of them are new, so ``create_all`` makes
them and :mod:`cosecre_hub.bootstrap`'s ``ADDED_COLUMNS`` has nothing to say —
that list is for columns added to tables an older database already has, and
becomes relevant the *second* time this ships.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base
from ...models import utcnow

#: An AIM teacher authors and runs exercises; a student answers them. Kept here
#: rather than on ``users`` so that being a maths teacher is not the same claim
#: as administering the hub — an institute has several of the first and one or
#: two of the second.
ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"


class AimMember(Base):
    __tablename__ = "aim_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16), default=ROLE_STUDENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AimExercise(Base):
    """A problem a teacher owns.

    ``topics`` is a JSON list rather than a join table: an institute's library is
    tens of exercises, and filtering that in Python costs nothing measurable
    while a join table costs a migration. :class:`AimTopic` still exists so the
    UI offers a fixed vocabulary instead of free-text tags that fragment.
    """

    __tablename__ = "aim_exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    level: Mapped[str] = mapped_column(String(40), default="")
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AimExerciseVersion(Base):
    """One immutable snapshot of an exercise.

    A running session pins the version it started with, so editing an exercise
    mid-class cannot change the problem under a student who is halfway through it.
    """

    __tablename__ = "aim_exercise_versions"
    __table_args__ = (UniqueConstraint("exercise_id", "version", name="uq_aim_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("aim_exercises.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    #: Exactly what the teacher typed, per wizard step. Kept beside the refined
    #: form so "refine again" starts from the author's words, not the model's.
    raw_blocks: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    refined: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    plots: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AimSession(Base):
    """One class sitting of one exercise."""

    __tablename__ = "aim_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("aim_exercises.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("aim_exercise_versions.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    join_code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    token_budget: Mapped[int] = mapped_column(Integer, default=60_000)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AimParticipant(Base):
    """One student inside one session."""

    __tablename__ = "aim_participants"
    __table_args__ = (UniqueConstraint("session_id", "user_id", name="uq_aim_participant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("aim_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="waiting")
    #: What the student's progress bar shows: tutor turns they asked for.
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    #: Summary refreshes, billed separately. A bar that jumps while the student
    #: is not typing reads as a bug, so this is honest but not shown to them.
    context_tokens: Mapped[int] = mapped_column(Integer, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    token_budget_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AimMessage(Base):
    __tablename__ = "aim_messages"
    __table_args__ = (
        Index("ix_aim_messages_participant_created", "participant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("aim_participants.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    #: ``streaming`` until the answer lands. A row is written before the model is
    #: called, so a dropped connection loses the answer but never the question.
    status: Mapped[str] = mapped_column(String(16), default="complete")
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AimAttachment(Base):
    """A photo a student sent with a message."""

    __tablename__ = "aim_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("aim_participants.id", ondelete="CASCADE"), index=True
    )
    #: Null between upload and the message that carries it.
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("aim_messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    stored_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    source_file_name: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AimStudentContext(Base):
    """What the tutor has learnt about one student on one exercise.

    Keyed by ``(user, exercise)`` rather than by participant so a student who
    redoes an exercise next term inherits their own profile instead of starting
    from nothing.
    """

    __tablename__ = "aim_student_contexts"
    __table_args__ = (UniqueConstraint("user_id", "exercise_id", name="uq_aim_student_context"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("aim_exercises.id", ondelete="CASCADE"), index=True
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_after_turn: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AimTopic(Base):
    """The library's controlled vocabulary."""

    __tablename__ = "aim_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
