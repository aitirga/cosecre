"""Keeping the accounting spreadsheet's statement tabs and the database in step.

Every sync does the same two things, in this order:

1. **Read the tabs back.** A line whose "Codi intern factura" or "Núm. factura"
   differs from what was last written there was edited by hand, and that edit
   is applied exactly as the reconciliation buttons would: an invoice typed in
   confirms the line, a cleared cell takes the confirmation back.
2. **Rewrite every tab** from the database, and remember what went into those
   two cells — the baseline the next read compares against.

Comparing against what *was written*, rather than against the database, is what
makes it safe to run after any change: a line confirmed in the app since the
last write still shows its old, empty cell in the sheet, and that is not a
person clearing it.

A change in the app schedules a sync a few seconds later, so a run of
confirmations costs one write; while the hub is awake it also syncs once a
minute (see ``main.sheet_schedule``), and "Sincronitza" in Extractes runs one
at once. The tabs are only rewritten when what they should say has changed,
an edit was read from them, or one is missing — so the minute's check is
usually a single read.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from ..deps import get_current_user, get_db, get_workspace_setting
from ..models import BankMovement, Document, PaymentMatch, User
from ..services.sheets import MirrorTabData
from ..services.statements import mirror

logger = logging.getLogger(__name__)

router = APIRouter()

_lock = threading.Lock()
_timer_lock = threading.Lock()


# ── Results ──────────────────────────────────────────────────────────────────


class MirrorChange(BaseModel):
    codi: str
    compte: str
    #: What happened, for a person: "Justificat amb DOC-…", "Desjustificat".
    text: str


class MirrorIssue(BaseModel):
    codi: str
    compte: str
    #: Why the edit was not applied; the sheet goes back to what the database says.
    text: str


class MirrorStatus(BaseModel):
    configured: bool
    spreadsheet_url: str | None = None
    synced_at: datetime | None = None
    running: bool = False
    error: str | None = None
    tabs: list[str] = []
    applied: list[MirrorChange] = []
    issues: list[MirrorIssue] = []


@dataclass
class _Outcome:
    applied: list[MirrorChange] = field(default_factory=list)
    issues: list[MirrorIssue] = field(default_factory=list)
    tabs: list[str] = field(default_factory=list)
    #: A tab the sheet should have is not there (deleted, or never written).
    tab_missing: bool = False


# ── Sync ─────────────────────────────────────────────────────────────────────


def configured(app, session: Session) -> bool:
    workspace = get_workspace_setting(session)
    return bool(app.state.sheet_service.is_ready(workspace))


def _movements(session: Session) -> list[BankMovement]:
    return (
        session.query(BankMovement)
        .options(selectinload(BankMovement.matches).selectinload(PaymentMatch.document))
        .all()
    )


def _documents_for(session: Session, edit: mirror.Edit) -> tuple[list[Document], str | None]:
    """The register entries an edit names, or why they cannot be found."""
    found: list[Document] = []
    if edit.by == "refs":
        for ref in edit.wanted:
            document = (
                session.query(Document).filter(Document.internal_doc_number.ilike(ref)).one_or_none()
            )
            if document is None:
                return [], f"No hi ha cap entrada del registre amb el codi intern {ref}."
            found.append(document)
        return found, None
    for number in edit.wanted:
        key = mirror.number_key(number)
        matches = [
            d for d in session.query(Document).filter(Document.num_factura != "").all()
            if mirror.number_key(d.num_factura) == key
        ]
        if not matches:
            return [], f"No hi ha cap factura amb el número {number} al registre."
        if len(matches) > 1:
            codes = ", ".join(d.internal_doc_number for d in matches[:4])
            return [], f"Hi ha {len(matches)} factures amb el número {number} ({codes}): posa'n el codi intern."
        found.append(matches[0])
    return found, None


def _apply(app, session: Session, outcome: _Outcome, user_id: int | None) -> None:
    """Read every tab back and apply the hand edits."""
    from .reconciliation import MatchConflict, confirm_documents, undo_movement

    workspace = get_workspace_setting(session)
    movements = _movements(session)
    titles = sorted({mirror.tab_title(m.compte) for m in movements})
    grids = app.state.sheet_service.read_mirror(workspace, titles)
    outcome.tab_missing = any(title not in grids for title in titles)
    by_code = {(m.compte, m.codi.upper()): m for m in movements if m.codi}

    for title, grid in grids.items():
        compte = title.removeprefix(mirror.TAB_PREFIX)
        for line in mirror.parse_tab(grid):
            movement = by_code.get((compte, line.codi.upper()))
            if movement is None:
                outcome.issues.append(MirrorIssue(codi=line.codi, compte=compte, text="Aquest codi no és de cap moviment d'aquest compte."))
                continue
            edit = mirror.edits(movement, line)
            if edit is None:
                continue
            documents, problem = _documents_for(session, edit)
            if problem:
                outcome.issues.append(MirrorIssue(codi=movement.codi, compte=compte, text=problem))
                continue
            current = {d.id for d in mirror.confirmed_documents(movement)}
            if {d.id for d in documents} == current:
                continue
            try:
                if documents:
                    confirm_documents(app, session, movement, documents, user_id)
                    text = "Justificat amb " + ", ".join(
                        f"{d.num_factura or 'sense número'} ({d.internal_doc_number})" for d in documents
                    )
                else:
                    undo_movement(app, session, movement)
                    text = "Ja no està justificat"
            except MatchConflict as conflict:
                session.rollback()
                outcome.issues.append(MirrorIssue(codi=movement.codi, compte=compte, text=str(conflict)))
                continue
            outcome.applied.append(MirrorChange(codi=movement.codi, compte=compte, text=text))
            session.expire_all()


def _fingerprint(data: list[MirrorTabData]) -> str:
    payload = [[tab.title, tab.rows, tab.tones] for tab in data]
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()


def _write(app, session: Session, outcome: _Outcome, *, force: bool = False) -> None:
    """Rewrite every tab from the database and record the new baselines.

    Skipped when the tabs would come out exactly as last written and nothing
    was read from them: nobody needs the same grid twice.
    """
    workspace = get_workspace_setting(session)
    tabs = mirror.build_tabs(_movements(session))
    data = [
        MirrorTabData(
            title=tab.title,
            headers=mirror.HEADERS,
            kinds=[kind for _, kind in mirror.COLUMNS],
            widths=mirror.WIDTHS,
            protected_columns=mirror.BANK_COLUMNS,
            rows=[line.values() for line in tab.lines],
            tones=[line.tone for line in tab.lines],
        )
        for tab in tabs
    ]
    outcome.tabs = [tab.title for tab in tabs]
    fingerprint = _fingerprint(data)
    unchanged = fingerprint == getattr(app.state, "mirror_fingerprint", None)
    if unchanged and not (force or outcome.applied or outcome.issues or outcome.tab_missing):
        return
    app.state.sheet_service.write_mirror(workspace, data)
    app.state.mirror_fingerprint = fingerprint
    for tab in tabs:
        for line in tab.lines:
            line.movement.mirror_refs = line.refs
            line.movement.mirror_numbers = line.numbers
    session.commit()


def sync(app, session: Session, *, user_id: int | None = None, force: bool = False) -> MirrorStatus:
    """Apply the sheet's edits, then rewrite it if needed. Serialised; never raises for Google's sake.

    ``force`` rewrites the tabs even when nothing seems to have changed — what
    a person pressing the button expects.
    """
    workspace = get_workspace_setting(session)
    if not configured(app, session):
        return MirrorStatus(configured=False)
    outcome = _Outcome()
    with _lock:
        app.state.mirror_error = None
        try:
            _apply(app, session, outcome, user_id)
            _write(app, session, outcome, force=force)
            app.state.mirror_synced_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 — Google errors become a status line
            logger.warning("Statements mirror failed", exc_info=True)
            session.rollback()
            app.state.mirror_error = f"No s'ha pogut sincronitzar amb el full: {exc}"[:300]
        if outcome.applied or outcome.issues:
            logger.info("Statements mirror: %d applied, %d issues", len(outcome.applied), len(outcome.issues))
    return _status(app, session, outcome, workspace.spreadsheet_url)


def _status(app, session: Session, outcome: _Outcome | None = None, url: str | None = None) -> MirrorStatus:
    outcome = outcome or _Outcome()
    return MirrorStatus(
        configured=configured(app, session),
        spreadsheet_url=url if url is not None else get_workspace_setting(session).spreadsheet_url,
        synced_at=getattr(app.state, "mirror_synced_at", None),
        running=_lock.locked(),
        error=getattr(app.state, "mirror_error", None),
        tabs=outcome.tabs,
        applied=outcome.applied,
        issues=outcome.issues,
    )


def _run(app) -> None:
    session = app.state.session_factory()
    try:
        sync(app, session)
    except Exception:  # noqa: BLE001
        logger.exception("Statements mirror failed")
        session.rollback()
    finally:
        session.close()


def schedule(app) -> None:
    """Sync a few seconds from now; a later call inside that window joins it."""
    delay = app.state.settings.statement_mirror_delay_seconds
    if delay <= 0:
        _run(app)
        return

    def fire() -> None:
        with _timer_lock:
            app.state.mirror_timer = None
        _run(app)

    with _timer_lock:
        if getattr(app.state, "mirror_timer", None) is not None:
            return
        timer = threading.Timer(delay, fire)
        timer.daemon = True
        app.state.mirror_timer = timer
        timer.start()


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("", response_model=MirrorStatus)
def mirror_status(request: Request, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _status(request.app, session)


@router.post("/sync", response_model=MirrorStatus)
def mirror_sync(request: Request, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Bring the sheet's edits in now, then write it back from the database."""
    if not configured(request.app, session):
        raise HTTPException(status_code=409, detail="El full de càlcul de comptabilitat no està configurat.")
    return sync(request.app, session, user_id=user.id, force=True)
