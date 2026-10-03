"""Undo, redo and the list of what has happened. See :mod:`cosecre_hub.services.history`."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, get_workspace_setting
from ..models import Document, DuplicateRemoval, HistoryAction, HistoryChange, User
from ..services import history
from ..services.sheets import GoogleSheetsService, SheetDocumentNotFound

logger = logging.getLogger(__name__)

router = APIRouter()


class ActionRead(BaseModel):
    id: int
    label: str
    detail: str
    kind: str
    state: str
    user_name: str | None
    mine: bool
    rows: int
    created_at: datetime
    done_at: datetime
    undone_at: datetime | None


class HistoryRead(BaseModel):
    undo: ActionRead | None
    redo: ActionRead | None
    actions: list[ActionRead]


class ReplayResult(BaseModel):
    action: ActionRead
    message: str


# ── Describing an action ─────────────────────────────────────────────────────


def _values(change: HistoryChange) -> dict[str, Any]:
    return {**(change.before or {}), **(change.after or {})}


def _detail(session: Session, action: HistoryAction) -> tuple[str, int]:
    changes = session.query(HistoryChange).filter(HistoryChange.action_id == action.id).order_by(HistoryChange.id)
    rows = changes.count()
    subject = ""
    documents: set[Any] = set()
    for change in changes.limit(60):
        values = _values(change)
        if change.table_name == "documents":
            documents.add(change.pk.get("id"))
            if not subject:
                number = values.get("num_factura")
                if not number:
                    # An update only carries what changed; the row knows the rest.
                    document = session.get(Document, change.pk.get("id"))
                    number = document.num_factura if document else ""
                    values = {"proveidor": document.proveidor if document else "", **values}
                subject = " · ".join(str(v) for v in (number, values.get("proveidor")) if v)
    if not subject:
        for change in changes.limit(60):
            values = _values(change)
            text = (
                values.get("concepte") if change.table_name == "bank_movements"
                else values.get("file_name") if change.table_name == "statement_imports"
                else values.get("nom") if change.table_name == "responsables"
                else None
            )
            if text:
                subject = str(text)
                break
    if len(documents) > 1:
        subject = f"{subject} i {len(documents) - 1} més" if subject else f"{len(documents)} documents"
    return subject, rows


def _read(session: Session, action: HistoryAction, me: User, names: dict[int, str]) -> ActionRead:
    detail, rows = _detail(session, action)
    return ActionRead(
        id=action.id,
        label=action.label,
        detail=detail,
        kind=action.kind,
        state=action.state,
        user_name=names.get(action.user_id) if action.user_id else None,
        mine=action.user_id == me.id,
        rows=rows,
        created_at=action.created_at,
        done_at=action.done_at,
        undone_at=action.undone_at,
    )


def _names(session: Session) -> dict[int, str]:
    return {u.id: u.display_name or u.email for u in session.query(User).all()}


def _undo_target(session: Session, me: User) -> HistoryAction | None:
    return (
        session.query(HistoryAction)
        .filter(HistoryAction.user_id == me.id, HistoryAction.kind == "person", HistoryAction.state == "done")
        .order_by(HistoryAction.done_at.desc(), HistoryAction.id.desc())
        .first()
    )


def _redo_target(session: Session, me: User) -> HistoryAction | None:
    return (
        session.query(HistoryAction)
        .filter(HistoryAction.user_id == me.id, HistoryAction.kind == "person", HistoryAction.state == "undone")
        .order_by(HistoryAction.undone_at.desc(), HistoryAction.id.desc())
        .first()
    )


# ── After a replay: the sheet, Drive and the duplicates log follow ───────────


def after_replay(app, session: Session, changes: list[HistoryChange]) -> None:
    """Bring what is outside the database in line with the rows just replayed."""
    session.expire_all()  # the replay wrote with Core, under the ORM's nose
    service: GoogleSheetsService = app.state.sheet_service
    workspace = get_workspace_setting(session)
    sheet_ready = service.is_ready(workspace)
    seen: dict[Any, dict[str, Any]] = {}
    for change in changes:
        if change.table_name == "documents":
            merged = seen.setdefault(change.pk.get("id"), {})
            # Keep what any step knew: the row's first version has no Drive id yet.
            merged.update({k: v for k, v in _values(change).items() if v not in (None, "")})
    now = datetime.now(UTC)
    for document_id, values in seen.items():
        document = session.get(Document, document_id)
        reference = values.get("internal_doc_number") or (document.internal_doc_number if document else None)
        drive_file_id = values.get("drive_file_id") or (document.drive_file_id if document else None)
        log = (
            session.query(DuplicateRemoval).filter(DuplicateRemoval.reference == reference).first()
            if reference else None
        )
        if document is not None:
            # Back, or changed: the sheet catches up on the next sync.
            document.sheet_state = "pending"
            document.sheet_snapshot = None
            if drive_file_id and service.drive_ready:
                _trash(service, drive_file_id, False)
            if log is not None and log.restored_at is None:
                log.restored_at = now
            continue
        if sheet_ready and reference:
            with app.state.register_lock:
                try:
                    service.delete_row(workspace, service.find_row(workspace, reference))
                except SheetDocumentNotFound:
                    pass
                except Exception:  # noqa: BLE001
                    logger.warning("Could not remove the sheet row of %s", reference, exc_info=True)
        if drive_file_id and service.drive_ready:
            _trash(service, drive_file_id, True)
        if log is not None:
            log.restored_at = None
    session.commit()
    if seen:
        from .documents.register import sync_register

        app.state.register_synced_at = 0.0
        sync_register(app, session, force=True)


def _trash(service: GoogleSheetsService, file_id: str, trashed: bool) -> None:
    try:
        service.trash_drive_file(file_id, trashed=trashed)
    except Exception:  # noqa: BLE001
        logger.warning("Could not %s Drive file %s", "trash" if trashed else "untrash", file_id, exc_info=True)


def _replay(request: Request, session: Session, me: User, target: HistoryAction | None, direction) -> ReplayResult:
    if target is None:
        raise HTTPException(status_code=404, detail="No hi ha res per desfer." if direction == "undo" else "No hi ha res per refer.")
    if direction == "undo" and target.state != "done":
        raise HTTPException(status_code=409, detail="Aquesta acció ja està desfeta.")
    if direction == "redo" and target.state == "done":
        raise HTTPException(status_code=409, detail="Aquesta acció ja està feta.")
    try:
        changes = history.replay(session, target, direction)
        session.commit()
    except history.HistoryConflict as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=f"«{target.label}»: {exc}") from exc
    after_replay(request.app, session, changes)
    session.refresh(target)
    verb = "Desfet" if direction == "undo" else "Refet"
    return ReplayResult(action=_read(session, target, me, _names(session)), message=f"{verb}: {target.label}")


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("", response_model=HistoryRead)
def list_history(
    limit: int = Query(60, ge=1, le=300),
    session: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    names = _names(session)
    actions = session.query(HistoryAction).order_by(HistoryAction.created_at.desc(), HistoryAction.id.desc()).limit(limit).all()
    undo, redo = _undo_target(session, me), _redo_target(session, me)
    return HistoryRead(
        undo=_read(session, undo, me, names) if undo else None,
        redo=_read(session, redo, me, names) if redo else None,
        actions=[_read(session, a, me, names) for a in actions],
    )


@router.post("/undo", response_model=ReplayResult)
def undo_last(request: Request, session: Session = Depends(get_db), me: User = Depends(get_current_user)):
    return _replay(request, session, me, _undo_target(session, me), "undo")


@router.post("/redo", response_model=ReplayResult)
def redo_last(request: Request, session: Session = Depends(get_db), me: User = Depends(get_current_user)):
    return _replay(request, session, me, _redo_target(session, me), "redo")


@router.post("/{action_id}/undo", response_model=ReplayResult)
def undo_action(action_id: int, request: Request, session: Session = Depends(get_db), me: User = Depends(get_current_user)):
    return _replay(request, session, me, session.get(HistoryAction, action_id), "undo")


@router.post("/{action_id}/redo", response_model=ReplayResult)
def redo_action(action_id: int, request: Request, session: Session = Depends(get_db), me: User = Depends(get_current_user)):
    return _replay(request, session, me, session.get(HistoryAction, action_id), "redo")
