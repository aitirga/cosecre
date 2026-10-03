"""What agrees between a movement and a register entry — no model involved.

Each signal is 0–1 and means one thing a person would check:

* ``amount`` — the money is the same (to the cent).
* ``number`` — the invoice number is in the transfer's concept. The bank cuts
  concepts at ~17 characters, so a number the concept *starts* counts.
* ``cif`` — a direct debit's creditor reference carries the supplier's CIF.
* ``iban`` — the IBAN on the invoice is the one paid (when the bank says it).
* ``name`` — the supplier's name is the payee's, allowing for "SL" and truncation.
* ``date`` — paid within a plausible time of the invoice.
* ``consistency`` — what the invoice says about how and from where it is paid
  does not contradict the movement.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher

from ...models import BankMovement, Document

_LEGAL = {
    "sl", "sa", "slu", "sau", "sll", "scp", "sccl", "scoop", "sc", "cb", "ute", "sat", "s", "l",
    "u", "de", "del", "la", "el", "els", "les", "i", "y", "para", "per", "the", "en", "com",
    "www", "es", "spain", "espana", "iberica", "limited", "ltd", "llc", "inc", "gmbh", "ireland",
    "europe", "international", "distribuciones", "distribucions",
}


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or "").lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def compact_code(text: str) -> str:
    """``F003-9BM5-107`` → ``F0039BM5107``: separators never mean anything."""
    return re.sub(r"[^A-Z0-9]", "", fold(text).upper())


def _tokens(text: str) -> list[str]:
    return [t for t in fold(text).split() if len(t) >= 3 and t not in _LEGAL]


def amount_signal(movement_amount: float, total: float | None) -> float:
    if total is None:
        return 0.0
    return 1.0 if abs(abs(movement_amount) - abs(total)) <= 0.011 else 0.0


def number_signal(hint: str, haystack: str, num_factura: str) -> float:
    """Is the invoice number what the transfer's concept says?"""
    number = compact_code(num_factura)
    if len(number) < 2:
        return 0.0
    candidates = [compact_code(hint)] if hint else []
    candidates.append(compact_code(haystack))
    trimmed = number.lstrip("0") or number
    for index, text in enumerate(candidates):
        if not text:
            continue
        if text == number or text.lstrip("0") == trimmed:
            return 1.0
        # The concept was cut short: "TRA2026A060" is the start of "TRA2026A06012".
        if len(text) >= 6 and number.startswith(text):
            return 1.0
        # The concept carries more than the number: "140927CUSTOM".
        if len(number) >= 4 and (number in text or (len(trimmed) >= 4 and trimmed in text)):
            return 1.0 if hint and index == 0 else 0.8
    return 0.0


def cif_signal(movement: BankMovement, cif: str) -> float:
    code = compact_code(cif)
    if len(code) < 8:
        return 0.0
    if movement.cif_hint and compact_code(movement.cif_hint) == code:
        return 1.0
    return 1.0 if code in compact_code(f"{movement.mes_dades} {movement.concepte}") else 0.0


def iban_signal(movement: BankMovement, iban: str) -> float:
    if not movement.iban_hint or not iban:
        return 0.0
    return 1.0 if compact_code(movement.iban_hint) == compact_code(iban) else 0.0


def name_signal(text: str, supplier: str) -> float:
    """How much of the supplier's name the payee text carries, 0–1."""
    wanted = _tokens(supplier)
    have = _tokens(text)
    if not wanted or not have:
        return 0.0

    def present(token: str) -> bool:
        # Truncated names: "DISTR" for "distribucions", "CATAL" for "catalunya".
        return any(
            h == token or (len(h) >= 4 and token.startswith(h)) or (len(token) >= 4 and h.startswith(token))
            for h in have
        )

    overlap = sum(1 for token in wanted if present(token)) / len(wanted)
    ratio = SequenceMatcher(None, " ".join(wanted), " ".join(have)).ratio()
    return round(max(overlap, ratio if ratio >= 0.6 else 0.0), 3)


def date_signal(paid: date | None, invoiced: date | None, recorded_payment: date | None = None) -> float:
    if paid is None:
        return 0.0
    if recorded_payment is not None and abs((paid - recorded_payment).days) <= 3:
        return 1.0
    if invoiced is None:
        return 0.3
    days = (paid - invoiced).days
    if days < -10:
        return 0.0
    if days < 0:
        return 0.5  # paid in advance: a pro forma, a booking
    # Same week is best; a month is still ordinary; past four months, unlikely.
    if days <= 7:
        return 1.0
    if days <= 30:
        return round(1.0 - 0.3 * (days - 7) / 23, 3)
    return round(max(0.0, 0.7 - 0.7 * (days - 30) / 90), 3)


def consistency_signal(movement: BankMovement, document: Document) -> float:
    checks = []
    if document.metode_pagament and movement.tipus:
        checks.append(document.metode_pagament == movement.tipus)
    if document.pressupost_afectat:
        checks.append(document.pressupost_afectat == movement.compte)
    if not checks:
        return 0.5
    return sum(checks) / len(checks)


def payee_text(movement: BankMovement) -> str:
    return f"{movement.mes_dades} {movement.concepte}"


def score(movement: BankMovement, documents: list[Document]) -> dict[str, float]:
    """Signals for one document, or a set that together explains one payment."""
    text = payee_text(movement)
    total = sum(d.import_value or 0.0 for d in documents) if all(
        d.import_value is not None for d in documents
    ) else None

    def best(fn) -> float:
        values = [fn(d) for d in documents]
        # A set is only as convincing as its weakest member.
        return min(values) if len(documents) > 1 else values[0]

    return {
        "amount": amount_signal(movement.import_value, total),
        "number": best(lambda d: number_signal(movement.num_factura_hint, movement.concepte, d.num_factura)),
        "cif": best(lambda d: cif_signal(movement, d.cif_proveidor)),
        "iban": best(lambda d: iban_signal(movement, d.compte_corrent)),
        "name": best(lambda d: name_signal(text, d.proveidor)),
        "date": best(lambda d: date_signal(movement.data, d.data_factura, d.data_pagament)),
        "consistency": best(lambda d: consistency_signal(movement, d)),
    }
