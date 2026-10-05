"""The statements, mirrored into the accounting spreadsheet: one tab per account.

Each tab reads like the bank's own export — date, value date, movement, more
details, amount, balance — with our code for the line in front and two columns
after it: the number of the invoice it paid, and that invoice's internal code.
Those two are the only cells meant to be edited; the bank's columns belong to
the bank.

This module is the pure half: what a tab contains, and how to read a person's
edits back out of one. Talking to Google and to the reconciliation lives in
``api.statements_mirror``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ...models import BankMovement, Document
from . import PAYMENT

TAB_PREFIX = "Extracte "

#: (header, kind). Kinds: ``text``, ``date``, ``money``.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("Codi", "text"),
    ("Data", "date"),
    ("Data valor", "date"),
    ("Moviment", "text"),
    ("Més dades", "text"),
    ("Import", "money"),
    ("Saldo", "money"),
    ("Núm. factura", "text"),
    ("Codi intern factura", "text"),
)
HEADERS = [header for header, _ in COLUMNS]
#: The bank's columns: a hand edit there is overwritten by the next write.
BANK_COLUMNS = len(COLUMNS) - 2
NUMBERS_COLUMN = HEADERS.index("Núm. factura")
REFS_COLUMN = HEADERS.index("Codi intern factura")
#: Points wide, for a tab created from scratch; people may resize them after.
WIDTHS = (80, 82, 82, 260, 300, 90, 90, 130, 170)


def tab_title(compte: str) -> str:
    return f"{TAB_PREFIX}{compte}"


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip().lower()


def split_list(text: object) -> list[str]:
    """``"A-1, B-2 ; c-3"`` → ``["A-1", "B-2", "c-3"]``. Order kept, repeats dropped."""
    seen: list[str] = []
    for part in re.split(r"[,;\n]+", str(text or "")):
        part = " ".join(part.split())
        if part and part.upper() not in (s.upper() for s in seen):
            seen.append(part)
    return seen


def canonical(text: object) -> str:
    """The form two cells are compared in: case, spacing and order don't count."""
    return ", ".join(sorted(p.upper() for p in split_list(text)))


def number_key(text: object) -> str:
    """An invoice number as it is compared: case, spaces and separators don't count.

    "A 12" finds "A-12". Two invoices that only differ in separators come back
    as ambiguous, which asks for the internal code instead of guessing.
    """
    return re.sub(r"[\s\-/._]+", "", str(text or "")).upper()


# ── Writing ──────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class MirrorLine:
    movement: BankMovement
    documents: list[Document]

    @property
    def refs(self) -> str:
        return ", ".join(d.internal_doc_number for d in self.documents)

    @property
    def numbers(self) -> str:
        return ", ".join(d.num_factura or "?" for d in self.documents) if self.documents else ""

    @property
    def tone(self) -> str:
        """``justified``, ``pending`` (a payment still without its invoice) or ``plain``."""
        if self.documents:
            return "justified"
        return "pending" if self.movement.categoria == PAYMENT else "plain"

    def values(self) -> list[Any]:
        m = self.movement
        return [m.codi, m.data, m.data_valor, m.concepte, m.mes_dades, m.import_value, m.saldo, self.numbers, self.refs]


@dataclass(slots=True)
class MirrorTab:
    compte: str
    lines: list[MirrorLine] = field(default_factory=list)

    @property
    def title(self) -> str:
        return tab_title(self.compte)


def order(movements: list[BankMovement]) -> list[BankMovement]:
    """Oldest first, like reading the statement; undated lines last."""
    return sorted(movements, key=lambda m: (m.data or date.max, m.id))


def confirmed_documents(movement: BankMovement) -> list[Document]:
    documents = [m.document for m in movement.matches if m.status == "confirmed" and m.document]
    return sorted(documents, key=lambda d: (d.data_factura or date.max, d.internal_doc_number))


def build_tabs(movements: list[BankMovement]) -> list[MirrorTab]:
    """One tab per account, accounts in alphabetical order."""
    tabs: dict[str, MirrorTab] = {}
    for movement in order(movements):
        tab = tabs.setdefault(movement.compte, MirrorTab(movement.compte))
        tab.lines.append(MirrorLine(movement, confirmed_documents(movement)))
    return [tabs[name] for name in sorted(tabs)]


# ── Reading edits back ───────────────────────────────────────────────────────


@dataclass(slots=True)
class SheetLine:
    row: int  # 1-based, as the sheet numbers it
    codi: str
    numbers: str
    refs: str


def parse_tab(grid: list[list[Any]]) -> list[SheetLine]:
    """The rows of a mirror tab that carry a code, found by their headers.

    Headers rather than positions, so a column someone moved still reads.
    """
    if not grid:
        return []
    header = {_fold(cell): index for index, cell in enumerate(grid[0]) if str(cell or "").strip()}
    codi = header.get(_fold("Codi"))
    numbers = header.get(_fold("Núm. factura"))
    refs = header.get(_fold("Codi intern factura"))
    if codi is None:
        return []

    def cell(row: list[Any], index: int | None) -> str:
        if index is None or index >= len(row) or row[index] is None:
            return ""
        value = row[index]
        # Sheets hands back a number for a cell that looks like one.
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value).strip()

    lines = []
    for row_number, row in enumerate(grid[1:], start=2):
        code = cell(row, codi)
        if code:
            lines.append(SheetLine(row_number, code, cell(row, numbers), cell(row, refs)))
    return lines


@dataclass(slots=True)
class Edit:
    """What a person asked for on one line, read from the sheet."""

    movement: BankMovement
    #: ``refs`` (internal codes typed) or ``numbers`` (invoice numbers typed).
    by: str
    wanted: list[str]


def edits(movement: BankMovement, line: SheetLine) -> Edit | None:
    """The hand edit on ``line``, if any: a cell that differs from what was last written.

    The internal code wins when both changed — it is the unambiguous one. A line
    the mirror never wrote has no baseline, so nothing on it counts as an edit.
    """
    if movement.mirror_refs is None:
        return None
    if canonical(line.refs) != canonical(movement.mirror_refs):
        return Edit(movement, "refs", split_list(line.refs))
    if canonical(line.numbers) != canonical(movement.mirror_numbers or ""):
        return Edit(movement, "numbers", split_list(line.numbers))
    return None
