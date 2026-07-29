"""The tutor conversation.

Deliberately two calls, not one:

``POST .../messages`` is ordinary JSON, so it goes through the client's normal
refresh-and-retry — which replays the whole request, and therefore must never
be the call that is streaming. It writes the student's message and an empty
assistant row and returns.

``GET /messages/{id}/stream`` is the NDJSON one. Being a GET makes it safe to
retry before any bytes are sent, and it is **replayable**: a message that has
already finished emits its stored text and closes. That single property buys
reload-resilience and reconnection for free.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from ...config import Settings
from ...deps import get_db, get_llm_registry, get_settings
from ...services.aim import read_aim_settings
from ...services.aim.context import StudentContextService
from ...services.aim.tutor import AimTutorService
from ...services.llm import Attachment, LLMError, LLMNotConfigured, LLMRegistry, Message
from ...services.storage import IMAGE_CONTENT_TYPES, save_upload_file
from . import strings
from .deps import AimIdentity, get_identity, require_student
from .models import (
    AimAttachment,
    AimExercise,
    AimExerciseVersion,
    AimMessage,
    AimParticipant,
    AimSession,
    AimStudentContext,
)
from .schemas import (
    AimAttachmentRead,
    AimMessageRead,
    AimSendMessage,
    AimSentMessages,
)
from .sessions import effective_budget

router = APIRouter()

#: NDJSON, not SSE. SSE's framing exists for `EventSource`, which cannot send an
#: Authorization header and so was never an option here; one JSON.parse per line
#: is simpler and survives a proxy that has never heard of text/event-stream.
_STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


@router.post(
    "/participants/{participant_id}/attachments",
    response_model=AimAttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    participant_id: int,
    file: UploadFile = File(..., description="A photo of the student's working."),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: AimIdentity = Depends(require_student),
):
    """Store a photo, unattached, until the message that carries it is sent."""
    participant, _ = _own_participation(session, participant_id, identity)

    stored = await save_upload_file(
        file,
        f"aim-{participant.id}-{uuid4().hex[:8]}",
        settings,
        allowed=IMAGE_CONTENT_TYPES,
        subdirectory="aim",
    )
    attachment = AimAttachment(
        participant_id=participant.id,
        stored_path=str(stored),
        content_type=file.content_type or "image/jpeg",
        source_file_name=file.filename or stored.name,
        byte_size=stored.stat().st_size,
    )
    session.add(attachment)
    session.commit()
    return _attachment_read(attachment)


@router.get("/attachments/{attachment_id}/file")
def read_attachment(
    attachment_id: int,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(get_identity),
):
    attachment = session.get(AimAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=strings.ATTACHMENT_NOT_FOUND
        )
    _readable_participation(session, attachment.participant_id, identity)

    path = Path(attachment.stored_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=strings.ATTACHMENT_NOT_FOUND
        )
    return FileResponse(
        path, media_type=attachment.content_type, filename=attachment.source_file_name
    )


@router.get("/participants/{participant_id}/messages", response_model=list[AimMessageRead])
def read_transcript(
    participant_id: int,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(get_identity),
):
    participant, _ = _readable_participation(session, participant_id, identity)
    messages = (
        session.query(AimMessage)
        .filter(AimMessage.participant_id == participant.id)
        .order_by(AimMessage.created_at.asc(), AimMessage.id.asc())
        .all()
    )
    by_message: dict[int, list[AimAttachment]] = {}
    for item in (
        session.query(AimAttachment)
        .filter(AimAttachment.participant_id == participant.id)
        .all()
    ):
        if item.message_id is not None:
            by_message.setdefault(item.message_id, []).append(item)

    return [_message_read(message, by_message.get(message.id)) for message in messages]


@router.post(
    "/participants/{participant_id}/messages",
    response_model=AimSentMessages,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    participant_id: int,
    payload: AimSendMessage,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_student),
):
    participant, record = _own_participation(session, participant_id, identity)
    if record.status != "live":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=strings.SESSION_NOT_LIVE)

    budget = effective_budget(participant, record)
    if participant.tokens_used >= budget:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.BUDGET_SPENT)

    now = datetime.now(UTC)
    question = AimMessage(
        participant_id=participant.id,
        role="user",
        content=payload.content.strip(),
        status="complete",
        completed_at=now,
    )
    session.add(question)
    session.flush()

    if payload.attachment_ids:
        # Only this student's own unattached uploads: an id from somewhere else
        # must not be adoptable by naming it.
        adopted = (
            session.query(AimAttachment)
            .filter(
                AimAttachment.id.in_(payload.attachment_ids),
                AimAttachment.participant_id == participant.id,
                AimAttachment.message_id.is_(None),
            )
            .all()
        )
        for item in adopted:
            item.message_id = question.id

    # Written before the model is called, and committed here, so a connection
    # that drops mid-answer loses the answer but never the question — and the
    # teacher's monitor sees the student's turn immediately.
    reply = AimMessage(participant_id=participant.id, role="assistant", status="streaming")
    session.add(reply)
    participant.last_activity_at = now
    session.commit()

    return AimSentMessages(question=_message_read(question), reply=_message_read(reply))


@router.get("/messages/{message_id}/stream")
def stream_reply(
    message_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_db),
    registry: LLMRegistry = Depends(get_llm_registry),
    identity: AimIdentity = Depends(get_identity),
):
    message = session.get(AimMessage, message_id)
    if message is None or message.role != "assistant":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=strings.MESSAGE_NOT_FOUND)
    participant, record = _readable_participation(session, message.participant_id, identity)

    # Replay. A finished message is its own stream, so a reload mid-answer, a
    # dropped connection, or a teacher opening the transcript all take the same
    # path as the first request.
    if message.status != "streaming":
        return StreamingResponse(
            _replay(message, participant, record),
            media_type="application/x-ndjson",
            headers=_STREAM_HEADERS,
        )

    if identity.user.id != participant.user_id:
        # A teacher may read a finished transcript but must not drive a turn.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_YOUR_CHAT)

    settings = read_aim_settings(session)
    version = session.get(AimExerciseVersion, record.version_id)
    refined = (version.refined if version else None) or {}
    exercise = session.get(AimExercise, record.exercise_id)

    history = _history(session, participant.id, settings.history_window_messages, message.id)
    profile = _profile(session, participant.user_id, record.exercise_id)
    tutor = AimTutorService(registry, model=settings.tutor_model)
    instructions = tutor.build_instructions(
        refined=refined,
        profile=profile.summary if profile else None,
        prior_history=_prior_history(session, participant.user_id, record.exercise_id),
        preamble_override=settings.tutor_preamble_override,
    )

    budget = effective_budget(participant, record)
    remaining = max(0, budget - participant.tokens_used)
    if remaining <= 0:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.BUDGET_SPENT)

    # Clamp a single turn so it cannot blow far past the line. The budget stays
    # advisory — a student with 500 tokens left can still spend more on input —
    # but this bounds how far.
    max_output = min(settings.max_output_tokens, max(64, remaining))

    if participant.turn_count + 1 >= 1 and (
        (participant.turn_count + 1) % settings.context_refresh_every_turns == 0
    ):
        background.add_task(
            refresh_student_context,
            request.app,
            participant.id,
            settings.tutor_model,
        )

    return StreamingResponse(
        _run(
            request.app.state.session_factory,
            tutor=tutor,
            instructions=instructions,
            history=history,
            message_id=message.id,
            participant_id=participant.id,
            max_output=max_output,
            budget=budget,
            exercise_title=exercise.title if exercise else "",
        ),
        media_type="application/x-ndjson",
        headers=_STREAM_HEADERS,
    )


# ──────────────────────────────────────────────────────────────── the stream
def _frame(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _replay(
    message: AimMessage, participant: AimParticipant, record: AimSession
) -> Iterator[str]:
    yield _frame({"type": "start", "message_id": message.id})
    if message.content:
        yield _frame({"type": "delta", "text": message.content})
    if message.status == "failed":
        yield _frame(
            {
                "type": "error",
                "code": "failed",
                "detail": message.error_message or strings.STREAM_LOST,
            }
        )
        return
    yield _frame(
        {
            "type": "usage",
            "input_tokens": message.input_tokens,
            "output_tokens": message.output_tokens,
            "total_tokens": message.total_tokens,
            "tokens_used": participant.tokens_used,
            "token_budget": effective_budget(participant, record),
        }
    )
    yield _frame({"type": "done", "message_id": message.id})


def _run(
    session_factory: sessionmaker,
    *,
    tutor: AimTutorService,
    instructions: str,
    history: list[Message],
    message_id: int,
    participant_id: int,
    max_output: int,
    budget: int,
    exercise_title: str,
) -> Iterator[str]:
    """Generate the answer, then persist it in a session of our own.

    The request-scoped session from `get_db` is closed by its dependency's
    teardown, which races a response that is still producing bytes. Opening a
    short-lived session at the terminal event instead is not a style
    preference — using the injected one here produces detached-instance errors
    that only appear under load.
    """
    yield _frame({"type": "start", "message_id": message_id})

    chunks: list[str] = []
    try:
        for event in tutor.stream_turn(
            instructions=instructions, history=history, max_output_tokens=max_output
        ):
            if event.type == "delta":
                chunks.append(event.text)
                yield _frame({"type": "delta", "text": event.text})
                continue

            totals = _finish(
                session_factory,
                message_id=message_id,
                participant_id=participant_id,
                text=event.text or "".join(chunks),
                usage=event.usage,
            )
            yield _frame(
                {
                    "type": "usage",
                    "input_tokens": event.usage.input_tokens,
                    "output_tokens": event.usage.output_tokens,
                    "total_tokens": event.usage.total_tokens,
                    "tokens_used": totals,
                    "token_budget": budget,
                }
            )
            yield _frame({"type": "done", "message_id": message_id})
            return

    except (LLMError, LLMNotConfigured) as exc:
        detail = strings.NO_MODEL if isinstance(exc, LLMNotConfigured) else str(exc)
        _fail(session_factory, message_id, "".join(chunks), detail)
        yield _frame({"type": "error", "code": "provider_failed", "detail": detail})
        return

    except GeneratorExit:
        # The student navigated away or lost the connection. Keep whatever
        # arrived and charge nothing: no usage was reported, and inventing a
        # number would be worse than under-counting. Deliberate.
        _fail(session_factory, message_id, "".join(chunks), strings.STREAM_LOST)
        raise

    _fail(session_factory, message_id, "".join(chunks), strings.STREAM_LOST)
    yield _frame({"type": "error", "code": "no_completion", "detail": strings.STREAM_LOST})


def _finish(
    session_factory: sessionmaker,
    *,
    message_id: int,
    participant_id: int,
    text: str,
    usage,
) -> int:
    with session_factory() as session:
        message = session.get(AimMessage, message_id)
        participant = session.get(AimParticipant, participant_id)
        if message is None or participant is None:
            return 0

        message.content = text
        message.status = "complete"
        message.input_tokens = usage.input_tokens
        message.output_tokens = usage.output_tokens
        message.total_tokens = usage.total_tokens
        message.completed_at = datetime.now(UTC)

        participant.tokens_used += usage.total_tokens or 0
        participant.turn_count += 1
        participant.last_activity_at = message.completed_at
        session.commit()
        return participant.tokens_used


def _fail(session_factory: sessionmaker, message_id: int, partial: str, detail: str) -> None:
    with session_factory() as session:
        message = session.get(AimMessage, message_id)
        if message is None:
            return
        message.content = partial
        message.status = "failed"
        message.error_message = detail
        message.completed_at = datetime.now(UTC)
        session.commit()


def refresh_student_context(app, participant_id: int, model: str | None) -> None:
    """Rebuild one student's profile after their turn has been answered.

    A BackgroundTask on the streaming response, so it runs once the body is
    fully sent. Its tokens go to `context_tokens`, never to `tokens_used`: a
    progress bar that moves while its owner is not typing reads as a bug.
    """
    with app.state.session_factory() as session:
        participant = session.get(AimParticipant, participant_id)
        if participant is None:
            return
        record = session.get(AimSession, participant.session_id)
        if record is None:
            return
        exercise = session.get(AimExercise, record.exercise_id)

        transcript = [
            (message.role, message.content)
            for message in session.query(AimMessage)
            .filter(AimMessage.participant_id == participant.id, AimMessage.status == "complete")
            .order_by(AimMessage.created_at.asc(), AimMessage.id.asc())
            .all()
        ]
        if not transcript:
            return

        row = (
            session.query(AimStudentContext)
            .filter(
                AimStudentContext.user_id == participant.user_id,
                AimStudentContext.exercise_id == record.exercise_id,
            )
            .first()
        )

        service = StudentContextService(app.state.llm_registry, model=model)
        try:
            summary, usage = service.refresh(
                transcript=transcript,
                previous=row.summary if row else None,
                exercise_title=exercise.title if exercise else "",
            )
        except LLMError:
            # A profile that could not be rebuilt is not worth failing a turn
            # over; the previous one stays and the next refresh tries again.
            return

        if row is None:
            row = AimStudentContext(
                user_id=participant.user_id, exercise_id=record.exercise_id
            )
            session.add(row)
        row.summary = summary
        row.updated_after_turn = participant.turn_count
        participant.context_tokens += usage.total_tokens or 0
        session.commit()


# ─────────────────────────────────────────────────────────────────── helpers
def _own_participation(
    session: Session, participant_id: int, identity: AimIdentity
) -> tuple[AimParticipant, AimSession]:
    participant = session.get(AimParticipant, participant_id)
    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=strings.PARTICIPANT_NOT_FOUND
        )
    if participant.user_id != identity.user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_YOUR_CHAT)
    record = session.get(AimSession, participant.session_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=strings.SESSION_NOT_FOUND)
    return participant, record


def _readable_participation(
    session: Session, participant_id: int, identity: AimIdentity
) -> tuple[AimParticipant, AimSession]:
    """The student themselves, or the teacher running that session. Nobody else."""
    participant = session.get(AimParticipant, participant_id)
    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=strings.PARTICIPANT_NOT_FOUND
        )
    record = session.get(AimSession, participant.session_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=strings.SESSION_NOT_FOUND)
    if identity.user.id not in (participant.user_id, record.teacher_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_YOUR_CHAT)
    return participant, record


def _history(
    session: Session, participant_id: int, window: int, exclude_id: int
) -> list[Message]:
    """The last `window` finished turns.

    Everything older is represented by the student's profile instead. Without
    this the input grows quadratically and a 60k budget is gone in about fifteen
    exchanges — it is the highest-leverage limit in the whole tutoring layer.
    """
    rows = (
        session.query(AimMessage)
        .filter(
            AimMessage.participant_id == participant_id,
            AimMessage.status == "complete",
            AimMessage.id != exclude_id,
            AimMessage.content != "",
        )
        .order_by(AimMessage.created_at.desc(), AimMessage.id.desc())
        .limit(window)
        .all()
    )
    rows = list(reversed(rows))

    photos: dict[int, list[AimAttachment]] = {}
    for item in (
        session.query(AimAttachment)
        .filter(AimAttachment.message_id.in_([row.id for row in rows] or [0]))
        .all()
    ):
        photos.setdefault(item.message_id, []).append(item)

    return [
        Message(
            role=row.role,
            content=row.content,
            attachments=[
                Attachment(path=Path(item.stored_path), mime_type=item.content_type)
                for item in photos.get(row.id, [])
                if Path(item.stored_path).exists()
            ],
        )
        for row in rows
    ]


def _profile(session: Session, user_id: int, exercise_id: int) -> AimStudentContext | None:
    return (
        session.query(AimStudentContext)
        .filter(
            AimStudentContext.user_id == user_id,
            AimStudentContext.exercise_id == exercise_id,
        )
        .first()
    )


def _prior_history(session: Session, user_id: int, exercise_id: int) -> list[str]:
    """One line from each of this student's two most recent other exercises.

    Cross-exercise adaptation without a second table: a student who always
    forgets to check units is worth knowing about before they do it again.
    """
    rows = (
        session.query(AimStudentContext)
        .filter(
            AimStudentContext.user_id == user_id,
            AimStudentContext.exercise_id != exercise_id,
        )
        .order_by(AimStudentContext.updated_at.desc())
        .limit(2)
        .all()
    )
    return [str(row.summary.get("summary", "")) for row in rows if row.summary.get("summary")]


def _attachment_read(attachment: AimAttachment) -> AimAttachmentRead:
    return AimAttachmentRead(
        id=attachment.id,
        content_type=attachment.content_type,
        source_file_name=attachment.source_file_name,
    )


def _message_read(
    message: AimMessage, attachments: list[AimAttachment] | None = None
) -> AimMessageRead:
    return AimMessageRead(
        id=message.id,
        role=message.role,
        content=message.content or "",
        status=message.status,
        total_tokens=message.total_tokens,
        error_message=message.error_message,
        created_at=message.created_at,
        attachments=[_attachment_read(item) for item in attachments or []],
    )
