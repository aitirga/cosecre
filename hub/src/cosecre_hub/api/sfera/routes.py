"""Export plans to Esfer@: prepare → approve → claim → report → reconcile.

The Hub never talks to the portal. It validates and keeps the plan; a runner
with the person's own session (the desktop app) claims one item, sends the
payload the Hub built, reads the result back and reports it here.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...deps import get_current_user, get_db
from ...models import BankMovement, Document, User, utcnow
from . import preflight
from .models import ACTIVE_STATES, SferaExportAttempt, SferaExportItem, SferaExportPlan, SferaRemoteMapping
from .schemas import (
    Approval,
    AttemptResult,
    ClaimOut,
    ExportContext,
    InvoiceIn,
    PlanCreate,
    PlanOut,
    PlanSummary,
    PreflightOut,
    Readback,
    Reconciliation,
)

router = APIRouter()
ENTITY = "supplier_invoice"


def _today() -> date:
    return date.today()


def _aggregate(items: list[SferaExportItem]) -> str:
    states = {item.state for item in items}
    if "executing" in states:
        return "executing"
    for state in ("conflict", "uncertain"):
        if state in states:
            return state
    if states <= {"succeeded", "reconciled"}:
        return "succeeded"
    if states == {"cancelled"}:
        return "cancelled"
    if states <= {"succeeded", "reconciled", "cancelled"}:
        return "finished"
    for state in ("blocked", "failed", "approved"):
        if state in states:
            return state
    return "ready"


def _plan(session: Session, plan_id: str) -> SferaExportPlan:
    plan = session.get(SferaExportPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "Pla d'exportació no trobat.")
    return plan


def _item(plan: SferaExportPlan, item_id: int) -> SferaExportItem:
    item = next((i for i in plan.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(404, "Element no trobat en aquest pla.")
    return item


def _out(plan: SferaExportPlan) -> PlanOut:
    return PlanOut.model_validate(
        {
            "id": plan.id, "state": plan.state, "plan_hash": plan.plan_hash, "context": plan.context,
            "created_at": plan.created_at, "approved_at": plan.approved_at,
            "items": [
                {**{c: getattr(i, c) for c in ("id", "source_ref", "document_id", "movement_id", "duplicate_key", "state", "problems", "invoice", "payload", "remote_id", "remote_code")}, "attempts": i.attempts}
                for i in plan.items
            ],
        }
    )


def _active_conflicts(session: Session, context: ExportContext, key: str, source_ref: str, exclude_plan: str | None = None) -> list[preflight.Problem]:
    problems = []
    mapped = session.scalar(
        select(SferaRemoteMapping).where(
            SferaRemoteMapping.environment == context.environment,
            SferaRemoteMapping.centre_code == context.centre_code,
            SferaRemoteMapping.entity == ENTITY,
            SferaRemoteMapping.duplicate_key == key,
        )
    )
    if mapped is not None:
        problems.append(preflight.Problem("document_number", "already_exported", f"Ja exportada a Esfer@ ({mapped.remote_code or mapped.remote_id}) des de {mapped.source_ref}."))
    others = session.scalars(
        select(SferaExportItem).join(SferaExportPlan).where(
            SferaExportPlan.environment == context.environment,
            SferaExportPlan.centre_code == context.centre_code,
            SferaExportItem.state.in_(ACTIVE_STATES),
            (SferaExportItem.duplicate_key == key) | (SferaExportItem.source_ref == source_ref),
            SferaExportPlan.id != (exclude_plan or ""),
        )
    ).all()
    if others:
        problems.append(preflight.Problem("source_ref", "in_other_plan", f"Ja és en un altre pla actiu ({others[0].plan_id[:8]})."))
    return problems


def _check_links(session: Session, invoice: InvoiceIn) -> list[preflight.Problem]:
    problems = []
    if invoice.document_id is not None and session.get(Document, invoice.document_id) is None:
        problems.append(preflight.Problem("document_id", "not_found", "El document de registre no existeix."))
    if invoice.movement_id is not None and session.get(BankMovement, invoice.movement_id) is None:
        problems.append(preflight.Problem("movement_id", "not_found", "El moviment no existeix."))
    return problems


@router.get("/capabilities")
def capabilities() -> list[dict]:
    """What can be written where, and when it was last proven against the portal."""
    return preflight.CAPABILITIES


def _evaluate(session: Session, context: ExportContext, invoices: list[InvoiceIn], exclude_plan: str | None = None) -> list[tuple[InvoiceIn, str, list[preflight.Problem]]]:
    """Every check, local and against the journal, for a batch; no remote effect."""
    today = _today()
    seen_keys: set[str] = set()
    seen_refs: set[str] = set()
    result = []
    for invoice in invoices:
        key = preflight.duplicate_key(invoice)
        problems = preflight.check_invoice(context, invoice, today=today)
        problems += _check_links(session, invoice)
        problems += _active_conflicts(session, context, key, invoice.source_ref, exclude_plan)
        if key in seen_keys or invoice.source_ref in seen_refs:
            problems.append(preflight.Problem("document_number", "duplicate_in_plan", "El pla repeteix el mateix proveïdor i número, o la mateixa referència."))
        seen_keys.add(key)
        seen_refs.add(invoice.source_ref)
        result.append((invoice, key, problems))
    return result


@router.post("/preflight", response_model=list[PreflightOut])
def dry_run(body: PlanCreate, session: Session = Depends(get_db)) -> list[PreflightOut]:
    """The same checks as creating a plan, without keeping anything."""
    return [
        PreflightOut(
            source_ref=invoice.source_ref, duplicate_key=key,
            problems=preflight.problems_json(problems),
            state="blocked" if any(p.blocking for p in problems) else "ready",
            payload=preflight.esfera_payload(body.context, invoice),
        )
        for invoice, key, problems in _evaluate(session, body.context, body.invoices)
    ]


@router.post("/export-plans", response_model=PlanOut, status_code=201)
def create_plan(body: PlanCreate, session: Session = Depends(get_db), user: User = Depends(get_current_user)) -> PlanOut:
    """Validate a batch without any remote effect and keep it as a plan."""
    plan = SferaExportPlan(
        id=str(uuid.uuid4()), environment=body.context.environment, centre_code=body.context.centre_code,
        context=body.context.model_dump(mode="json"), plan_hash=preflight.plan_hash(body.context, body.invoices),
        created_by_id=user.id,
    )
    for invoice, key, problems in _evaluate(session, body.context, body.invoices):
        plan.items.append(
            SferaExportItem(
                entity=ENTITY, source_ref=invoice.source_ref, document_id=invoice.document_id, movement_id=invoice.movement_id,
                duplicate_key=key, problems=preflight.problems_json(problems),
                state="blocked" if any(p.blocking for p in problems) else "ready",
                invoice=invoice.model_dump(mode="json"), payload=preflight.esfera_payload(body.context, invoice),
            )
        )
    plan.state = _aggregate(plan.items)
    session.add(plan)
    session.commit()
    return _out(plan)


def _untouched(plan: SferaExportPlan) -> bool:
    """Nothing in it was ever handed to a runner, so deleting it loses no evidence."""
    return all(not item.attempts and item.remote_id is None for item in plan.items)


@router.delete("/export-plans/{plan_id}", status_code=204)
def delete_plan(plan_id: str, session: Session = Depends(get_db)) -> None:
    """Delete a plan that never ran. One that did keeps its journal: cancel it instead."""
    plan = _plan(session, plan_id)
    if not _untouched(plan):
        raise HTTPException(409, "Aquest pla té intents d'escriptura registrats. Cancel·la'l en lloc d'eliminar-lo.")
    session.delete(plan)
    session.commit()


@router.delete("/export-plans/{plan_id}/items/{item_id}", response_model=PlanOut)
def remove_item(plan_id: str, item_id: int, session: Session = Depends(get_db)) -> PlanOut:
    """Take an item out of a plan still under review; the plan gets a new hash to approve."""
    plan = _plan(session, plan_id)
    item = _item(plan, item_id)
    if plan.approved_at is not None:
        raise HTTPException(409, "El pla ja està aprovat. Cancel·la'l i prepara'n un de nou.")
    if len(plan.items) == 1:
        raise HTTPException(409, "És l'únic element: elimina el pla sencer.")
    plan.items.remove(item)
    session.flush()
    context = ExportContext(**plan.context)
    invoices = [InvoiceIn(**i.invoice) for i in plan.items]
    plan.plan_hash = preflight.plan_hash(context, invoices)
    # Re-run the checks: removing a duplicate may unblock its twin.
    for remaining, (_, _, problems) in zip(plan.items, _evaluate(session, context, invoices, exclude_plan=plan.id)):
        remaining.problems = preflight.problems_json(problems)
        remaining.state = "blocked" if any(p.blocking for p in problems) else "ready"
    plan.state = _aggregate(plan.items)
    session.commit()
    return _out(plan)


@router.get("/export-plans", response_model=list[PlanSummary])
def list_plans(session: Session = Depends(get_db)) -> list[PlanSummary]:
    plans = session.scalars(select(SferaExportPlan).order_by(SferaExportPlan.created_at.desc()).limit(100)).all()
    return [
        PlanSummary(id=p.id, state=p.state, environment=p.environment, centre_code=p.centre_code, items=len(p.items), created_at=p.created_at)
        for p in plans
    ]


@router.get("/export-plans/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: str, session: Session = Depends(get_db)) -> PlanOut:
    return _out(_plan(session, plan_id))


@router.post("/export-plans/{plan_id}/approve", response_model=PlanOut)
def approve_plan(plan_id: str, body: Approval, session: Session = Depends(get_db), user: User = Depends(get_current_user)) -> PlanOut:
    """Authorise exactly the plan that was reviewed: the hash binds the approval to its content."""
    plan = _plan(session, plan_id)
    if body.plan_hash != plan.plan_hash:
        raise HTTPException(409, "El pla ha canviat des que es va revisar. Torna'l a revisar.")
    if plan.state != "ready":
        raise HTTPException(409, f"Només es pot aprovar un pla a punt (estat actual: {plan.state}).")
    for item in plan.items:
        item.state = "approved"
    plan.approved_by_id, plan.approved_at = user.id, utcnow()
    plan.state = _aggregate(plan.items)
    session.commit()
    return _out(plan)


@router.post("/export-plans/{plan_id}/items/{item_id}/claim", response_model=ClaimOut)
def claim_item(plan_id: str, item_id: int, session: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ClaimOut:
    """Hand one approved item to a runner, recording the attempt before any call is made.

    Writes in one environment and centre are serialised: while an item is
    executing or uncertain there, nothing else is claimed.
    """
    plan = _plan(session, plan_id)
    item = _item(plan, item_id)
    if plan.approved_at is None:
        raise HTTPException(409, "El pla no està aprovat.")
    if item.state not in ("approved", "failed"):
        raise HTTPException(409, f"Aquest element no es pot executar (estat: {item.state}).")
    busy = session.scalar(
        select(SferaExportItem).join(SferaExportPlan).where(
            SferaExportPlan.environment == plan.environment,
            SferaExportPlan.centre_code == plan.centre_code,
            SferaExportItem.state.in_(("executing", "uncertain")),
        )
    )
    if busy is not None:
        raise HTTPException(409, f"Hi ha una escriptura en curs o incerta en aquest centre ({busy.source_ref}). Concilia-la abans de continuar.")
    attempt = SferaExportAttempt(runner_user_id=user.id)
    item.attempts.append(attempt)
    item.state = "executing"
    plan.state = _aggregate(plan.items)
    session.commit()
    return ClaimOut(plan_id=plan.id, item_id=item.id, attempt_id=attempt.id, payload=item.payload, duplicate_key=item.duplicate_key, context=plan.context)


def _readback_problem(item: SferaExportItem, plan: SferaExportPlan, readback: Readback | None) -> str | None:
    if readback is None:
        return "Falta la relectura de la factura desada."
    invoice = item.invoice
    differences = []
    if readback.supplier_remote_id != invoice["supplier_remote_id"]:
        differences.append("proveïdor")
    if readback.total != Decimal(invoice["total"]):
        differences.append("total")
    if readback.remote_budget_id != plan.context["remote_budget_id"]:
        differences.append("pressupost")
    if readback.document_number.strip().upper() != invoice["document_number"].strip().upper():
        differences.append("número")
    return f"La relectura no coincideix: {', '.join(differences)}." if differences else None


def _confirm(session: Session, plan: SferaExportPlan, item: SferaExportItem, remote_id: int | None, remote_code: str | None, readback: Readback | None, state: str) -> str | None:
    """Record a confirmed remote record, or say why it cannot be confirmed."""
    if remote_id is None:
        return "Falta l'ID remot."
    problem = _readback_problem(item, plan, readback)
    if problem:
        return problem
    existing = session.scalar(
        select(SferaRemoteMapping).where(
            SferaRemoteMapping.environment == plan.environment, SferaRemoteMapping.centre_code == plan.centre_code,
            SferaRemoteMapping.entity == item.entity, SferaRemoteMapping.duplicate_key == item.duplicate_key,
        )
    )
    if existing is not None and existing.remote_id != remote_id:
        return f"Ja hi ha una altra factura remota amb aquesta clau ({existing.remote_id})."
    if existing is None:
        session.add(SferaRemoteMapping(
            environment=plan.environment, centre_code=plan.centre_code, entity=item.entity, duplicate_key=item.duplicate_key,
            source_ref=item.source_ref, remote_id=remote_id, remote_code=remote_code, item_id=item.id,
        ))
    item.remote_id, item.remote_code, item.state = remote_id, remote_code, state
    return None


@router.post("/export-plans/{plan_id}/items/{item_id}/result", response_model=PlanOut)
def report_result(plan_id: str, item_id: int, body: AttemptResult, session: Session = Depends(get_db)) -> PlanOut:
    """The runner's report. Only the attempt it was given may report (fencing)."""
    plan = _plan(session, plan_id)
    item = _item(plan, item_id)
    attempt = item.attempts[-1] if item.attempts else None
    if attempt is None or attempt.id != body.attempt_id or attempt.outcome != "pending" or item.state != "executing":
        raise HTTPException(409, "Aquest intent ja no és el vigent per a l'element.")
    attempt.http_status, attempt.remote_id, attempt.error, attempt.finished_at = body.http_status, body.remote_id, body.error, utcnow()
    if body.outcome == "succeeded":
        problem = _confirm(session, plan, item, body.remote_id, body.remote_code, body.readback, "succeeded")
        if problem:
            item.state, attempt.outcome = "conflict", "conflict"
            attempt.error = problem
        else:
            attempt.outcome = "succeeded"
    elif body.outcome == "failed" and body.no_effect_confirmed:
        item.state = attempt.outcome = "failed"
    else:
        # A failure without a read proving nothing was written is not a failure yet.
        item.state = attempt.outcome = "uncertain"
    plan.state = _aggregate(plan.items)
    session.commit()
    return _out(plan)


@router.post("/export-plans/{plan_id}/items/{item_id}/recover", response_model=PlanOut)
def recover_item(plan_id: str, item_id: int, session: Session = Depends(get_db)) -> PlanOut:
    """A runner that vanished mid-write leaves the item uncertain, never retried blind."""
    plan = _plan(session, plan_id)
    item = _item(plan, item_id)
    if item.state != "executing":
        raise HTTPException(409, "Només es recupera un element en execució.")
    attempt = item.attempts[-1]
    attempt.outcome, attempt.finished_at = "abandoned", utcnow()
    attempt.error = "El runner no ha informat del resultat."
    item.state = "uncertain"
    plan.state = _aggregate(plan.items)
    session.commit()
    return _out(plan)


@router.post("/export-plans/{plan_id}/items/{item_id}/reconcile", response_model=PlanOut)
def reconcile_item(plan_id: str, item_id: int, body: Reconciliation, session: Session = Depends(get_db)) -> PlanOut:
    """Settle an uncertain or conflicting item with what a read of the portal showed."""
    plan = _plan(session, plan_id)
    item = _item(plan, item_id)
    if item.state not in ("uncertain", "conflict"):
        raise HTTPException(409, "Només es concilia un element incert o en conflicte.")
    if body.found:
        problem = _confirm(session, plan, item, body.remote_id, body.remote_code, body.readback, "reconciled")
        if problem:
            item.state = "conflict"
            raise_after = problem
        else:
            raise_after = None
    else:
        item.state, raise_after = "failed", None
    plan.state = _aggregate(plan.items)
    session.commit()
    if raise_after:
        raise HTTPException(409, raise_after)
    return _out(plan)


@router.post("/export-plans/{plan_id}/cancel", response_model=PlanOut)
def cancel_plan(plan_id: str, session: Session = Depends(get_db)) -> PlanOut:
    """Cancel what has not run. Records already created stay: there is no rollback."""
    plan = _plan(session, plan_id)
    for item in plan.items:
        if item.state in ("blocked", "ready", "approved", "failed"):
            item.state = "cancelled"
    plan.state = _aggregate(plan.items)
    session.commit()
    return _out(plan)
