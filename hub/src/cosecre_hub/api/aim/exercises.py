"""Authoring exercises, and the library teachers share them through."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...deps import get_db, get_llm_registry
from ...models import User
from ...services.aim import ExerciseAuthoringService, read_aim_settings
from ...services.llm import LLMError, LLMNotConfigured, LLMRegistry
from . import strings
from .deps import AimIdentity, require_member, require_teacher
from .models import AimExercise, AimExerciseVersion, AimSession, AimTopic
from .schemas import (
    AimDraftWrite,
    AimExerciseCreate,
    AimExerciseDetail,
    AimExerciseSummary,
    AimExerciseUpdate,
    AimPlotRequest,
    AimPlotResponse,
    AimPublishRequest,
    AimRefineRequest,
    AimRefineResponse,
    AimTopicRead,
    AimUsageRead,
    AimVersionRead,
)

router = APIRouter()

#: Seeded on first read so the library has a vocabulary before anyone types.
DEFAULT_TOPICS: list[tuple[str, str]] = [
    ("algebra", "Àlgebra"),
    ("funcions", "Funcions"),
    ("geometria", "Geometria"),
    ("trigonometria", "Trigonometria"),
    ("probabilitat", "Probabilitat"),
    ("estadistica", "Estadística"),
    ("derivades", "Derivades"),
    ("integrals", "Integrals"),
    ("nombres", "Nombres i operacions"),
    ("problemes", "Resolució de problemes"),
]


@contextmanager
def _as_llm_errors():
    """Same 503/502 split the model gateway uses, so clients react the same way."""
    try:
        yield
    except LLMNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=strings.NO_MODEL
        ) from exc
    except LLMError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


# ──────────────────────────────────────────────────────────────────── topics
@router.get("/topics", response_model=list[AimTopicRead])
def list_topics(session: Session = Depends(get_db), _: AimIdentity = Depends(require_member)):
    if session.query(AimTopic).count() == 0:
        session.add_all(AimTopic(slug=slug, label=label) for slug, label in DEFAULT_TOPICS)
        session.commit()
    return [
        AimTopicRead.model_validate(topic)
        for topic in session.query(AimTopic).order_by(AimTopic.label.asc()).all()
    ]


# ───────────────────────────────────────────────────────────────── exercises
@router.post("/exercises", response_model=AimExerciseDetail, status_code=status.HTTP_201_CREATED)
def create_exercise(
    payload: AimExerciseCreate,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    exercise = AimExercise(owner_id=identity.user.id, title=payload.title.strip())
    session.add(exercise)
    session.flush()

    version = AimExerciseVersion(
        exercise_id=exercise.id,
        version=1,
        raw_blocks={"title": payload.title.strip()},
        created_by_id=identity.user.id,
    )
    session.add(version)
    session.flush()
    exercise.current_version_id = version.id
    session.commit()

    return _detail(session, exercise)


@router.get("/exercises", response_model=list[AimExerciseSummary])
def list_exercises(
    scope: str = Query("mine", pattern="^(mine|library)$"),
    topic: str | None = None,
    level: str | None = None,
    q: str | None = None,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    """``mine`` is what this teacher owns; ``library`` is what the institute shares.

    A hub *is* an institute, so "shared" needs no registry service — it is every
    published exercise on this server.
    """
    query = session.query(AimExercise)
    if scope == "mine":
        query = query.filter(AimExercise.owner_id == identity.user.id)
    else:
        query = query.filter(AimExercise.status == "published")

    if level:
        query = query.filter(AimExercise.level == level)
    if q:
        query = query.filter(AimExercise.title.ilike(f"%{q}%"))

    exercises = query.order_by(AimExercise.updated_at.desc()).all()
    # Topics are a JSON list, so this one filter happens in Python. An
    # institute's library is tens of exercises; a join table plus its migration
    # would cost more than it saves.
    if topic:
        exercises = [item for item in exercises if topic in (item.topics or [])]

    return [_summary(session, item) for item in exercises]


@router.get("/exercises/{exercise_id}", response_model=AimExerciseDetail)
def read_exercise(
    exercise_id: int,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    return _detail(session, _readable(session, exercise_id, identity))


@router.patch("/exercises/{exercise_id}", response_model=AimExerciseDetail)
def update_exercise(
    exercise_id: int,
    payload: AimExerciseUpdate,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    exercise = _owned(session, exercise_id, identity)
    if payload.title is not None:
        exercise.title = payload.title.strip()
    if payload.topics is not None:
        exercise.topics = payload.topics
    if payload.level is not None:
        exercise.level = payload.level
    session.commit()
    return _detail(session, exercise)


@router.put("/exercises/{exercise_id}/draft", response_model=AimVersionRead)
def save_draft(
    exercise_id: int,
    payload: AimDraftWrite,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    """Autosave from the wizard.

    Writes in place rather than creating a version per keystroke; a new version
    is minted only when a session pins one.
    """
    exercise = _owned(session, exercise_id, identity)
    version = _current_version(session, exercise)
    version.raw_blocks = payload.raw_blocks
    if title := str(payload.raw_blocks.get("title") or "").strip():
        exercise.title = title[:255]
    session.commit()
    return _version_read(version)


@router.post("/exercises/{exercise_id}/refine", response_model=AimRefineResponse)
def refine_exercise(
    exercise_id: int,
    payload: AimRefineRequest,
    session: Session = Depends(get_db),
    registry: LLMRegistry = Depends(get_llm_registry),
    identity: AimIdentity = Depends(require_teacher),
):
    exercise = _owned(session, exercise_id, identity)
    version = _current_version(session, exercise)
    settings = read_aim_settings(session)
    service = ExerciseAuthoringService(registry, model=settings.authoring_model)

    with _as_llm_errors():
        refined, usage = service.refine(payload.raw_blocks, focus=payload.focus)

    version.raw_blocks = payload.raw_blocks
    version.refined = refined.model_dump()
    if refined.title:
        exercise.title = refined.title[:255]
    if refined.suggested_topics and not exercise.topics:
        known = {slug for (slug,) in session.query(AimTopic.slug).all()}
        exercise.topics = [item for item in refined.suggested_topics if item in known]
    if refined.suggested_level and not exercise.level:
        exercise.level = refined.suggested_level[:40]
    session.commit()

    return AimRefineResponse(version=_version_read(version), usage=_usage(usage))


@router.post("/exercises/{exercise_id}/plots", response_model=AimPlotResponse)
def generate_plots(
    exercise_id: int,
    payload: AimPlotRequest,
    session: Session = Depends(get_db),
    registry: LLMRegistry = Depends(get_llm_registry),
    identity: AimIdentity = Depends(require_teacher),
):
    exercise = _owned(session, exercise_id, identity)
    version = _current_version(session, exercise)
    settings = read_aim_settings(session)
    service = ExerciseAuthoringService(registry, model=settings.authoring_model)

    refined = version.refined or {}
    context = f"{exercise.title}\n\n{refined.get('statement_md', '')}".strip()
    requests = payload.requests or list(refined.get("plot_requests") or [])

    with _as_llm_errors():
        plots, usage = service.plots(context, requests)

    version.plots = [plot.model_dump() for plot in plots]
    session.commit()
    return AimPlotResponse(version=_version_read(version), usage=_usage(usage))


@router.post("/exercises/{exercise_id}/publish", response_model=AimExerciseDetail)
def publish_exercise(
    exercise_id: int,
    payload: AimPublishRequest,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    exercise = _owned(session, exercise_id, identity)
    version = _current_version(session, exercise)
    if not version.refined:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=strings.NOT_REFINED)

    exercise.topics = payload.topics
    exercise.level = payload.level
    exercise.status = "published"
    exercise.published_at = datetime.now(UTC)
    session.commit()
    return _detail(session, exercise)


@router.post(
    "/exercises/{exercise_id}/clone",
    response_model=AimExerciseDetail,
    status_code=status.HTTP_201_CREATED,
)
def clone_exercise(
    exercise_id: int,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    """Take a colleague's published exercise as your own draft."""
    source = _readable(session, exercise_id, identity)
    source_version = _current_version(session, source)

    clone = AimExercise(
        owner_id=identity.user.id,
        title=source.title,
        topics=list(source.topics or []),
        level=source.level,
    )
    session.add(clone)
    session.flush()

    version = AimExerciseVersion(
        exercise_id=clone.id,
        version=1,
        raw_blocks=dict(source_version.raw_blocks or {}),
        refined=dict(source_version.refined) if source_version.refined else None,
        plots=list(source_version.plots or []),
        created_by_id=identity.user.id,
    )
    session.add(version)
    session.flush()
    clone.current_version_id = version.id
    session.commit()
    return _detail(session, clone)


@router.delete("/exercises/{exercise_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exercise(
    exercise_id: int,
    session: Session = Depends(get_db),
    identity: AimIdentity = Depends(require_teacher),
):
    exercise = _owned(session, exercise_id, identity)
    # Deleting would cascade into transcripts a student is entitled to read, so
    # an exercise that has ever been run is archived instead.
    if session.query(AimSession).filter(AimSession.exercise_id == exercise.id).count():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=strings.EXERCISE_IN_USE)
    session.delete(exercise)
    session.commit()


# ─────────────────────────────────────────────────────────────────── helpers
def _owned(session: Session, exercise_id: int, identity: AimIdentity) -> AimExercise:
    exercise = session.get(AimExercise, exercise_id)
    if exercise is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=strings.EXERCISE_NOT_FOUND
        )
    if exercise.owner_id != identity.user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_YOUR_EXERCISE)
    return exercise


def _readable(session: Session, exercise_id: int, identity: AimIdentity) -> AimExercise:
    """Yours, or anything published — which is what the library means."""
    exercise = session.get(AimExercise, exercise_id)
    if exercise is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=strings.EXERCISE_NOT_FOUND
        )
    if exercise.owner_id != identity.user.id and exercise.status != "published":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_YOUR_EXERCISE)
    return exercise


def _current_version(session: Session, exercise: AimExercise) -> AimExerciseVersion:
    version = (
        session.get(AimExerciseVersion, exercise.current_version_id)
        if exercise.current_version_id
        else None
    )
    if version is None:
        version = AimExerciseVersion(exercise_id=exercise.id, version=1, raw_blocks={})
        session.add(version)
        session.flush()
        exercise.current_version_id = version.id
    return version


def _version_read(version: AimExerciseVersion) -> AimVersionRead:
    return AimVersionRead.model_validate(
        {
            "id": version.id,
            "version": version.version,
            "raw_blocks": version.raw_blocks or {},
            "refined": version.refined,
            "plots": version.plots or [],
        }
    )


def _summary(session: Session, exercise: AimExercise) -> AimExerciseSummary:
    version = (
        session.get(AimExerciseVersion, exercise.current_version_id)
        if exercise.current_version_id
        else None
    )
    owner = session.get(User, exercise.owner_id)
    return AimExerciseSummary(
        id=exercise.id,
        title=exercise.title,
        status=exercise.status,
        topics=list(exercise.topics or []),
        level=exercise.level,
        owner_id=exercise.owner_id,
        owner_name=(owner.display_name or owner.email) if owner else "",
        refined=bool(version and version.refined),
        version=version.version if version else 0,
        updated_at=exercise.updated_at,
    )


def _detail(session: Session, exercise: AimExercise) -> AimExerciseDetail:
    version = (
        session.get(AimExerciseVersion, exercise.current_version_id)
        if exercise.current_version_id
        else None
    )
    return AimExerciseDetail(
        **_summary(session, exercise).model_dump(),
        current=_version_read(version) if version else None,
    )


def _usage(usage) -> AimUsageRead:
    return AimUsageRead(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )
