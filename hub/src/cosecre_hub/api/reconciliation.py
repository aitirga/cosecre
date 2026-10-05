"""Justifying statements: the AI proposes, a person confirms.

Nothing here runs on its own. A run starts when someone presses "Començar
justificació", goes over the movements nobody has looked at yet, and leaves
proposals behind. Confirming one is what writes to the register.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from ..deps import get_current_user, get_db, get_workspace_setting
from ..models import BankMovement, Document, MatchRun, PaymentMatch, StatementImport, User
from ..schemas.statements import (
    ConfirmRequest,
    DocumentBrief,
    MatchRead,
    MovementDetail,
    MovementRead,
    PaymentRead,
    ReconcileStatement,
    RunRead,
    RunRequest,
)
from ..services.matching import engine
from ..services.matching.confidence import band
from ..services.statements import PAYMENT
from .documents.register import push_document
from .statements.routes import to_document_brief as _brief
from .statements.routes import to_movement_read, to_statement_read

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Reading ──────────────────────────────────────────────────────────────────


def _match_read(match: PaymentMatch) -> MatchRead:
    signals = dict(match.signals or {})
    return MatchRead(
        id=match.id,
        status=match.status,
        rank=match.rank,
        confidence=match.confidence,
        band=band(match.confidence),
        decided_by=match.decided_by,
        reason=match.reason,
        group=int(signals.pop("group", 0) or 0),
        signals=signals,
        ai_trace=match.ai_trace,
        document=_brief(match.document),
    )


def _with_matches(query):
    return query.options(selectinload(BankMovement.matches).selectinload(PaymentMatch.document))


@router.get("/statements", response_model=list[ReconcileStatement])
def statements(session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Every statement, with how far its justification has got."""
    rows = (
        session.query(StatementImport)
        .options(selectinload(StatementImport.created_by))
        .order_by(StatementImport.period_to.desc(), StatementImport.created_at.desc())
        .all()
    )
    movements = _with_matches(session.query(BankMovement)).all()
    by_statement: dict[int, list[BankMovement]] = {}
    for movement in movements:
        by_statement.setdefault(movement.import_id, []).append(movement)
    result = []
    for statement in rows:
        own = by_statement.get(statement.id, [])
        statuses = Counter(m.match_status for m in own)
        bands = Counter(
            band(to_movement_read(m).confidence) for m in own if m.match_status == "proposed"
        )
        result.append(
            ReconcileStatement(
                **to_statement_read(statement).model_dump(),
                payments=sum(1 for m in own if m.categoria == PAYMENT),
                unmatched=statuses["unmatched"],
                proposed=statuses["proposed"],
                confirmed=statuses["confirmed"],
                rejected=statuses["rejected"] + statuses["no_match"],
                not_applicable=statuses["not_applicable"],
                bands=dict(bands),
            )
        )
    return result


@router.get("/movements", response_model=list[MovementRead])
def movements(
    statement: int | None = None,
    status: str | None = Query(None, description="Comma-separated match statuses."),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = _with_matches(session.query(BankMovement))
    if statement is not None:
        query = query.filter(BankMovement.import_id == statement)
    if status:
        query = query.filter(BankMovement.match_status.in_(status.split(",")))
    return [to_movement_read(m) for m in query.order_by(BankMovement.data.desc(), BankMovement.id).all()]


def _movement(session: Session, movement_id: int) -> BankMovement:
    movement = _with_matches(session.query(BankMovement)).filter(BankMovement.id == movement_id).first()
    if movement is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat el moviment.")
    return movement


def _detail(session: Session, movement: BankMovement) -> MovementDetail:
    linked = session.get(BankMovement, movement.linked_movement_id) if movement.linked_movement_id else None
    matches = sorted(
        (m for m in movement.matches if m.document is not None),
        key=lambda m: ({"confirmed": 0, "proposed": 1, "alternative": 2, "rejected": 3}.get(m.status, 4), m.rank, -m.confidence),
    )
    return MovementDetail(
        **to_movement_read(movement).model_dump(),
        matches=[_match_read(m) for m in matches],
        linked_movement=to_movement_read(linked) if linked else None,
    )


@router.get("/movements/{movement_id}", response_model=MovementDetail)
def movement_detail(movement_id: int, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _detail(session, _movement(session, movement_id))


@router.get("/documents/search", response_model=list[DocumentBrief])
def search_documents(
    q: str = "", session: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """For linking by hand: number, supplier, CIF or amount."""
    text = q.strip()
    query = session.query(Document)
    if text:
        like = f"%{text}%"
        clauses = [
            Document.num_factura.ilike(like),
            Document.proveidor.ilike(like),
            Document.cif_proveidor.ilike(like),
            Document.internal_doc_number.ilike(like),
        ]
        try:
            amount = abs(float(text.replace("€", "").replace(".", "").replace(",", ".")))
            clauses.append(Document.import_value.between(amount - 0.011, amount + 0.011))
        except ValueError:
            pass
        query = query.filter(or_(*clauses))
    documents = query.order_by(Document.data_factura.desc()).limit(20).all()
    return [_brief(d) for d in documents]


@router.get("/documents/{reference}/payments", response_model=list[PaymentRead])
def document_payments(reference: str, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    document = session.query(Document).filter(Document.internal_doc_number == reference).first()
    if document is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat el document.")
    matches = (
        session.query(PaymentMatch)
        .filter(PaymentMatch.document_id == document.id, PaymentMatch.status.in_(["confirmed", "proposed"]))
        .all()
    )
    return [
        PaymentRead(
            movement_id=m.movement.id,
            import_id=m.movement.import_id,
            status=m.status,
            confidence=m.confidence,
            compte=m.movement.compte,
            tipus=m.movement.tipus,
            data=m.movement.data,
            concepte=m.movement.concepte,
            mes_dades=m.movement.mes_dades,
            import_value=m.movement.import_value,
        )
        for m in matches
    ]


# ── Running ──────────────────────────────────────────────────────────────────


def _run_read(run: MatchRun) -> RunRead:
    return RunRead(
        id=run.id,
        import_id=run.import_id,
        status=run.status,
        total=run.total,
        processed=run.processed,
        proposed=run.proposed,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _pending_ids(session: Session, import_id: int | None) -> list[int]:
    query = session.query(BankMovement.id).filter(
        BankMovement.match_status == "unmatched", BankMovement.categoria == PAYMENT
    )
    if import_id is not None:
        query = query.filter(BankMovement.import_id == import_id)
    return [row[0] for row in query.order_by(BankMovement.data.desc()).all()]


def _match_one(app, movement_id: int) -> bool:
    session = app.state.session_factory()
    try:
        movement = session.get(BankMovement, movement_id)
        if movement is None or movement.match_status != "unmatched":
            return False
        workspace = get_workspace_setting(session)
        classifier = app.state.classifier
        outcome = engine.match_movement(
            session,
            movement,
            registry=app.state.llm_registry,
            jev=getattr(classifier, "jev", None),
            model=workspace.openai_model,
        )
        return outcome.proposed
    except Exception:  # noqa: BLE001 — one movement failing must not stop the run
        logger.exception("Matching movement %s failed", movement_id)
        session.rollback()
        return False
    finally:
        session.close()


def _bump(app, run_id: int, proposed: bool) -> None:
    session = app.state.session_factory()
    try:
        run = session.get(MatchRun, run_id)
        run.processed += 1
        run.proposed += int(proposed)
        session.commit()
    finally:
        session.close()


async def execute_run(app, run_id: int, movement_ids: list[int]) -> None:
    """Every pending movement, several at a time; progress is saved as each one ends."""
    lock = asyncio.Lock()

    async def one(movement_id: int) -> None:
        async with app.state.extraction_limiter:
            proposed = await run_in_threadpool(_match_one, app, movement_id)
        async with lock:
            await run_in_threadpool(_bump, app, run_id, proposed)

    error = None
    try:
        await asyncio.gather(*(one(movement_id) for movement_id in movement_ids))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Matching run %s failed", run_id)
        error = str(exc)[:300]
    session = app.state.session_factory()
    try:
        withdrawn = engine.resolve_conflicts(session, movement_ids)
        run = session.get(MatchRun, run_id)
        run.proposed = max(0, run.proposed - withdrawn)
        run.status = "error" if error else "done"
        run.error_message = error
        run.finished_at = datetime.now(UTC)
        session.commit()
    finally:
        session.close()


@router.post("/runs", response_model=RunRead)
def start_run(
    payload: RunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Propose invoices for every movement of a statement nobody has looked at yet."""
    running = (
        session.query(MatchRun)
        .filter(MatchRun.status == "running", MatchRun.import_id == payload.import_id)
        .first()
    )
    if running is not None:
        return _run_read(running)
    if not request.app.state.llm_registry.any_configured():
        logger.info("Matching without a model: only rule-decided proposals will be made")
    ids = _pending_ids(session, payload.import_id)
    run = MatchRun(import_id=payload.import_id, total=len(ids), started_by_id=user.id)
    if not ids:
        run.status = "done"
        run.finished_at = datetime.now(UTC)
    session.add(run)
    session.commit()
    if ids:
        background_tasks.add_task(execute_run, request.app, run.id, ids)
    return _run_read(run)


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(run_id: int, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    run = session.get(MatchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat l'execució.")
    return _run_read(run)


@router.get("/runs", response_model=RunRead | None)
def active_run(
    statement: int | None = None, session: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """The run in progress for a statement, so a reloaded page picks its progress back up."""
    run = (
        session.query(MatchRun)
        .filter(MatchRun.status == "running", MatchRun.import_id == statement)
        .order_by(MatchRun.id.desc())
        .first()
    )
    return _run_read(run) if run else None


# ── Deciding ─────────────────────────────────────────────────────────────────


@router.post("/movements/{movement_id}/confirm", response_model=MovementDetail)
def confirm(
    movement_id: int,
    payload: ConfirmRequest,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """This movement paid these invoices. Fills in their payment fields."""
    movement = _movement(session, movement_id)
    documents = session.query(Document).filter(Document.internal_doc_number.in_(payload.document_refs)).all()
    if len(documents) != len(set(payload.document_refs)):
        raise HTTPException(status_code=404, detail="Alguna factura no existeix.")
    taken = (
        session.query(PaymentMatch)
        .filter(
            PaymentMatch.document_id.in_([d.id for d in documents]),
            PaymentMatch.status == "confirmed",
            PaymentMatch.movement_id != movement.id,
        )
        .first()
    )
    if taken is not None:
        raise HTTPException(
            status_code=409, detail="Aquesta factura ja està justificada amb un altre moviment."
        )

    now = datetime.now(UTC)
    chosen = {d.id for d in documents}
    existing = {m.document_id: m for m in movement.matches}
    for match in movement.matches:
        if match.document_id not in chosen and match.status != "rejected":
            match.status = "rejected"
    for document in documents:
        match = existing.get(document.id)
        if match is None:
            match = PaymentMatch(
                movement_id=movement.id,
                document_id=document.id,
                confidence=100,
                decided_by="person",
                reason="Vinculada a mà.",
                signals={},
            )
            session.add(match)
        match.status = "confirmed"
        match.confirmed_by_id = user.id
        match.confirmed_at = now

        document.pagament = "Pagat"
        document.data_pagament = movement.data
        if movement.tipus:
            document.metode_pagament = movement.tipus
        document.pressupost_afectat = movement.compte
        document.sheet_state = "pending"

        # Anyone else's proposal for this invoice is now wrong.
        for other in (
            session.query(PaymentMatch)
            .filter(
                PaymentMatch.document_id == document.id,
                PaymentMatch.movement_id != movement.id,
                PaymentMatch.status.in_(["proposed", "alternative"]),
            )
            .all()
        ):
            other.status = "rejected"
            if other.rank == 0 and other.movement.match_status == "proposed":
                other.movement.match_status = "unmatched"
    movement.match_status = "confirmed"
    session.commit()

    for document in documents:
        try:
            push_document(request.app, session, document)
            session.commit()
        except Exception:  # noqa: BLE001 — the database has it; the sheet catches up on the next sync
            logger.warning("Could not push %s to the sheet", document.internal_doc_number, exc_info=True)
            session.rollback()
    session.expire_all()
    return _detail(session, _movement(session, movement_id))


@router.post("/movements/{movement_id}/reject", response_model=MovementDetail)
def reject(movement_id: int, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """"Cap factura": this movement has no invoice in the register."""
    movement = _movement(session, movement_id)
    if movement.match_status == "confirmed":
        raise HTTPException(status_code=409, detail="Aquest moviment ja està justificat. Desfés-ho primer.")
    for match in movement.matches:
        match.status = "rejected"
    movement.match_status = "rejected"
    session.commit()
    return _detail(session, _movement(session, movement_id))


@router.post("/matches/{match_id}/reject", response_model=MovementDetail)
def reject_match(match_id: int, session: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """"No és aquesta": drop one proposal and put the next candidate forward."""
    match = session.get(PaymentMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat la proposta.")
    movement = match.movement
    if match.status == "confirmed":
        raise HTTPException(status_code=409, detail="Aquesta proposta ja està confirmada.")
    group = (match.signals or {}).get("group")
    for other in movement.matches:
        if other.status in {"proposed", "alternative"} and (other.signals or {}).get("group") == group:
            other.status = "rejected"
    remaining = sorted(
        (m for m in movement.matches if m.status in {"proposed", "alternative"}), key=lambda m: m.rank
    )
    if remaining and not any(m.status == "proposed" for m in remaining):
        next_group = (remaining[0].signals or {}).get("group")
        for other in remaining:
            if (other.signals or {}).get("group") == next_group:
                other.status = "proposed"
                other.rank = 0
    movement.match_status = "proposed" if remaining else "no_match"
    session.commit()
    return _detail(session, _movement(session, movement.id))


@router.post("/movements/{movement_id}/undo", response_model=MovementDetail)
def undo(
    movement_id: int,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Take back a confirmation or a "Cap factura". Invoice fields already written stay as they are."""
    movement = _movement(session, movement_id)
    unjustified = [m.document for m in movement.matches if m.status == "confirmed" and m.document]
    for match in list(movement.matches):
        if match.status == "confirmed" and match.decided_by == "person":
            session.delete(match)
        elif match.status in {"confirmed", "rejected"}:
            match.status = "alternative"
    movement.match_status = "unmatched"
    session.commit()

    # Only their row colour changes: no longer green.
    for document in unjustified:
        try:
            push_document(request.app, session, document)
            session.commit()
        except Exception:  # noqa: BLE001 — the database has it; the sheet catches up on the next sync
            logger.warning("Could not push %s to the sheet", document.internal_doc_number, exc_info=True)
            session.rollback()
    session.expire_all()
    return _detail(session, _movement(session, movement_id))


@router.post("/movements/{movement_id}/repropose", response_model=MovementDetail)
async def repropose(
    movement_id: int, request: Request, session: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """Ask again for one movement — after new invoices were added to the register, say."""
    movement = _movement(session, movement_id)
    if movement.match_status == "confirmed":
        raise HTTPException(status_code=409, detail="Aquest moviment ja està justificat.")
    if movement.categoria != PAYMENT:
        raise HTTPException(status_code=400, detail="Aquest moviment no és un pagament.")
    movement.match_status = "unmatched"
    session.commit()
    async with request.app.state.extraction_limiter:
        await run_in_threadpool(_match_one, request.app, movement_id)
    session.expire_all()
    return _detail(session, _movement(session, movement_id))
