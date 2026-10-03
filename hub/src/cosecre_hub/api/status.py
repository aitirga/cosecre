"""Estat: where the accounting stands, in one read.

Nothing here is stored. Every number is counted from the register and the
statements on each request — the data is a school's year of invoices, small
enough that counting is cheaper than keeping a second copy honest.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from ..deps import get_current_user, get_db, get_workspace_setting
from ..models import (
    BankMovement,
    Document,
    DuplicateRemoval,
    MatchRun,
    PaymentMatch,
    StatementImport,
    User,
)
from ..schemas.documents import COMPTES
from ..schemas.status import (
    AccountStatus,
    DocumentIssue,
    DocumentIssues,
    DocumentTotals,
    MonthCell,
    MonthGap,
    MonthRow,
    MovementIssue,
    MovementIssues,
    PaymentTotals,
    RegisterHealth,
    StatusOverview,
    Tally,
)
from ..services.statements import PAYMENT
from ..services.text_format import iban_is_valid

router = APIRouter()

#: Quotes and delivery notes are never paid as such: the invoice that follows is.
NOT_PAYABLE = {"Pressupost", "Albarà"}
IN_FLIGHT = {"pending", "processing", "written_to_sheet"}
#: A "Pendent de pagament" older than this is worth chasing.
OVERDUE_DAYS = 30
#: Months shown in the account × month grid.
GRID_MONTHS = 12
#: Rows sent per issue list; the totals still count every one.
MAX_ITEMS = 200
#: The register fields whose absence makes an entry hard to justify.
REQUIRED_FIELDS = {
    "import_value": "Import",
    "proveidor": "Proveïdor",
    "data_factura": "Data",
    "num_factura": "Núm. factura",
    "pressupost_afectat": "Compte",
}
MISSING = {"no_match", "rejected"}


def _month(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _months_between(first: date, last: date) -> list[str]:
    months = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _months_of(start: date, end: date) -> set[str]:
    return set(_months_between(start, end))


def _add(tally: Tally, amount: float) -> None:
    tally.count += 1
    tally.amount = round(tally.amount + amount, 2)


def _tally_payment(totals: PaymentTotals, movement: BankMovement) -> None:
    amount = abs(movement.import_value or 0.0)
    _add(totals.total, amount)
    status = movement.match_status
    if status == "confirmed":
        _add(totals.confirmed, amount)
    elif status == "proposed":
        _add(totals.proposed, amount)
    elif status in MISSING:
        _add(totals.missing, amount)
    elif status == "unmatched":
        _add(totals.unmatched, amount)


def _gaps(covered: set[str]) -> list[MonthGap]:
    """Runs of uncovered months strictly between the first and last covered one."""
    if not covered:
        return []
    ordered = sorted(covered)
    span = _months_between(date.fromisoformat(f"{ordered[0]}-01"), date.fromisoformat(f"{ordered[-1]}-01"))
    gaps: list[MonthGap] = []
    run: list[str] = []
    for month in span + [None]:  # type: ignore[list-item]
        if month is not None and month not in covered:
            run.append(month)
            continue
        if run:
            gaps.append(MonthGap(from_month=run[0], to_month=run[-1], months=len(run)))
            run = []
    return gaps


def _document_issue(
    document: Document, today: date, *, proposed: set[int], covered: bool, since: date | None
) -> DocumentIssue:
    return DocumentIssue(
        num_doc_intern=document.internal_doc_number,
        num_factura=document.num_factura or "",
        proveidor=document.proveidor or "",
        data_factura=document.data_factura,
        data_pagament=document.data_pagament,
        import_value=document.import_value,
        compte=document.pressupost_afectat or "",
        pagament=document.pagament or "",
        metode_pagament=document.metode_pagament or "",
        has_proposal=document.id in proposed,
        covered=covered,
        days=(today - since).days if since else None,
    )


@router.get("", response_model=StatusOverview)
def overview(session: Session = Depends(get_db), _: User = Depends(get_current_user)) -> StatusOverview:
    today = datetime.now(UTC).date()

    statements = session.query(StatementImport).all()
    movements = (
        session.query(BankMovement)
        .options(selectinload(BankMovement.matches).selectinload(PaymentMatch.document))
        .all()
    )
    documents = session.query(Document).all()
    payments = [m for m in movements if m.categoria == PAYMENT]

    # ── Coverage: which months of which account a statement speaks for ──────
    intervals: dict[str, list[tuple[date, date]]] = defaultdict(list)
    covered_months: dict[str, set[str]] = defaultdict(set)
    for statement in statements:
        if statement.period_from and statement.period_to:
            intervals[statement.compte].append((statement.period_from, statement.period_to))
            covered_months[statement.compte] |= _months_of(statement.period_from, statement.period_to)

    def is_covered(compte: str, day: date | None) -> bool:
        return bool(day) and any(start <= day <= end for start, end in intervals.get(compte, []))

    # ── Payments ─────────────────────────────────────────────────────────────
    totals = PaymentTotals()
    by_account: dict[str, PaymentTotals] = defaultdict(PaymentTotals)
    for movement in payments:
        _tally_payment(totals, movement)
        _tally_payment(by_account[movement.compte], movement)

    accounts: list[AccountStatus] = []
    known = list(COMPTES) + sorted({s.compte for s in statements} - set(COMPTES))
    for compte in known:
        own = [s for s in statements if s.compte == compte]
        period_to = max((s.period_to for s in own if s.period_to), default=None)
        accounts.append(
            AccountStatus(
                compte=compte,
                statements=len(own),
                period_from=min((s.period_from for s in own if s.period_from), default=None),
                period_to=period_to,
                last_upload_at=max((s.updated_at for s in own), default=None),
                days_since=(today - period_to).days if period_to else None,
                payments=by_account.get(compte, PaymentTotals()),
                gaps=_gaps(covered_months.get(compte, set())),
            )
        )

    # ── Account × month grid ────────────────────────────────────────────────
    first_day = min((m.data for m in payments if m.data), default=None)
    grid_months = _months_between(first_day, today)[-GRID_MONTHS:] if first_day else []
    cells: dict[tuple[str, str], MonthCell] = {}
    for movement in payments:
        if not movement.data:
            continue
        key = (_month(movement.data), movement.compte)
        cell = cells.setdefault(key, MonthCell(compte=movement.compte))
        cell.payments += 1
        if movement.match_status == "confirmed":
            cell.confirmed += 1
        elif movement.match_status in MISSING:
            cell.missing += 1
        elif movement.match_status in {"proposed", "unmatched"}:
            cell.pending += 1
            cell.pending_amount = round(cell.pending_amount + abs(movement.import_value or 0.0), 2)
    months = [
        MonthRow(
            month=month,
            cells=[
                (cells.get((month, compte)) or MonthCell(compte=compte)).model_copy(
                    update={"covered": month in covered_months.get(compte, set())}
                )
                for compte in COMPTES
            ],
        )
        for month in reversed(grid_months)
    ]

    # ── Payments with no invoice behind them ───────────────────────────────
    def movement_issue(movement: BankMovement, **extra) -> MovementIssue:
        return MovementIssue(
            movement_id=movement.id,
            import_id=movement.import_id,
            compte=movement.compte,
            data=movement.data,
            concepte=movement.concepte or "",
            mes_dades=movement.mes_dades or "",
            amount=round(abs(movement.import_value or 0.0), 2),
            match_status=movement.match_status,
            **extra,
        )

    newest = lambda m: (m.data or date.min, m.id)  # noqa: E731
    missing = MovementIssues(total=totals.missing.model_copy())
    missing.items = [
        movement_issue(m) for m in sorted((m for m in payments if m.match_status in MISSING), key=newest, reverse=True)
    ][:MAX_ITEMS]

    # ── Confirmed payments whose invoices do not add up to them ─────────────
    mismatches = MovementIssues()
    mismatch_items: list[MovementIssue] = []
    for movement in sorted((m for m in payments if m.match_status == "confirmed"), key=newest, reverse=True):
        linked = [m.document for m in movement.matches if m.status == "confirmed" and m.document is not None]
        if not linked:
            continue
        amount = round(abs(movement.import_value or 0.0), 2)
        known_amounts = [d.import_value for d in linked if d.import_value is not None]
        documents_amount = round(sum(known_amounts), 2)
        difference = round(amount - documents_amount, 2)
        if len(known_amounts) == len(linked) and abs(difference) <= 0.01:
            continue
        _add(mismatches.total, abs(difference))
        mismatch_items.append(
            movement_issue(
                movement,
                documents=[d.internal_doc_number for d in linked],
                documents_amount=documents_amount,
                difference=difference,
            )
        )
    mismatches.items = mismatch_items[:MAX_ITEMS]

    # ── Invoices, from the register's side ─────────────────────────────────
    confirmed_docs = {
        match.document_id for m in payments for match in m.matches if match.status == "confirmed"
    }
    proposed_docs = {
        match.document_id
        for m in movements
        if m.match_status == "proposed"
        for match in m.matches
        if match.status == "proposed"
    }
    settled = [d for d in documents if d.status not in IN_FLIGHT and d.status != "error"]
    payable = [d for d in settled if d.tipus_document not in NOT_PAYABLE]

    paid_not_found = DocumentIssues()
    overdue = DocumentIssues()
    paid_items: list[DocumentIssue] = []
    overdue_items: list[DocumentIssue] = []
    for document in payable:
        if document.id in confirmed_docs:
            continue
        amount = abs(document.import_value or 0.0)
        compte = document.pressupost_afectat or ""
        if document.pagament == "Pagat":
            when = document.data_pagament or document.data_factura
            _add(paid_not_found.total, amount)
            paid_items.append(
                _document_issue(
                    document, today, proposed=proposed_docs, covered=is_covered(compte, when), since=when
                )
            )
        elif document.pagament == "Pendent de pagament" and document.data_factura:
            if (today - document.data_factura).days > OVERDUE_DAYS:
                _add(overdue.total, amount)
                overdue_items.append(
                    _document_issue(
                        document,
                        today,
                        proposed=proposed_docs,
                        covered=is_covered(compte, document.data_factura),
                        since=document.data_factura,
                    )
                )
    # Covered first: the statement is there, so the payment should be too.
    paid_items.sort(key=lambda d: (not d.covered, -(d.days or 0)))
    overdue_items.sort(key=lambda d: -(d.days or 0))
    paid_not_found.items = paid_items[:MAX_ITEMS]
    overdue.items = overdue_items[:MAX_ITEMS]

    # ── The register's own health ──────────────────────────────────────────
    register = RegisterHealth(total=len(documents))
    missing_fields: dict[str, int] = {label: 0 for label in REQUIRED_FIELDS.values()}
    by_tipus: dict[str, int] = defaultdict(int)
    for document in documents:
        if document.status in IN_FLIGHT:
            register.in_flight += 1
            continue
        if document.status == "error":
            register.errors += 1
        elif document.validat:
            register.validated += 1
        else:
            register.needs_validation += 1
        if document.sheet_state != "synced":
            register.not_in_sheet += 1
        if not (document.upload_id or document.drive_file_id or document.file_link):
            register.without_file += 1
        if document.compte_corrent and not iban_is_valid(document.compte_corrent):
            register.invalid_iban += 1
        by_tipus[document.tipus_document or "Sense tipus"] += 1
        for field, label in REQUIRED_FIELDS.items():
            if field == "num_factura" and document.tipus_document not in {"Factura", "Factura simplificada"}:
                continue
            if getattr(document, field) in (None, ""):
                missing_fields[label] += 1
    register.missing_fields = {label: n for label, n in missing_fields.items() if n}
    register.by_tipus = dict(sorted(by_tipus.items(), key=lambda item: -item[1]))
    register.duplicates_removed = (
        session.query(DuplicateRemoval).filter(DuplicateRemoval.restored_at.is_(None)).count()
    )

    last_run = (
        session.query(MatchRun.finished_at)
        .filter(MatchRun.finished_at.isnot(None))
        .order_by(MatchRun.finished_at.desc())
        .first()
    )

    return StatusOverview(
        generated_at=datetime.now(UTC),
        today=today,
        payments=totals,
        documents=DocumentTotals(
            total=len(documents),
            payable=len(payable),
            justified=sum(1 for d in payable if d.id in confirmed_docs),
            validated=register.validated,
            needs_validation=register.needs_validation,
        ),
        accounts=accounts,
        months=months,
        missing_invoices=missing,
        amount_mismatches=mismatches,
        paid_not_found=paid_not_found,
        overdue=overdue,
        health=register,
        caixeta_synced_at=get_workspace_setting(session).caixeta_synced_at,
        last_run_at=last_run[0] if last_run else None,
    )
