"""Budget lines: import from esfer@, context for Jev, and charging movements to them.

What esfer@ books against a line is the money that moved — a line of a bank
statement, the caixeta or the prepaid card — so that is what is charged here.
The invoices a movement paid (confirmed in Justificar extractes) are shown and
read by Jev, because they say what the money was for.

Reading is the office's (the router is mounted behind ``require_staff``);
every write is the secretari/a's alone, because which line a movement is
charged to is an accounting decision.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ...deps import get_db, get_workspace_setting, require_admin
from ...models import AppSetting, BankMovement, Document, PaymentMatch, User, utcnow
from ...services.classification import JevError
from ...services.people import fold
from ...services.storage import MAX_UPLOAD_BYTES
from ...services.text_format import compact_code
from ..documents.register import drive_name, extension_for
from . import esfera, suggest
from .models import MovementPartida, MovementPartidaSuggestion, Partida, Pressupost
from .schemas import (
    AssignmentRead,
    AssignmentsUpdate,
    ContextUpdate,
    ImportSummary,
    InvoiceBrief,
    OrderUpdate,
    PartidaRead,
    PressupostRead,
    QueueItem,
    RankedRead,
    SuggestionRead,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: Where the general context lives: one value, every year.
CONTEXT_APP = "cosecre-docs"
CONTEXT_KEY = "partides.context"
#: The secretari/a's order of the lines inside each concept.
ORDER_KEY = "partides.order"

#: Movements that never reach the budget: money moving between the school's
#: own accounts, and the opening balance of a statement.
NOT_CHARGED = {"traspas_intern", "saldo_inicial"}


# ── Helpers ─────────────────────────────────────────────────────────────────


def _exercicis(session: Session) -> list[int]:
    return [row[0] for row in session.query(Pressupost.exercici).order_by(Pressupost.exercici.desc())]


def _setting(session: Session, key: str) -> AppSetting | None:
    return (
        session.query(AppSetting)
        .filter(AppSetting.app_slug == CONTEXT_APP, AppSetting.key == key)
        .first()
    )


def _general_context(session: Session) -> str:
    row = _setting(session, CONTEXT_KEY)
    value = row.value if row is not None else ""
    return value if isinstance(value, str) else ""


def _user_order(session: Session) -> dict[str, list[str]]:
    row = _setting(session, ORDER_KEY)
    value = row.value if row is not None else None
    return value if isinstance(value, dict) else {}


def _partida_read(partida: Partida, has_children: set[str], usage: dict[int, tuple[int, float]]) -> PartidaRead:
    fons, fons_label = esfera.fund_family(partida.codi_finalista)
    count, total = usage.get(partida.id, (0, 0.0))
    return PartidaRead(
        id=partida.id,
        exercici=partida.exercici,
        tipus=partida.tipus,  # type: ignore[arg-type]
        codi=partida.codi,
        codi_pare=partida.codi_pare,
        codi_finalista=partida.codi_finalista,
        fons=fons,
        fons_label=fons_label,
        nom=partida.nom,
        import_pressupost=partida.import_pressupost,
        ordre=partida.ordre,
        te_fills=partida.codi in has_children,
        retirada=partida.retirada,
        context=partida.context or "",
        moviments=count,
        imputat=round(total, 2),
    )


def _usage(session: Session, exercici: int) -> dict[int, tuple[int, float]]:
    """Confirmed movements per line, and what they add up to."""
    rows = (
        session.query(MovementPartida, BankMovement.import_value)
        .join(Partida, Partida.id == MovementPartida.partida_id)
        .join(BankMovement, BankMovement.id == MovementPartida.movement_id)
        .filter(Partida.exercici == exercici, MovementPartida.confirmada.is_(True))
        .all()
    )
    shares: dict[int, list[MovementPartida]] = {}
    for assignment, _ in rows:
        shares.setdefault(assignment.movement_id, []).append(assignment)
    usage: dict[int, tuple[int, float]] = {}
    for assignment, total in rows:
        amount = assignment.import_assignat
        if amount is None:
            # Unsplit: the whole movement, shared evenly if it sits on several lines.
            amount = abs(total or 0.0) / len(shares[assignment.movement_id])
        count, running = usage.get(assignment.partida_id, (0, 0.0))
        usage[assignment.partida_id] = (count + 1, running + amount)
    return usage


def _read_budget(request: Request, session: Session, exercici: int | None) -> PressupostRead:
    years = _exercicis(session)
    jev = getattr(request.app.state.classifier, "jev", None) is not None
    context = _general_context(session)
    order = _user_order(session)
    if exercici is None:
        exercici = years[0] if years else None
    budget = session.get(Pressupost, exercici) if exercici is not None else None
    if budget is None:
        return PressupostRead(
            exercici=None, exercicis=years, context_general=context, ordre_usuari=order, jev=jev
        )
    partides = (
        session.query(Partida).filter(Partida.exercici == exercici).order_by(Partida.ordre).all()
    )
    has_children = {p.codi_pare for p in partides if p.codi_pare}
    usage = _usage(session, exercici)
    return PressupostRead(
        exercici=budget.exercici,
        exercicis=years,
        centre=budget.centre,
        nif=budget.nif,
        codi_centre=budget.codi_centre,
        data_informe=budget.data_informe,
        total_ingressos=budget.total_ingressos,
        total_despeses=budget.total_despeses,
        file_name=budget.file_name,
        imported_at=budget.imported_at,
        context_general=context,
        ordre_usuari=order,
        jev=jev,
        partides=[_partida_read(p, has_children, usage) for p in partides],
    )


def _movement(session: Session, movement_id: int) -> BankMovement:
    movement = session.get(BankMovement, movement_id)
    if movement is None or movement.categoria in NOT_CHARGED:
        raise HTTPException(status_code=404, detail="No s'ha trobat el moviment.")
    return movement


def _exercici_for(movement: BankMovement, years: list[int]) -> int | None:
    if not years:
        return None
    when = suggest.movement_date(movement)
    return when.year if when is not None and when.year in years else years[0]


def _paid_invoices(session: Session, movement_ids: list[int] | None = None) -> dict[int, list[Document]]:
    """The invoices each movement paid, as a person confirmed them."""
    query = (
        session.query(PaymentMatch.movement_id, Document)
        .join(Document, Document.id == PaymentMatch.document_id)
        .filter(PaymentMatch.status == "confirmed")
    )
    if movement_ids is not None:
        query = query.filter(PaymentMatch.movement_id.in_(movement_ids or [-1]))
    paid: dict[int, list[Document]] = {}
    for movement_id, document in query.order_by(PaymentMatch.id):
        paid.setdefault(movement_id, []).append(document)
    return paid


def _invoice_brief(document: Document) -> InvoiceBrief:
    upload = document.upload
    stored = Path(upload.stored_path) if upload is not None else None
    has_file = stored is not None and stored.exists()
    return InvoiceBrief(
        reference=document.internal_doc_number,
        tipus_document=document.tipus_document or "",
        num_factura=document.num_factura or "",
        proveidor=document.proveidor or "",
        cif_proveidor=document.cif_proveidor or "",
        data_factura=document.data_factura,
        import_value=document.import_value,
        descripcio=document.descripcio or "",
        descripcio_compra=document.descripcio_compra or "",
        responsable_nom=document.responsable_nom or "",
        file_url=f"/documents/records/{document.internal_doc_number}/file" if has_file else None,
        file_name=drive_name(document, extension_for(document)) if has_file else None,
    )


def _queue_item(
    movement: BankMovement,
    years: list[int],
    invoices: list[Document],
    assignments: list[MovementPartida],
    suggestion: MovementPartidaSuggestion | None,
) -> QueueItem:
    if any(a.confirmada for a in assignments):
        estat = "assignada"
    elif assignments:
        estat = "proposta"
    else:
        estat = "pendent"
    return QueueItem(
        id=movement.id,
        import_id=movement.import_id,
        codi=movement.codi or "",
        compte=movement.compte or "",
        tipus=movement.tipus or "",
        categoria=movement.categoria or "",
        data=suggest.movement_date(movement),
        concepte=movement.concepte or "",
        mes_dades=movement.mes_dades or "",
        import_value=movement.import_value,
        sentit=suggest.sentit(movement),  # type: ignore[arg-type]
        match_status=movement.match_status or "",
        factures=[_invoice_brief(d) for d in invoices],
        exercici=_exercici_for(movement, years),
        curs=suggest.school_year(suggest.movement_date(movement)),
        estat=estat,  # type: ignore[arg-type]
        assignments=[
            AssignmentRead(
                partida_id=a.partida_id,
                import_assignat=a.import_assignat,
                origen=a.origen,  # type: ignore[arg-type]
                confianca=a.confianca,
                confirmada=a.confirmada,
            )
            for a in sorted(assignments, key=lambda a: a.id)
        ],
        suggestion=(
            SuggestionRead(
                ranking=[RankedRead(**r) for r in suggestion.ranking],
                confidence=suggestion.confidence,
                cap=suggestion.cap,
                multiple=suggestion.multiple,
                model=suggestion.model,
                created_at=suggestion.created_at,
            )
            if suggestion is not None
            else None
        ),
    )


def _item_for(session: Session, movement: BankMovement) -> QueueItem:
    assignments = session.query(MovementPartida).filter(MovementPartida.movement_id == movement.id).all()
    return _queue_item(
        movement,
        _exercicis(session),
        _paid_invoices(session, [movement.id]).get(movement.id, []),
        assignments,
        session.get(MovementPartidaSuggestion, movement.id),
    )


def _history(session: Session, movement: BankMovement, invoices: list[Document]) -> list[tuple[str, int]]:
    """Lines other movements were confirmed to, by the same supplier or concept, most used first.

    The supplier comes from the invoices a movement paid; a movement with none
    (a bank fee, a direct debit) is known by its concept instead.
    """
    cifs = {compact_code(d.cif_proveidor) for d in invoices} - {""}
    names = {fold(d.proveidor or "") for d in invoices} - {""}
    concept = fold(movement.concepte or "")
    if not cifs and not names and not concept:
        return []
    rows = (
        session.query(MovementPartida.movement_id, BankMovement.concepte, Partida.nom)
        .join(BankMovement, BankMovement.id == MovementPartida.movement_id)
        .join(Partida, Partida.id == MovementPartida.partida_id)
        .filter(MovementPartida.confirmada.is_(True), MovementPartida.movement_id != movement.id)
        .all()
    )
    if not rows:
        return []
    paid = _paid_invoices(session, list({row[0] for row in rows}))
    counts: Counter[str] = Counter()
    for other_id, other_concept, line in rows:
        others = paid.get(other_id, [])
        same_supplier = any(
            (cifs and compact_code(d.cif_proveidor) in cifs) or (names and fold(d.proveidor or "") in names)
            for d in others
        )
        same_concept = not invoices and not others and concept and fold(other_concept or "") == concept
        if same_supplier or same_concept:
            counts[line] += 1
    return counts.most_common(5)


# ── The budget ──────────────────────────────────────────────────────────────


@router.get("", response_model=PressupostRead)
def read_budget(
    request: Request,
    exercici: int | None = Query(default=None),
    session: Session = Depends(get_db),
):
    return _read_budget(request, session, exercici)


@router.post("/import", response_model=ImportSummary)
async def import_budget(
    file: UploadFile = File(...),
    dry_run: bool = Form(default=False),
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Read an esfer@ export; with ``dry_run``, only say what importing it would do."""
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El fitxer és massa gran.")
    try:
        parsed = esfera.parse(content, file.filename or "")
    except esfera.BudgetFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await run_in_threadpool(_apply_import, session, parsed, file.filename or "", admin, dry_run)


def _apply_import(
    session: Session, parsed: esfera.ParsedBudget, file_name: str, admin: User, dry_run: bool
) -> ImportSummary:
    school_cif = compact_code(get_workspace_setting(session).school_cif or "")
    budget = session.get(Pressupost, parsed.exercici)
    replaces = budget is not None
    existing = {p.codi: p for p in session.query(Partida).filter(Partida.exercici == parsed.exercici)}
    # A line that existed last year keeps what was written about it.
    earlier: dict[str, str] = {}
    for partida in (
        session.query(Partida)
        .filter(Partida.exercici < parsed.exercici, Partida.context != "")
        .order_by(Partida.exercici)
    ):
        earlier[partida.codi] = partida.context

    created = updated = unchanged = inherited = 0
    for line in parsed.partides:
        values = {
            "tipus": line.tipus,
            "codi_pare": line.codi_pare,
            "codi_finalista": line.codi_finalista,
            "nom": line.nom,
            "import_pressupost": line.import_pressupost,
            "ordre": line.ordre,
            "retirada": False,
        }
        partida = existing.pop(line.codi, None)
        if partida is None:
            created += 1
            context = earlier.get(line.codi, "")
            inherited += bool(context)
            if not dry_run:
                session.add(Partida(exercici=parsed.exercici, codi=line.codi, context=context, **values))
            continue
        if all(getattr(partida, k) == v for k, v in values.items()):
            unchanged += 1
            continue
        updated += 1
        if not dry_run:
            for key, value in values.items():
                setattr(partida, key, value)

    # What the new file no longer has: kept if movements point at it.
    used = {
        row[0]
        for row in session.query(MovementPartida.partida_id).filter(
            MovementPartida.partida_id.in_([p.id for p in existing.values()] or [-1])
        )
    }
    retired = removed = 0
    for partida in existing.values():
        if partida.id in used:
            retired += not partida.retirada
            if not dry_run:
                partida.retirada = True
        else:
            removed += 1
            if not dry_run:
                session.delete(partida)

    if not dry_run:
        if budget is None:
            budget = Pressupost(exercici=parsed.exercici)
            session.add(budget)
        budget.centre = parsed.centre
        budget.nif = parsed.nif
        budget.codi_centre = parsed.codi_centre
        budget.data_informe = parsed.data_informe
        budget.total_ingressos = parsed.total_ingressos
        budget.total_despeses = parsed.total_despeses
        budget.file_name = file_name[:255]
        budget.imported_by_id = admin.id
        budget.imported_at = utcnow()
        session.commit()

    return ImportSummary(
        dry_run=dry_run,
        exercici=parsed.exercici,
        centre=parsed.centre,
        nif=parsed.nif,
        codi_centre=parsed.codi_centre,
        nif_matches=(compact_code(parsed.nif) == school_cif) if school_cif else None,
        replaces=replaces,
        created=created,
        updated=updated,
        unchanged=unchanged,
        retired=retired,
        removed=removed,
        despeses=sum(1 for p in parsed.partides if p.tipus == "despesa"),
        ingressos=sum(1 for p in parsed.partides if p.tipus == "ingres"),
        total_despeses=parsed.total_despeses,
        context_inherited=inherited,
    )


@router.put("/context", response_model=PressupostRead)
def update_general_context(
    payload: ContextUpdate,
    request: Request,
    exercici: int | None = Query(default=None),
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = _setting(session, CONTEXT_KEY)
    if row is None:
        row = AppSetting(app_slug=CONTEXT_APP, key=CONTEXT_KEY)
        session.add(row)
    row.value = payload.context.strip()
    row.updated_by_id = admin.id
    session.commit()
    return _read_budget(request, session, exercici)


@router.put("/order", response_model=dict[str, list[str]])
def update_order(
    payload: OrderUpdate,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Keep the order the secretari/a dragged one concept's lines into."""
    row = _setting(session, ORDER_KEY)
    if row is None:
        row = AppSetting(app_slug=CONTEXT_APP, key=ORDER_KEY)
        session.add(row)
    order = dict(row.value) if isinstance(row.value, dict) else {}
    codis = list(dict.fromkeys(c.strip() for c in payload.codis if c.strip()))
    if codis:
        order[payload.block] = codis
    else:
        order.pop(payload.block, None)
    # A new dict, so the JSON column sees the change.
    row.value = order
    row.updated_by_id = admin.id
    session.commit()
    return order


@router.put("/lines/{partida_id}/context", response_model=PartidaRead)
def update_line_context(
    partida_id: int,
    payload: ContextUpdate,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    partida = session.get(Partida, partida_id)
    if partida is None:
        raise HTTPException(status_code=404, detail="No s'ha trobat la partida.")
    partida.context = payload.context.strip()
    session.commit()
    has_children = {
        row[0]
        for row in session.query(Partida.codi_pare).filter(
            Partida.exercici == partida.exercici, Partida.codi_pare == partida.codi
        )
    }
    return _partida_read(partida, has_children, _usage(session, partida.exercici))


# ── Charging movements ──────────────────────────────────────────────────────


@router.get("/queue", response_model=list[QueueItem])
def queue(session: Session = Depends(get_db)):
    """Every statement movement that is charged to a line, with what it has, newest first."""
    years = _exercicis(session)
    movements = (
        session.query(BankMovement)
        .filter(BankMovement.categoria.notin_(NOT_CHARGED), BankMovement.import_value != 0)
        .all()
    )
    assignments: dict[int, list[MovementPartida]] = {}
    for assignment in session.query(MovementPartida).all():
        assignments.setdefault(assignment.movement_id, []).append(assignment)
    suggestions = {s.movement_id: s for s in session.query(MovementPartidaSuggestion).all()}
    paid = _paid_invoices(session)
    movements.sort(key=lambda m: (suggest.movement_date(m) or datetime.min.date(), m.id), reverse=True)
    return [
        _queue_item(m, years, paid.get(m.id, []), assignments.get(m.id, []), suggestions.get(m.id))
        for m in movements
    ]


@router.put("/movements/{movement_id}", response_model=QueueItem)
def assign(
    movement_id: int,
    payload: AssignmentsUpdate,
    session: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Set a movement's lines. What is sent is confirmed; anything else goes."""
    movement = _movement(session, movement_id)
    wanted = {line.partida_id: line for line in payload.partides}
    if wanted:
        found = session.query(Partida).filter(Partida.id.in_(wanted)).all()
        if len(found) != len(wanted):
            raise HTTPException(status_code=422, detail="Alguna partida no existeix.")
        parents = {
            row[0]
            for row in session.query(Partida.codi_pare).filter(
                Partida.exercici.in_({p.exercici for p in found}),
                Partida.codi_pare.in_([p.codi for p in found]),
            )
        }
        headings = [p for p in found if p.codi in parents]
        if headings:
            raise HTTPException(
                status_code=422,
                detail=f"«{headings[0].nom}» té subpartides: tria'n una.",
            )
    _check_split(movement, list(wanted.values()))
    current = {
        a.partida_id: a
        for a in session.query(MovementPartida).filter(MovementPartida.movement_id == movement.id)
    }
    for partida_id, assignment in current.items():
        if partida_id not in wanted:
            session.delete(assignment)
    for partida_id, line in wanted.items():
        assignment = current.get(partida_id)
        if assignment is None:
            assignment = MovementPartida(
                movement_id=movement.id, partida_id=partida_id, origen="persona"
            )
            session.add(assignment)
        assignment.import_assignat = line.import_assignat
        assignment.confirmada = True
        assignment.assigned_by_id = admin.id
    session.commit()
    return _item_for(session, movement)


def _check_split(movement: BankMovement, lines: list) -> None:
    """A split is all or nothing, and adds up to the movement.

    No amounts at all means "shared evenly"; one line alone takes the whole
    movement whatever it says. Parts are positive whichever way the money went.
    """
    amounts = [line.import_assignat for line in lines]
    if len(lines) < 2 or all(amount is None for amount in amounts):
        if len(lines) == 1:
            lines[0].import_assignat = None
        return
    if any(amount is None for amount in amounts):
        raise HTTPException(
            status_code=422, detail="Si es reparteix, cada partida ha de dir el seu import."
        )
    if any(amount <= 0 for amount in amounts):
        raise HTTPException(status_code=422, detail="Cada part ha de ser més gran que zero.")
    total = abs(movement.import_value)
    if abs(sum(amounts) - total) > 0.01:
        raise HTTPException(
            status_code=422,
            detail=f"El repartiment suma {sum(amounts):.2f} € i el moviment és de {total:.2f} €.",
        )


@router.post("/movements/{movement_id}/suggest", response_model=QueueItem)
async def suggest_lines(
    movement_id: int,
    request: Request,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Ask Jev, store its ranking, and pre-assign when nothing is confirmed yet."""
    jev = getattr(request.app.state.classifier, "jev", None)
    if jev is None:
        raise HTTPException(status_code=503, detail="Jev no està configurat en aquest hub.")
    movement = _movement(session, movement_id)
    years = _exercicis(session)
    exercici = _exercici_for(movement, years)
    if exercici is None:
        raise HTTPException(
            status_code=409, detail="Encara no hi ha cap pressupost importat a Configuració."
        )
    partides = session.query(Partida).filter(Partida.exercici == exercici).order_by(Partida.ordre).all()
    context = _general_context(session)
    invoices = _paid_invoices(session, [movement.id]).get(movement.id, [])
    history = _history(session, movement, invoices)
    try:
        result = await run_in_threadpool(
            suggest.ask, jev, movement, invoices, partides, context, history
        )
    except JevError as exc:
        logger.warning("Jev could not suggest a budget line", exc_info=True)
        raise HTTPException(status_code=502, detail="Jev no ha respost. Torna-ho a provar.") from exc

    stored = session.get(MovementPartidaSuggestion, movement.id)
    if stored is None:
        stored = MovementPartidaSuggestion(movement_id=movement.id)
        session.add(stored)
    stored.ranking = [{"partida_id": r.partida_id, "probability": r.probability} for r in result.ranking]
    stored.confidence = result.confidence
    stored.cap = result.cap
    stored.multiple = result.multiple
    stored.model = result.model
    stored.created_at = utcnow()

    current = session.query(MovementPartida).filter(MovementPartida.movement_id == movement.id).all()
    if not any(a.confirmada for a in current):
        for assignment in current:
            session.delete(assignment)
        session.flush()
        for ranked in result.preassign():
            session.add(
                MovementPartida(
                    movement_id=movement.id,
                    partida_id=ranked.partida_id,
                    origen="jev",
                    confianca=ranked.probability,
                    confirmada=False,
                )
            )
    session.commit()
    return _item_for(session, movement)
