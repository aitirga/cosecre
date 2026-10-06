"""The statement dossier: the statement itself, then the original invoices behind it.

Two parts, in one PDF:

1. **The statement**, laid out like the bank's own export — date, value date,
   movement, more details, amount, balance — then two yellow cells: the line's
   internal code (``G_014``, ``Cix_013``…) and the number of the invoice it
   paid. The code is always there; the number only when an invoice is
   confirmed, otherwise the cell is left to be written in by hand.
2. **The originals**, in the statement's order: every confirmed invoice whose
   original is a document (a PDF, not a photo), each page shrunk just enough
   to carry the line's code centred on top. Photos, and lines without an
   invoice, add no pages.

The caixeta reads in its own ``Cix_NNN`` order; every other account by date.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy.orm import Session, selectinload

from ..models import BankMovement, Document, PaymentMatch, StatementImport
from .statements import PAYMENT
from .statements.mirror import order
from .text_format import format_date

logger = logging.getLogger(__name__)

# ── Geometry and palette (the web app's tokens) ──────────────────────────────

LANDSCAPE = landscape(A4)
MARGIN = 36

INK_900 = HexColor("#1b2c46")
INK_500 = HexColor("#4a5f7f")
INK_400 = HexColor("#566b8c")
LINE = HexColor("#dbe5f3")
LINE_STRONG = HexColor("#c2d2ea")
HEADER_FILL = HexColor("#edf3fc")
WRITE_IN = HexColor("#fff2a8")

SANS = "Helvetica"
BOLD = "Helvetica-Bold"

#: The statement table: (heading, width, right-aligned). Widths add up to the
#: landscape content width, 770pt. The last two are the yellow cells.
COLUMNS = (
    ("Data", 50, False),
    ("Data valor", 50, False),
    ("Moviment", 190, False),
    ("Més dades", 190, False),
    ("Import", 68, True),
    ("Saldo", 68, True),
    ("Codi", 70, False),
    ("Núm. factura", 84, False),
)
CODE_COLUMN = len(COLUMNS) - 2
ROW_H = 16
FIRST_TABLE_Y = LANDSCAPE[1] - MARGIN - 70
NEXT_TABLE_Y = LANDSCAPE[1] - MARGIN - 18
BOTTOM = MARGIN + 6

#: An original's page keeps this much of itself (by side), so the code fits above it.
ORIGINAL_SCALE = 0.93


# ── What goes in ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Original:
    #: ``image``, ``pdf``, ``missing`` or ``unreadable``.
    kind: str
    path: Path | None = None
    name: str = ""
    pages: int = 0


@dataclass(slots=True)
class Invoice:
    document: Document
    original: Original


@dataclass(slots=True)
class Line:
    movement: BankMovement
    invoices: list[Invoice] = field(default_factory=list)

    @property
    def numbers(self) -> str:
        return ", ".join(i.document.num_factura or "?" for i in self.invoices)

    @property
    def originals(self) -> list[Invoice]:
        """The invoices that go in after the statement: documents, not photos."""
        return [i for i in self.invoices if i.original.kind == "pdf"]


def _original(document: Document) -> Original:
    upload = document.upload
    if upload is None or not upload.stored_path:
        return Original("missing")
    path = Path(upload.stored_path)
    if not path.exists():
        return Original("missing")
    name = upload.source_file_name or path.name
    if upload.source_file_type == "application/pdf" or path.suffix.lower() == ".pdf":
        try:
            return Original("pdf", path, name, len(PdfReader(path).pages))
        except Exception:  # noqa: BLE001 — a broken PDF gets a page saying so, not a failed dossier
            logger.warning("Unreadable PDF original %s", path, exc_info=True)
            return Original("unreadable", path, name)
    return Original("image", path, name)


def _lines(
    session: Session,
    statement: StatementImport,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[Line]:
    query = (
        session.query(BankMovement)
        .options(
            selectinload(BankMovement.matches)
            .selectinload(PaymentMatch.document)
            .selectinload(Document.upload)
        )
        .filter(BankMovement.import_id == statement.id)
    )
    # A range keeps only the lines dated inside it; an undated line has no place in one.
    if date_from:
        query = query.filter(BankMovement.data >= date_from)
    if date_to:
        query = query.filter(BankMovement.data <= date_to)
    lines = []
    for movement in order(query.all()):
        # Confirmed only: a proposal is a guess, and the dossier is what gets handed in.
        documents = sorted(
            (m.document for m in movement.matches if m.status == "confirmed" and m.document),
            key=lambda d: (d.data_factura or date.max, d.internal_doc_number),
        )
        lines.append(Line(movement, [Invoice(d, _original(d)) for d in documents]))
    return lines


# ── Text helpers ─────────────────────────────────────────────────────────────


def _clean(value: object) -> str:
    """One line of text the standard PDF fonts can draw."""
    text = " ".join(str(value or "").split())
    return text.encode("cp1252", "replace").decode("cp1252")


def _money(value: float | None) -> str:
    if value is None:
        return ""
    digits = f"{abs(value):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"{'-' if value < -0.004 else ''}{digits} €"


def _fit(text: str, font: str, size: float, width: float) -> str:
    """Cut ``text`` with an ellipsis so it fits ``width``."""
    text = _clean(text)
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _period(statement: StatementImport, lines: list[Line], date_from: date | None = None, date_to: date | None = None) -> str:
    dates = [line.movement.data for line in lines if line.movement.data]
    start = date_from or statement.period_from or (min(dates) if dates else None)
    end = date_to or statement.period_to or (max(dates) if dates else None)
    if not start and not end:
        return "sense dates"
    return f"{format_date(start)} – {format_date(end)}"


def file_name(statement: StatementImport, date_from: date | None = None, date_to: date | None = None) -> str:
    account = "".join(ch if ch.isalnum() else "-" for ch in statement.compte.lower()).strip("-") or "extracte"
    if date_from or date_to:
        start = date_from or statement.period_from
        end = date_to or statement.period_to
        span = "-".join(f"{d:%Y%m%d}" for d in (start, end) if d)
        return f"dossier-{account}-{span}.pdf"
    stamp = statement.period_to or statement.period_from or date.today()
    return f"dossier-{account}-{stamp:%Y-%m}.pdf"


# ── Pages ────────────────────────────────────────────────────────────────────


class _Pages:
    """The canvas, plus the footer every drawn page shares and its numbering.

    Only the statement is drawn; the originals after it still count in "n / N".
    """

    def __init__(self, target, statement: StatementImport, period: str, total: int):
        self.c = Canvas(target, pagesize=LANDSCAPE, pageCompression=1)
        self.c.setTitle(f"Dossier d'extracte — {statement.compte} ({period})")
        self.c.setAuthor("Cosecre")
        self.footer_text = _clean(f"Cosecre · Extracte {statement.compte} · {period}")
        self.total = total
        self.page = 1

    def start(self, size) -> None:
        self.c.setPageSize(size)

    def finish_page(self, size) -> None:
        c = self.c
        width = size[0]
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(MARGIN, MARGIN - 8, width - MARGIN, MARGIN - 8)
        c.setFont(SANS, 7)
        c.setFillColor(INK_400)
        c.drawString(MARGIN, MARGIN - 18, self.footer_text)
        c.drawRightString(width - MARGIN, MARGIN - 18, f"{self.page} / {self.total}")
        c.showPage()
        self.page += 1


def _rows_per_page(first: bool) -> int:
    top = (FIRST_TABLE_Y if first else NEXT_TABLE_Y) - 6
    return int((top - BOTTOM) // ROW_H)


def _statement_pages(count: int) -> int:
    first = _rows_per_page(True)
    if count <= first:
        return 1
    rest = _rows_per_page(False)
    return 1 + -(-(count - first) // rest)


def _draw_statement(pages: _Pages, statement: StatementImport, lines: list[Line], period: str, today: date, ranged: bool) -> None:
    c = pages.c
    width, height = LANDSCAPE
    top = height - MARGIN
    content_w = width - 2 * MARGIN

    pages.start(LANDSCAPE)
    c.setFont(BOLD, 16)
    c.setFillColor(INK_900)
    c.drawString(MARGIN, top - 16, _fit(f"Extracte {statement.compte}", BOLD, 16, content_w))
    meta = [f"Període {period}"]
    if statement.account_iban:
        meta.append(f"IBAN {statement.account_iban}")
    if statement.file_name:
        meta.append(statement.file_name)
    c.setFont(SANS, 8.5)
    c.setFillColor(INK_500)
    c.drawString(MARGIN, top - 31, _fit(" · ".join(meta), SANS, 8.5, content_w))
    payments = [line for line in lines if line.movement.categoria == PAYMENT]
    justified = [line for line in payments if line.invoices]
    note = (
        f"{len(lines)} moviments, {len(payments)} pagaments, {len(justified)} amb factura. "
        "Núm. factura en blanc: cap factura confirmada, es pot omplir a mà. "
        f"Generat el {format_date(today)}."
    )
    if ranged:
        note = f"Només els moviments del període {period}. " + note
    c.setFont(SANS, 7.5)
    c.setFillColor(INK_400)
    c.drawString(MARGIN, top - 44, _fit(note, SANS, 7.5, content_w))

    remaining = list(lines)
    first = True
    while True:
        if not first:
            pages.start(LANDSCAPE)
        y = FIRST_TABLE_Y if first else NEXT_TABLE_Y
        _table_header(c, y)
        take = _rows_per_page(first)
        chunk, remaining = remaining[:take], remaining[take:]
        y -= 6
        for line in chunk:
            y -= ROW_H
            _table_row(c, line, y)
        if not lines and first:
            c.setFont(SANS, 8.5)
            c.setFillColor(INK_400)
            empty = "No hi ha cap moviment en aquest període." if ranged else "Aquest extracte no té cap moviment."
            c.drawString(MARGIN, y - ROW_H, empty)
        pages.finish_page(LANDSCAPE)
        first = False
        if not remaining:
            break


def _table_header(c: Canvas, y: float) -> None:
    total = sum(width for _, width, _ in COLUMNS)
    c.setFillColor(HEADER_FILL)
    c.rect(MARGIN, y - 5, total, 15, stroke=0, fill=1)
    x = MARGIN
    c.setFont(BOLD, 6.5)
    c.setFillColor(INK_500)
    for heading, width, right in COLUMNS:
        if right:
            c.drawRightString(x + width - 4, y, heading.upper())
        else:
            c.drawString(x + 4, y, heading.upper())
        x += width
    c.setStrokeColor(LINE_STRONG)
    c.setLineWidth(0.6)
    c.line(MARGIN, y - 5, MARGIN + total, y - 5)


def _table_row(c: Canvas, line: Line, y: float) -> None:
    movement = line.movement
    values = (
        format_date(movement.data),
        format_date(movement.data_valor),
        movement.concepte,
        movement.mes_dades,
        _money(movement.import_value),
        _money(movement.saldo),
        movement.codi,
        line.numbers,
    )
    x = MARGIN
    for index, ((_, width, right), value) in enumerate(zip(COLUMNS, values, strict=True)):
        yellow = index >= CODE_COLUMN
        if yellow:
            c.setFillColor(WRITE_IN)
            c.rect(x + 1.5, y - 3.5, width - 3, ROW_H - 3, stroke=0, fill=1)
        font = BOLD if index == CODE_COLUMN else SANS
        c.setFillColor(INK_500 if index == 3 else INK_900)
        if index == len(COLUMNS) - 1 and _two_lines(c, value or "", x + 4, y, width - 8):
            x += width
            continue
        c.setFont(font, 7)
        text = _fit(value or "", font, 7, width - 8)
        if right:
            c.drawRightString(x + width - 4, y + 1.5, text)
        else:
            c.drawString(x + 4, y + 1.5, text)
        x += width
    c.setStrokeColor(LINE)
    c.setLineWidth(0.4)
    c.line(MARGIN, y - 4, x, y - 4)


def _two_lines(c: Canvas, text: str, x: float, y: float, width: float) -> bool:
    """Several invoices in one cell: two smaller lines rather than a cut-off list.

    Returns False when the text fits on one line and should be drawn normally.
    """
    if stringWidth(_clean(text), SANS, 7) <= width:
        return False
    parts = [p.strip() for p in text.split(",") if p.strip()]
    half = (len(parts) + 1) // 2
    rows = [", ".join(parts[:half]) + ("," if len(parts) > 1 else ""), ", ".join(parts[half:])]
    c.setFont(SANS, 5.6)
    c.drawString(x, y + 5, _fit(rows[0], SANS, 5.6, width))
    if rows[1]:
        c.drawString(x, y - 1.5, _fit(rows[1], SANS, 5.6, width))
    return True


def _code_overlay(width: float, height: float, band: float, codi: str) -> PageObject:
    buffer = io.BytesIO()
    c = Canvas(buffer, pagesize=(width, height))
    size = 15 if width < 700 else 18
    c.setFont(BOLD, size)
    c.setFillColor(INK_900)
    c.drawCentredString(width / 2, height - band / 2 - size / 3, _clean(codi or "—"))
    c.showPage()
    c.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]


def _add_with_code(writer: PdfWriter, source: PageObject, codi: str) -> None:
    """An original's page, nearly full size, with the line's code centred on top."""
    page = writer.add_page(source)
    page.transfer_rotation_to_content()
    box = page.mediabox
    width, height = float(box.width), float(box.height)
    edge = width * (1 - ORIGINAL_SCALE) / 2  # the sides' margin, and the bottom's
    band = height * (1 - ORIGINAL_SCALE) - edge  # what is left above, for the code
    page.add_transformation(
        Transformation()
        .translate(-float(box.left), -float(box.bottom))
        .scale(ORIGINAL_SCALE)
        .translate(edge, edge)
    )
    page.mediabox = page.cropbox = RectangleObject((0, 0, width, height))
    page.merge_page(_code_overlay(width, height, band, codi))


# ── Putting it together ──────────────────────────────────────────────────────


def build(
    session: Session,
    statement: StatementImport,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    today: date | None = None,
) -> Path:
    """Write the dossier to a temporary file and return its path; the caller deletes it.

    ``date_from``/``date_to`` (both inclusive, either optional) narrow it to the
    lines dated inside that range: a quarter of a year-long statement, say.
    """
    today = today or date.today()
    lines = _lines(session, statement, date_from, date_to)
    period = _period(statement, lines, date_from, date_to)

    plan = [(line, invoice) for line in lines for invoice in line.originals]
    statement_pages = _statement_pages(len(lines))
    total = statement_pages + sum(invoice.original.pages for _, invoice in plan)

    handle, out_path = tempfile.mkstemp(prefix="cosecre-dossier-", suffix=".pdf")
    os.close(handle)
    try:
        drawn = io.BytesIO()
        pages = _Pages(drawn, statement, period, total)
        _draw_statement(pages, statement, lines, period, today, ranged=bool(date_from or date_to))
        pages.c.save()
        drawn.seek(0)

        writer = PdfWriter()
        for page in PdfReader(drawn).pages:
            writer.add_page(page)
        writer.add_outline_item("Extracte", 0)
        current: BankMovement | None = None
        for line, invoice in plan:
            if line.movement is not current:
                current = line.movement
                title = " · ".join(
                    filter(None, [current.codi, format_date(current.data), _money(current.import_value), current.concepte])
                )
                writer.add_outline_item(_clean(title)[:90], len(writer.pages))
            for original_page in PdfReader(invoice.original.path).pages:
                _add_with_code(writer, original_page, current.codi)
        writer.add_metadata({"/Title": _clean(f"Dossier d'extracte — {statement.compte} ({period})"), "/Author": "Cosecre"})
        with open(out_path, "wb") as sink:
            writer.write(sink)
    except Exception:
        os.unlink(out_path)
        raise
    return Path(out_path)
