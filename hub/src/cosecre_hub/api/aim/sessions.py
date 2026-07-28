"""Running an exercise for a class, and watching it happen."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...deps import get_db
from ...models import User
from ...services.aim import read_aim_settings
from . import strings
from .deps import AimIdentity, require_student, require_teacher
from .models import (
    AimExercise,
    AimExerciseVersion,
    AimMessage,
    AimParticipant,
    AimSession,
    AimStudentContext,
)
from .schemas import (
    AimJoinRequest,
    AimMonitorRead,
    AimParticipantRead,
    AimParticipantUpdate,
    AimSessionCreate,
    AimSessionRead,
    AimStudentExercise,
    AimStudentState,
)

router = APIRouter()

#: No vowels and no look-alikes, because this gets read off a projector.
_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXYZ23456789"

#: Student turns with no advance in `current_step` before the monitor says so.
STUCK_AFTER_TURNS = 3


def _new_join_code(session: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if session.query(AimSession).filter(AimSession.join_code == code).first() is None:
            return code
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=strings.NO_JOIN_CODE
    )


# ────────────────────────────────────────────────────────────────── teacher
@router.post("/sessions", response_model=AimSessionRead, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: AimSessionCreate,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    exercise = session.get(AimExercise, payload.exercise_id)
    if exercise is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=strings.EXERCISE_NOT_FOUND
        )
    if exercise.owner_id != identity.user.id and exercise.status != "published":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_YOUR_EXERCISE)

    version = (
        session.get(AimExerciseVersion, exercise.current_version_id)
        if exercise.current_version_id
        else None
    )
    if version is None or not version.refined:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=strings.NOT_REFINED)

    settings = read_aim_settings(session)
    record = AimSession(
        id=str(uuid4()),
        exercise_id=exercise.id,
        # Pinned: editing the exercise mid-class must not change the problem
        # under a student who is halfway through it.
        version_id=version.id,
        teacher_id=identity.user.id,
        join_code=_new_join_code(session),
        token_budget=payload.token_budget or settings.default_token_budget,
    )
    session.add(record)
    session.commit()
    return _session_read(session, record)


@router.get("/sessions", response_model=list[AimSessionRead])
def list_sessions(
    status_filter: str | None = Query(None, alias="status"),
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    query = session.query(AimSession).filter(AimSession.teacher_id == identity.user.id)
    if status_filter:
        query = query.filter(AimSession.status == status_filter)
    return [
        _session_read(session, record)
        for record in query.order_by(AimSession.created_at.desc()).all()
    ]


@router.post("/sessions/{session_id}/start", response_model=AimSessionRead)
def start_session(
    session_id: str,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    record = _owned_session(session, session_id, identity)
    if record.status == "ended":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=strings.SESSION_ENDED)
    record.status = "live"
    record.started_at = record.started_at or datetime.now(UTC)
    session.query(AimParticipant).filter(
        AimParticipant.session_id == record.id, AimParticipant.status == "waiting"
    ).update({"status": "active"})
    session.commit()
    return _session_read(session, record)


@router.post("/sessions/{session_id}/end", response_model=AimSessionRead)
def end_session(
    session_id: str,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    record = _owned_session(session, session_id, identity)
    record.status = "ended"
    record.ended_at = datetime.now(UTC)
    session.query(AimParticipant).filter(AimParticipant.session_id == record.id).update(
        {"status": "finished"}
    )
    session.commit()
    return _session_read(session, record)


@router.get("/sessions/{session_id}/monitor", response_model=AimMonitorRead)
def monitor_session(
    session_id: str,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    record = _owned_session(session, session_id, identity)
    participants = (
        session.query(AimParticipant)
        .filter(AimParticipant.session_id == record.id)
        .order_by(AimParticipant.joined_at.asc())
        .all()
    )
    return AimMonitorRead(
        session=_session_read(session, record),
        participants=[
            _participant_read(session, participant, record) for participant in participants
        ],
    )


@router.patch(
    "/sessions/{session_id}/participants/{participant_id}", response_model=AimParticipantRead
)
def update_participant(
    session_id: str,
    participant_id: int,
    payload: AimParticipantUpdate,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    record = _owned_session(session, session_id, identity)
    participant = session.get(AimParticipant, participant_id)
    if participant is None or participant.session_id != record.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=strings.PARTICIPANT_NOT_FOUND
        )

    if payload.token_budget_override is not None:
        participant.token_budget_override = payload.token_budget_override
    if payload.status is not None:
        participant.status = payload.status
    session.commit()
    return _participant_read(session, participant, record)


# ────────────────────────────────────────────────────────────────── student
@router.get("/student/current", response_model=AimStudentState)
def read_student_state(
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_student),
):
    """Where this student stands, and what they are allowed to see.

    Attaches them to the newest open session on first call: "sign in and wait"
    is the whole interaction, and a join code before that would be friction for
    the common case. The code stays as the escape hatch for two classes at once.
    """
    record = (
        session.query(AimSession)
        .filter(AimSession.status.in_(["waiting", "live"]))
        .order_by(AimSession.created_at.desc())
        .first()
    )

    if record is None:
        # Nothing open. If their last session has just finished, say so rather
        # than dropping them back to an empty screen with no explanation.
        finished = (
            session.query(AimParticipant, AimSession)
            .join(AimSession, AimSession.id == AimParticipant.session_id)
            .filter(AimParticipant.user_id == identity.user.id)
            .order_by(AimSession.created_at.desc())
            .first()
        )
        if finished is None:
            return AimStudentState(state="idle")
        return _student_state(session, finished[0], finished[1])

    participant = (
        session.query(AimParticipant)
        .filter(
            AimParticipant.session_id == record.id, AimParticipant.user_id == identity.user.id
        )
        .first()
    )
    if participant is None:
        participant = AimParticipant(
            session_id=record.id,
            user_id=identity.user.id,
            status="active" if record.status == "live" else "waiting",
        )
        session.add(participant)
        session.commit()

    return _student_state(session, participant, record)


@router.post("/sessions/join", response_model=AimStudentState)
def join_by_code(
    payload: AimJoinRequest,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_student),
):
    record = (
        session.query(AimSession)
        .filter(AimSession.join_code == payload.code.strip().upper())
        .first()
    )
    if record is None or record.status == "ended":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=strings.BAD_JOIN_CODE)

    participant = (
        session.query(AimParticipant)
        .filter(
            AimParticipant.session_id == record.id, AimParticipant.user_id == identity.user.id
        )
        .first()
    )
    if participant is None:
        participant = AimParticipant(
            session_id=record.id,
            user_id=identity.user.id,
            status="active" if record.status == "live" else "waiting",
        )
        session.add(participant)
        session.commit()

    return _student_state(session, participant, record)


# ─────────────────────────────────────────────────────────────────── shared
def _owned_session(session: Session, session_id: str, identity: AimIdentity) -> AimSession:
    record = session.get(AimSession, session_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=strings.SESSION_NOT_FOUND)
    if record.teacher_id != identity.user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_YOUR_SESSION)
    return record


def effective_budget(participant: AimParticipant, record: AimSession) -> int:
    override = participant.token_budget_override
    return override if override is not None else record.token_budget


def _session_read(session: Session, record: AimSession) -> AimSessionRead:
    exercise = session.get(AimExercise, record.exercise_id)
    return AimSessionRead(
        id=record.id,
        exercise_id=record.exercise_id,
        exercise_title=exercise.title if exercise else "",
        status=record.status,
        join_code=record.join_code,
        token_budget=record.token_budget,
        participant_count=session.query(AimParticipant)
        .filter(AimParticipant.session_id == record.id)
        .count(),
        created_at=record.created_at,
        started_at=record.started_at,
        ended_at=record.ended_at,
    )


def _participant_read(
    session: Session, participant: AimParticipant, record: AimSession
) -> AimParticipantRead:
    user = session.get(User, participant.user_id)
    last = (
        session.query(AimMessage)
        .filter(AimMessage.participant_id == participant.id)
        .order_by(AimMessage.created_at.desc())
        .first()
    )
    context = (
        session.query(AimStudentContext)
        .filter(
            AimStudentContext.user_id == participant.user_id,
            AimStudentContext.exercise_id == record.exercise_id,
        )
        .first()
    )
    # Derived rather than stored: several turns since the profile last saw the
    # student move on. It is a prompt for the teacher to look, not a verdict.
    turns_since_progress = participant.turn_count - (
        context.updated_after_turn if context else 0
    )
    stuck = bool(
        participant.turn_count >= STUCK_AFTER_TURNS
        and turns_since_progress >= STUCK_AFTER_TURNS
        and (context.summary.get("consecutive_failures", 0) if context else 0) >= 2
    )

    return AimParticipantRead(
        id=participant.id,
        user_id=participant.user_id,
        display_name=(user.display_name or user.email) if user else "",
        status=participant.status,
        tokens_used=participant.tokens_used,
        context_tokens=participant.context_tokens,
        effective_budget=effective_budget(participant, record),
        turn_count=participant.turn_count,
        last_activity_at=participant.last_activity_at,
        last_message_preview=(last.content or "")[:160] if last else "",
        stuck=stuck,
    )


def _student_state(
    session: Session, participant: AimParticipant, record: AimSession
) -> AimStudentState:
    state = {"live": "live", "ended": "ended"}.get(record.status, "waiting")
    exercise_payload = None

    if record.status == "live":
        version = session.get(AimExerciseVersion, record.version_id)
        refined = (version.refined if version else None) or {}
        exercise_payload = AimStudentExercise(
            title=refined.get("title") or "",
            statement_md=refined.get("statement_md") or "",
            plots=(version.plots if version else None) or [],
        )

    return AimStudentState(
        state=state,
        session=_session_read(session, record),
        participant_id=participant.id,
        exercise=exercise_payload,
        tokens_used=participant.tokens_used,
        effective_budget=effective_budget(participant, record),
    )
