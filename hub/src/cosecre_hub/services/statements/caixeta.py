"""The caixeta d'efectiu: the petty-cash ledger people keep in a Google Sheet.

Only the yearly tabs (``CAIXETA'25``, ``CAIXETA'26``…) are read: one row per
cash movement, keyed by its ``Cix_NNN`` number. The dated count tabs and the
Esfera comparison are someone's working papers, not movements.

The sheet is edited by hand, so a row can change after it was read. Its key
stays the same, which is what lets :mod:`.store` update it in place.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from ..text_format import parse_amount, parse_date
from . import INCOME, OPENING, PAYMENT, REFUND, SOURCE_CAIXETA, ParsedMovement, ParsedStatement

CASH = "Efectiu"
#: ``CAIXETA'26``, tolerating a typographic apostrophe or a space.
TAB_PATTERN = r"CAIXETA\s*['’]?\s*\d{2}"

_COLUMNS = {
    "o": "ref",
    "º": "ref",
    "data": "data",
    "numero factura": "num_factura",
    "num factura": "num_factura",
    "concepte": "concepte",
    "import": "import",
    "saldo": "saldo",
}
_NOT_A_NUMBER = {"DESPESA SIMPLIFICADA", "INGRES", "DEVOLUCIO", "SALDO INICIAL", ""}


def _fold(text: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or "").strip().lower())
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", folded).split()) or str(text or "").strip()


def content_fingerprint(tabs: dict[str, list[list[Any]]]) -> str:
    """Changes whenever any value in the read tabs does."""
    return hashlib.sha1(json.dumps(tabs, sort_keys=True, default=str).encode()).hexdigest()


def parse(tabs: dict[str, list[list[Any]]]) -> ParsedStatement:
    movements: list[ParsedMovement] = []
    for title, rows in tabs.items():
        if not rows:
            continue
        header = [_fold(h) for h in rows[0]]
        columns = {_COLUMNS[h]: i for i, h in enumerate(header) if h in _COLUMNS}
        if "ref" not in columns and header and header[0] in {"", "o"}:
            columns["ref"] = 0

        def cell(row: list[Any], name: str) -> Any:
            i = columns.get(name)
            return row[i] if i is not None and i < len(row) else None

        for row in rows[1:]:
            reference = str(cell(row, "ref") or "").strip()
            concept = str(cell(row, "concepte") or "").strip()
            amount = parse_amount(cell(row, "import"))
            when = parse_date(cell(row, "data"))
            number = str(cell(row, "num_factura") or "").strip()
            if not reference or (amount is None and _fold(concept) != "saldo inicial"):
                continue  # a numbered row nobody has filled in yet
            folded_number = _fold(number).upper()
            folded_concept = _fold(concept).upper()
            if folded_concept == "SALDO INICIAL":
                categoria = OPENING
            elif folded_number.startswith("DEVOLUCIO") or folded_concept.startswith("DEVOLUCIO"):
                categoria = REFUND
            elif (amount or 0) > 0 or folded_number.startswith("INGRES"):
                categoria = INCOME
            else:
                categoria = PAYMENT
            saldo = parse_amount(cell(row, "saldo"))
            movements.append(
                ParsedMovement(
                    data=when,
                    concepte=concept,
                    mes_dades=number,
                    import_value=round(amount or 0.0, 2),
                    saldo=round(saldo, 2) if saldo is not None else None,
                    tipus=CASH,
                    categoria=categoria,
                    num_factura_hint="" if folded_number in _NOT_A_NUMBER else number,
                    external_ref=reference,
                    identity=(SOURCE_CAIXETA, _fold(title), reference),
                    raw={"tab": title, "row": [str(v) for v in row]},
                )
            )
    return ParsedStatement(source=SOURCE_CAIXETA, movements=movements, compte="Caixeta")
