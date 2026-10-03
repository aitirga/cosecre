"""Bringing bank statements in: five sources, three formats, one shape.

Every reader here turns its source into :class:`ParsedStatement` — a list of
:class:`ParsedMovement` — and :mod:`.store` writes that to the database. Nothing
in this package matches movements to invoices; that is ``services.matching``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any

#: Where a movement came from.
SOURCE_CAIXA = "caixa_xls"
SOURCE_PREPAID = "prepaid_pdf"
SOURCE_CAIXETA = "caixeta_sheet"

#: Movements that should have an invoice behind them. Everything else is
#: bookkeeping between the school's own pockets, or money coming in.
PAYMENT = "pagament"
FEE = "comissio"
INTERNAL = "traspas_intern"
INCOME = "ingres"
REFUND = "devolucio"
OPENING = "saldo_inicial"
CATEGORIES = (PAYMENT, FEE, INTERNAL, INCOME, REFUND, OPENING)


@dataclass(slots=True)
class ParsedMovement:
    data: date | None
    concepte: str
    import_value: float
    tipus: str = ""
    categoria: str = PAYMENT
    data_valor: date | None = None
    mes_dades: str = ""
    saldo: float | None = None
    num_factura_hint: str = ""
    cif_hint: str = ""
    iban_hint: str = ""
    external_ref: str = ""
    #: The source's own key parts, hashed into the fingerprint.
    identity: tuple[Any, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        text = "|".join("" if part is None else str(part) for part in self.identity)
        return hashlib.sha1(text.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ParsedStatement:
    source: str
    movements: list[ParsedMovement]
    account_iban: str = ""
    #: A ``COMPTES`` label when the source itself says which account it is.
    compte: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def period(self) -> tuple[date | None, date | None]:
        dates = [m.data for m in self.movements if m.data]
        return (min(dates), max(dates)) if dates else (None, None)


class StatementError(ValueError):
    """The file is not a statement this package can read. The message is for people."""
