"""The Estat page: one read of how far the accounting has got."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class Tally(BaseModel):
    """How many, and how much money they add up to (always positive)."""

    count: int = 0
    amount: float = 0.0


class PaymentTotals(BaseModel):
    """Every payment line of every statement, by where its justification is."""

    total: Tally = Field(default_factory=Tally)
    confirmed: Tally = Field(default_factory=Tally)
    #: The AI put an invoice forward; a person has to confirm it.
    proposed: Tally = Field(default_factory=Tally)
    #: Nobody has run the justification over it yet.
    unmatched: Tally = Field(default_factory=Tally)
    #: No invoice in the register: the AI found none, or a person said so.
    missing: Tally = Field(default_factory=Tally)


class DocumentTotals(BaseModel):
    total: int = 0
    #: Entries that should have a payment behind them (not quotes or delivery notes).
    payable: int = 0
    #: Payable entries a confirmed movement already pays.
    justified: int = 0
    validated: int = 0
    needs_validation: int = 0


class MonthGap(BaseModel):
    """A run of months, inside an account's history, with no statement at all."""

    from_month: str
    to_month: str
    months: int


class AccountStatus(BaseModel):
    compte: str
    statements: int = 0
    period_from: date | None = None
    period_to: date | None = None
    last_upload_at: datetime | None = None
    #: Days from the last movement covered to today; ``None`` with no statement.
    days_since: int | None = None
    payments: PaymentTotals = Field(default_factory=PaymentTotals)
    gaps: list[MonthGap] = Field(default_factory=list)


class MonthCell(BaseModel):
    compte: str
    #: Some statement of this account covers part of the month.
    covered: bool = False
    payments: int = 0
    confirmed: int = 0
    #: Proposed or not looked at yet.
    pending: int = 0
    missing: int = 0
    pending_amount: float = 0.0


class MonthRow(BaseModel):
    month: str
    cells: list[MonthCell]


class MovementIssue(BaseModel):
    movement_id: int
    import_id: int
    compte: str
    data: date | None = None
    concepte: str = ""
    mes_dades: str = ""
    #: Positive: what left the account.
    amount: float
    match_status: str
    documents: list[str] = Field(default_factory=list)
    documents_amount: float | None = None
    #: ``amount - documents_amount``: positive means the invoices fall short.
    difference: float | None = None


class DocumentIssue(BaseModel):
    num_doc_intern: str
    num_factura: str = ""
    proveidor: str = ""
    data_factura: date | None = None
    data_pagament: date | None = None
    import_value: float | None = None
    compte: str = ""
    pagament: str = ""
    metode_pagament: str = ""
    #: A movement has it as a proposal waiting for confirmation.
    has_proposal: bool = False
    #: A statement of its account covers its date, so the payment should be there.
    covered: bool = False
    days: int | None = None


class MovementIssues(BaseModel):
    total: Tally = Field(default_factory=Tally)
    items: list[MovementIssue] = Field(default_factory=list)


class DocumentIssues(BaseModel):
    total: Tally = Field(default_factory=Tally)
    items: list[DocumentIssue] = Field(default_factory=list)


class RegisterHealth(BaseModel):
    total: int = 0
    in_flight: int = 0
    errors: int = 0
    needs_validation: int = 0
    validated: int = 0
    #: Changed here but not yet in the spreadsheet, or taken out of it.
    not_in_sheet: int = 0
    without_file: int = 0
    invalid_iban: int = 0
    duplicates_removed: int = 0
    #: Field label → entries that leave it empty.
    missing_fields: dict[str, int] = Field(default_factory=dict)
    by_tipus: dict[str, int] = Field(default_factory=dict)


class StatusOverview(BaseModel):
    generated_at: datetime
    today: date
    payments: PaymentTotals
    documents: DocumentTotals
    accounts: list[AccountStatus]
    months: list[MonthRow]
    missing_invoices: MovementIssues
    amount_mismatches: MovementIssues
    #: Marked "Pagat" in the register, and no movement justifies it.
    paid_not_found: DocumentIssues
    #: "Pendent de pagament" for longer than ``OVERDUE_DAYS``.
    overdue: DocumentIssues
    health: RegisterHealth
    caixeta_synced_at: datetime | None = None
    last_run_at: datetime | None = None
