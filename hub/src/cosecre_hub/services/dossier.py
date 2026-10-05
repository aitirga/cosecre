"""The statement dossier: the statement itself, then the paper behind each payment.

Two parts, in one PDF:

1. **The statement**, laid out like the bank's own export — date, value date,
   movement, more details, amount, balance — with our code for each line in
   front and, after it, the number and internal code of the invoice that line
   paid. Only confirmed links fill those two cells; anything less certain
   leaves them empty, with room to write the invoice in by hand.
2. **The justificants**, in the statement's order. For each payment:
   * an invoice whose original is a PDF: that PDF, whole;
   * an invoice that is a photo (a ticket): a page with the line's code, date,
     concept and amount, and the photo printed below;
   * no invoice at all: the same page with nothing below, ready for the paper
     to be stapled on.

Lines that are not payments (fees, income, internal transfers) appear in the
statement but need no page of their own.

Drawn straight on a reportlab canvas: every page has a fixed layout, so the
page count — and each footer's "page n of N" — is known before drawing starts.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy.orm import Session, selectinload

from ..models import BankMovement, Document, PaymentMatch, StatementImport
from .statements import PAYMENT
from .text_format import format_date

logger = logging.getLogger(__name__)

# ── Geometry and palette (the web app's tokens) ──────────────────────────────

PORTRAIT = A4
LANDSCAPE = landscape(A4)
MARGIN = 36

INK_900 = HexColor("#1b2c46")
INK_500 = HexColor("#4a5f7f")
INK_400 = HexColor("#566b8c")
LINE = HexColor("#dbe5f3")
LINE_STRONG = HexColor("#c2d2ea")
HEADER_FILL = HexColor("#edf3fc")
ACCENT = HexColor("#2f5aa8")
WRITE_IN = HexColor("#fdf1de")

SANS = "Helvetica"
BOLD = "Helvetica-Bold"

#: The statement table: (heading, width, right-aligned). Widths add up to the
#: landscape content width, 770pt.
COLUMNS = (
    ("Codi", 50, False),
    ("Data", 48, False),
    ("Data valor", 48, False),
    ("Moviment", 160, False),
    ("Més dades", 160, False),
    ("Import", 62, True),
    ("Saldo", 62, True),
    ("Núm. factura", 76, False),
    ("Codi intern factura", 104, False),
)
ROW_H = 16
FIRST_TABLE_Y = LANDSCAPE[1] - MARGIN - 70
NEXT_TABLE_Y = LANDSCAPE[1] - MARGIN - 18
BOTTOM = MARGIN + 6

#: The longest side a photo keeps. Enough to read a ticket at A4, small enough
#: that a dossier of a hundred photos stays a file people can email.
IMAGE_MAX_PX = 1800


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
    def needs_paper(self) -> bool:
        """A payment, or anything someone linked an invoice to."""
        return bool(self.invoices) or self.movement.categoria == PAYMENT

    @property
    def numbers(self) -> str:
        return ", ".join(i.document.num_factura or "?" for i in self.invoices)

    @property
    def refs(self) -> str:
        return ", ".join(i.document.internal_doc_number for i in self.invoices)

    def pages(self) -> list[tuple[str, Invoice | None]]:
        """What this line contributes after the statement, in order.

        ``("pdf", invoice)`` is the original appended whole; ``("ticket",
        invoice)`` a drawn page with the photo; ``("blank", None)`` a drawn page
        with only the line's details.
        """
        if not self.needs_paper:
            return []
        if not self.invoices:
            return [("blank", None)]
        return [("pdf" if i.original.kind == "pdf" else "ticket", i) for i in self.invoices]


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
    movements = query.all()
    # A statement reads oldest first; undated lines (rare) go last.
    movements.sort(key=lambda m: (m.data or date.max, m.id))
    lines = []
    for movement in movements:
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


def _wrap(text: str, font: str, size: float, width: float, max_lines: int) -> list[str]:
    lines = simpleSplit(_clean(text), font, size, width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _fit(lines[-1] + " …", font, size, width)
    return lines


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

    Appended PDF originals are not drawn here, but they count: ``skip`` moves
    the numbering past them so the next drawn page reads the right number.
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

    def skip(self, pages: int) -> None:
        self.page += pages


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
        "Les caselles de factura en groc no tenen cap factura confirmada: es poden omplir a mà. "
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
        movement.codi,
        format_date(movement.data),
        format_date(movement.data_valor),
        movement.concepte,
        movement.mes_dades,
        _money(movement.import_value),
        _money(movement.saldo),
        line.numbers,
        line.refs,
    )
    x = MARGIN
    for index, ((_, width, right), value) in enumerate(zip(COLUMNS, values, strict=True)):
        invoice_cell = index >= len(COLUMNS) - 2
        if invoice_cell and line.needs_paper and not line.invoices:
            # Room to write the invoice in by hand.
            c.setFillColor(WRITE_IN)
            c.rect(x + 1.5, y - 3.5, width - 3, ROW_H - 3, stroke=0, fill=1)
        font = BOLD if index == 0 else SANS
        c.setFillColor(INK_500 if index == 4 else INK_900)
        if invoice_cell and _two_lines(c, value or "", x + 4, y, width - 8):
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


def _draw_details(pages: _Pages, line: Line, invoice: Invoice | None) -> float:
    """The head every drawn justificant page shares; returns where the body starts."""
    c = pages.c
    width, height = PORTRAIT
    top = height - MARGIN
    content_w = width - 2 * MARGIN
    movement = line.movement

    c.setFont(BOLD, 7)
    c.setFillColor(ACCENT)
    c.drawString(MARGIN, top - 8, "CODI INTERN", charSpace=0.6)
    c.setFont(BOLD, 22)
    c.setFillColor(INK_900)
    c.drawString(MARGIN, top - 32, _clean(movement.codi or "—"))

    rows = [
        ("Data de pagament", format_date(movement.data)),
        ("Concepte / empresa", movement.concepte or "—"),
        ("Import", _money(movement.import_value)),
    ]
    if invoice is not None:
        document = invoice.document
        rows.append(
            ("Factura", " · ".join(filter(None, [document.num_factura or "sense número", document.internal_doc_number, document.proveidor])))
        )
    y = top - 54
    for label, value in rows:
        c.setFont(BOLD, 7)
        c.setFillColor(INK_400)
        c.drawString(MARGIN, y + 1, label.upper(), charSpace=0.4)
        c.setFont(SANS, 10.5)
        c.setFillColor(INK_900)
        for text in _wrap(value, SANS, 10.5, content_w - 120, 2):
            c.drawString(MARGIN + 120, y, text)
            y -= 13
        y -= 5
    c.setStrokeColor(LINE_STRONG)
    c.setLineWidth(0.6)
    c.line(MARGIN, y + 6, width - MARGIN, y + 6)
    return y - 6


def _draw_blank(pages: _Pages, line: Line) -> None:
    pages.start(PORTRAIT)
    _draw_details(pages, line, None)
    pages.finish_page(PORTRAIT)


def _draw_ticket(pages: _Pages, line: Line, invoice: Invoice) -> None:
    c = pages.c
    pages.start(PORTRAIT)
    body_top = _draw_details(pages, line, invoice)
    width = PORTRAIT[0] - 2 * MARGIN
    height = body_top - BOTTOM
    original = invoice.original

    message = ""
    if original.kind == "image":
        try:
            reader, (px_w, px_h) = _image(original.path)
        except Exception:  # noqa: BLE001 — a photo that will not open is said so on its page
            logger.warning("Unreadable image original %s", original.path, exc_info=True)
            message = "No s'ha pogut llegir la foto original."
        else:
            scale = min(width / px_w, height / px_h)
            draw_w, draw_h = px_w * scale, px_h * scale
            c.drawImage(reader, MARGIN + (width - draw_w) / 2, body_top - draw_h, draw_w, draw_h)
    elif original.kind == "unreadable":
        message = "L'original és un PDF que no s'ha pogut llegir; descarrega'l del registre."
    else:
        message = "Aquesta factura no té cap original al servidor."
    if message:
        c.setFont(SANS, 9)
        c.setFillColor(INK_500)
        c.drawString(MARGIN, body_top - 14, _fit(message, SANS, 9, width))
    pages.finish_page(PORTRAIT)


def _image(path: Path) -> tuple[ImageReader, tuple[int, int]]:
    """The photo upright, flattened on white and shrunk to a sensible size."""
    with Image.open(path) as source:
        source.draft("RGB", (IMAGE_MAX_PX, IMAGE_MAX_PX))  # JPEG decodes small; others ignore it
        image = ImageOps.exif_transpose(source)
        if image.mode in {"RGBA", "LA", "P"}:
            image = image.convert("RGBA")
            flat = Image.new("RGB", image.size, "white")
            flat.paste(image, mask=image.getchannel("A"))
            image = flat
        else:
            image = image.convert("RGB")
        image.thumbnail((IMAGE_MAX_PX, IMAGE_MAX_PX))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=82, optimize=True)
    buffer.seek(0)
    return ImageReader(buffer), image.size


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

    plan = [(line, kind, invoice) for line in lines for kind, invoice in line.pages()]
    statement_pages = _statement_pages(len(lines))
    total = statement_pages + sum(invoice.original.pages if kind == "pdf" else 1 for _, kind, invoice in plan)

    handle, out_path = tempfile.mkstemp(prefix="cosecre-dossier-", suffix=".pdf")
    os.close(handle)
    try:
        # Every drawn page, in order, numbered as it will be in the final file.
        drawn = io.BytesIO()
        pages = _Pages(drawn, statement, period, total)
        _draw_statement(pages, statement, lines, period, today, ranged=bool(date_from or date_to))
        for line, kind, invoice in plan:
            if kind == "pdf":
                pages.skip(invoice.original.pages)
            elif kind == "ticket":
                _draw_ticket(pages, line, invoice)
            else:
                _draw_blank(pages, line)
        pages.c.save()
        drawn.seek(0)

        # Then the drawn pages and the PDF originals, interleaved.
        own = PdfReader(drawn)
        writer = PdfWriter()
        cursor = 0
        for _ in range(statement_pages):
            writer.add_page(own.pages[cursor])
            cursor += 1
        writer.add_outline_item("Extracte", 0)
        current: BankMovement | None = None
        for line, kind, invoice in plan:
            if line.movement is not current:
                current = line.movement
                title = " · ".join(
                    filter(None, [current.codi, format_date(current.data), _money(current.import_value), current.concepte])
                )
                writer.add_outline_item(_clean(title)[:90], len(writer.pages))
            if kind == "pdf":
                for original_page in PdfReader(invoice.original.path).pages:
                    writer.add_page(original_page)
            else:
                writer.add_page(own.pages[cursor])
                cursor += 1
        writer.add_metadata({"/Title": _clean(f"Dossier d'extracte — {statement.compte} ({period})"), "/Author": "Cosecre"})
        with open(out_path, "wb") as sink:
            writer.write(sink)
    except Exception:
        os.unlink(out_path)
        raise
    return Path(out_path)
