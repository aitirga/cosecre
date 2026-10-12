"""Cosecre's own export contract — not an Esfer@ payload.

Amounts are decimals (send them as strings, ``"30.00"``); remote IDs are the
portal's numeric IDs for the context named in :class:`ExportContext`, never row
numbers or codes.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...schemas.common import UtcDatetime

Environment = Literal["training", "production"]
Outcome = Literal["succeeded", "uncertain", "failed"]


class ExportContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Environment
    #: The centre's external code (``08000000``), as the portal session shows it.
    centre_code: str = Field(pattern=r"^\d{8}$")
    remote_centre_id: int = Field(gt=0)
    remote_budget_id: int = Field(gt=0)
    financial_year: int = Field(ge=2000, le=2100)
    #: Whether the centre settles VAT (``parametresCentre/liquidacioIVA``).
    vat_settlement: bool


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partida_remote_id: int = Field(gt=0)
    cost_centre_remote_id: int | None = Field(default=None, gt=0)
    base: Decimal
    #: ``None`` means unknown, which blocks: zero has to be said, not assumed.
    vat_amount: Decimal | None = None
    withholding_amount: Decimal = Decimal(0)


class DueDateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    amount: Decimal
    payment_type: str = Field(min_length=1, max_length=4)
    bank_account_remote_id: int | None = Field(default=None, gt=0)
    description: str | None = None


class InvoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A readable local reference (``DOC-2026-0042``); one active export each.
    source_ref: str = Field(min_length=1, max_length=64)
    document_id: int | None = None
    movement_id: int | None = None
    supplier_remote_id: int = Field(gt=0)
    document_number: str = Field(max_length=255)
    internal_number: str | None = Field(default=None, max_length=255)
    document_date: date
    accounting_date: date
    description: str = Field(max_length=2000)
    observations: str | None = Field(default=None, max_length=5000)
    total: Decimal
    lines: list[LineIn] = Field(max_length=50)
    due_dates: list[DueDateIn] = Field(max_length=24)


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ExportContext
    invoices: list[InvoiceIn] = Field(min_length=1, max_length=50)


class Approval(BaseModel):
    plan_hash: str = Field(min_length=64, max_length=64)


class Readback(BaseModel):
    """What the runner read back after saving: compared with the plan."""

    supplier_remote_id: int
    total: Decimal
    remote_budget_id: int
    document_number: str


class AttemptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: int
    outcome: Outcome
    remote_id: int | None = None
    remote_code: str | None = Field(default=None, max_length=64)
    readback: Readback | None = None
    http_status: int | None = None
    error: str | None = Field(default=None, max_length=2000)
    #: Only a read showing nothing was written turns a failure into ``failed``.
    no_effect_confirmed: bool = False


class Reconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool
    remote_id: int | None = None
    remote_code: str | None = Field(default=None, max_length=64)
    readback: Readback | None = None


class ProblemOut(BaseModel):
    field: str
    code: str
    message: str
    blocking: bool


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    outcome: str
    http_status: int | None
    remote_id: int | None
    error: str | None
    started_at: UtcDatetime
    finished_at: UtcDatetime | None


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_ref: str
    document_id: int | None
    movement_id: int | None
    duplicate_key: str
    state: str
    problems: list[ProblemOut]
    invoice: dict[str, Any]
    payload: dict[str, Any]
    remote_id: int | None
    remote_code: str | None
    attempts: list[AttemptOut]


class PlanOut(BaseModel):
    id: str
    state: str
    plan_hash: str
    context: dict[str, Any]
    created_at: UtcDatetime
    approved_at: UtcDatetime | None
    items: list[ItemOut]


class PlanSummary(BaseModel):
    id: str
    state: str
    environment: str
    centre_code: str
    items: int
    created_at: UtcDatetime


class PreflightOut(BaseModel):
    source_ref: str
    duplicate_key: str
    state: str
    problems: list[ProblemOut]
    payload: dict[str, Any]


class ClaimOut(BaseModel):
    plan_id: str
    item_id: int
    attempt_id: int
    #: The body to send to ``/factura/validate`` and ``/factura/desa``.
    payload: dict[str, Any]
    duplicate_key: str
    context: dict[str, Any]
