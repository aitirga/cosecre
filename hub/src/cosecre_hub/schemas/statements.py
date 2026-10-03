"""Bank statements and their reconciliation with the register."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MatchStatus = Literal["unmatched", "proposed", "no_match", "confirmed", "rejected", "not_applicable"]
Categoria = Literal["pagament", "comissio", "traspas_intern", "ingres", "devolucio", "saldo_inicial"]


class StatementRead(BaseModel):
    id: int
    source: str
    compte: str
    account_iban: str = ""
    file_name: str = ""
    status: str
    error_message: str | None = None
    period_from: date | None = None
    period_to: date | None = None
    rows_total: int = 0
    rows_new: int = 0
    rows_duplicate: int = 0
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    has_file: bool = False
    warnings: list[str] = Field(default_factory=list)


class MovementRead(BaseModel):
    id: int
    import_id: int
    source: str
    compte: str
    tipus: str
    categoria: str
    data: date | None = None
    data_valor: date | None = None
    concepte: str = ""
    mes_dades: str = ""
    import_value: float
    saldo: float | None = None
    num_factura_hint: str = ""
    cif_hint: str = ""
    iban_hint: str = ""
    external_ref: str = ""
    #: The line as the source gave it, for the review screen's detail card.
    raw: dict[str, Any] = Field(default_factory=dict)
    match_status: MatchStatus
    linked_movement_id: int | None = None
    #: The best open (or the confirmed) proposal's confidence, for the list.
    confidence: int | None = None
    #: Register references of the proposed or confirmed invoice(s).
    documents: list[str] = Field(default_factory=list)


class MovementUpdate(BaseModel):
    tipus: str | None = None
    categoria: Categoria | None = None


class CaixetaStatus(BaseModel):
    configured: bool
    synced_at: datetime | None = None
    running: bool = False
    error: str | None = None
    statement_id: int | None = None
    changed: bool | None = None


class AccountNeeded(BaseModel):
    code: Literal["needs_account"] = "needs_account"
    iban: str
    message: str


# ── Reconciliation ──────────────────────────────────────────────────────────


class ReconcileStatement(StatementRead):
    payments: int = 0
    unmatched: int = 0
    proposed: int = 0
    confirmed: int = 0
    rejected: int = 0
    not_applicable: int = 0
    #: Proposals by colour band: ``high``, ``medium``, ``low``.
    bands: dict[str, int] = Field(default_factory=dict)


class DocumentBrief(BaseModel):
    """What the review screen shows of a register entry."""

    num_doc_intern: str
    num_factura: str = ""
    proveidor: str = ""
    cif_proveidor: str = ""
    data_factura: date | None = None
    data_pagament: date | None = None
    import_value: float | None = None
    compte: str = ""
    metode_pagament: str = ""
    pagament: str = ""
    compte_corrent: str = ""
    descripcio: str = ""
    file_url: str | None = None


class MatchRead(BaseModel):
    id: int
    status: str
    rank: int
    confidence: int
    band: str
    decided_by: str
    reason: str = ""
    signals: dict[str, Any] = Field(default_factory=dict)
    ai_trace: dict[str, Any] | None = None
    #: Matches sharing ``group`` were proposed together, as one payment of several invoices.
    group: int = 0
    document: DocumentBrief


class MovementDetail(MovementRead):
    matches: list[MatchRead] = Field(default_factory=list)
    linked_movement: MovementRead | None = None


class RunRequest(BaseModel):
    import_id: int | None = None


class RunRead(BaseModel):
    id: int
    import_id: int | None = None
    status: str
    total: int
    processed: int
    proposed: int
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ConfirmRequest(BaseModel):
    document_refs: list[str] = Field(min_length=1)


class PaymentRead(BaseModel):
    """A confirmed (or proposed) payment, as seen from a register entry."""

    movement_id: int
    import_id: int
    status: str
    confidence: int
    compte: str
    tipus: str
    data: date | None = None
    concepte: str = ""
    mes_dades: str = ""
    import_value: float
