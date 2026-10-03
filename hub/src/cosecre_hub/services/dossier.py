"""The statement dossier: one PDF that puts every bank line beside the invoice it paid.

It is what someone checking a statement asks for: each line, the register entry
behind it, and the photo of that invoice, in the statement's own order. The
first pages index every movement — justified or not, so a gap shows instead of
being left out quietly — and each justified line then gets a sheet of its own.
A photo goes on its sheet; a PDF original follows its sheet, whole.

Drawn straight on a reportlab canvas rather than with flowables: every page has
a fixed layout, which is what lets the index print each sheet's page number
before a single page exists.
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
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy.orm import Session, selectinload

from ..models import BankMovement, Document, PaymentMatch, StatementImport
from .statements import PAYMENT
from .text_format import format_date

logger = logging.getLogger(__name__)

# ── Page geometry and palette (the web app's tokens) ─────────────────────────

W, H = A4
MARGIN = 36
TOP = H - MARGIN
BOTTOM = MARGIN + 6
CONTENT_W = W - 2 * MARGIN

INK_900 = HexColor("#1c1917")
INK_500 = HexColor("#5c5048")
INK_400 = HexColor("#6f6259")
LINE = HexColor("#e4d8c4")
LINE_STRONG = HexColor("#d3c3aa")
SURFACE = HexColor("#fbf5ea")
ACCENT = HexColor("#b83c14")
OLIVE = HexColor("#3a5a3c")
OLIVE_BG = HexColor("#e8efe6")
GOLD = HexColor("#6f4c05")
GOLD_BG = HexColor("#fdf1d5")
DANGER = HexColor("#a52626")

SANS = "Helvetica"
BOLD = "Helvetica-Bold"

#: Index table: (heading, width, right-aligned). Widths add up to CONTENT_W.
COLUMNS = (
    ("Data", 50, False),
    ("Concepte", 194, False),
    ("Import", 64, True),
    ("Estat", 70, False),
    ("Factura", 115, False),
    ("Pàg.", 30.28, True),
)
ROW_H = 15
#: Where the table header sits on the first index page and on the others.
FIRST_TABLE_Y = TOP - 178
NEXT_TABLE_Y = TOP - 36

#: The longest side a photo keeps. Enough to read a ticket at A4, small enough
#: that a dossier of a hundred photos stays a file people can email.
IMAGE_MAX_PX = 1800

STATUS_LABEL = {
    "confirmed": "Justificat",
    "proposed": "Proposta",
    "unmatched": "Pendent",
    "rejected": "Sense factura",
    "no_match": "Sense factura",
    "not_applicable": "No aplica",
}
CATEGORIA_LABEL = {
    "comissio": "Comissió",
    "traspas_intern": "Traspàs intern",
    "ingres": "Ingrés",
    "devolucio": "Devolució",
    "saldo_inicial": "Saldo inicial",
}
DECIDED_LABEL = {
    "rules": "per regles",
    "openai": "per gpt-6-luna",
    "jev": "per Jev",
    "jev+openai": "per gpt-6-luna i Jev",
    "person": "a mà",
}


# ── What goes in ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Original:
    #: ``image``, ``pdf``, ``missing`` or ``unreadable``.
    kind: str
    path: Path | None = None
    name: str = ""
    pages: int = 0


@dataclass(slots=True)
class Sheet:
    match: PaymentMatch
    document: Document
    original: Original
    #: 1-based among its movement's sheets, and how many there are.
    position: int = 1
    of: int = 1
    page: int = 0


@dataclass(slots=True)
class Line:
    number: int
    movement: BankMovement
    sheets: list[Sheet] = field(default_factory=list)

    @property
    def is_payment(self) -> bool:
        return self.movement.categoria == PAYMENT

    @property
    def proposed(self) -> bool:
        return any(s.match.status != "confirmed" for s in self.sheets)


def _shown_matches(movement: BankMovement, proposals: bool) -> list[PaymentMatch]:
    """Confirmed invoices; with ``proposals``, the put-forward ones of an open line."""
    confirmed = [m for m in movement.matches if m.status == "confirmed" and m.document]
    if confirmed or not proposals or movement.match_status != "proposed":
        return confirmed
    live = [m for m in movement.matches if m.status == "proposed" and m.document]
    return [m for m in live if m.rank == 0] or live


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
        except Exception:  # noqa: BLE001 — a broken PDF is noted on its sheet, not fatal
            logger.warning("Unreadable PDF original %s", path, exc_info=True)
            return Original("unreadable", path, name)
    return Original("image", path, name)


def _lines(session: Session, statement: StatementImport, proposals: bool) -> list[Line]:
    movements = (
        session.query(BankMovement)
        .options(
            selectinload(BankMovement.matches)
            .selectinload(PaymentMatch.document)
            .selectinload(Document.upload)
        )
        .filter(BankMovement.import_id == statement.id)
        .all()
    )
    # A statement reads oldest first; undated lines (rare) go last.
    movements.sort(key=lambda m: (m.data or date.max, m.id))
    lines = []
    for number, movement in enumerate(movements, start=1):
        matches = sorted(
            _shown_matches(movement, proposals),
            key=lambda m: (m.document.data_factura or date.max, m.document.internal_doc_number),
        )
        sheets = [Sheet(m, m.document, _original(m.document)) for m in matches]
        for position, sheet in enumerate(sheets, start=1):
            sheet.position, sheet.of = position, len(sheets)
        lines.append(Line(number, movement, sheets))
    return lines


# ── Text helpers ─────────────────────────────────────────────────────────────


def _clean(value: object) -> str:
    """One line of text the standard PDF fonts can draw."""
    text = " ".join(str(value or "").split())
    return text.encode("cp1252", "replace").decode("cp1252")


def _money(value: float | None) -> str:
    if value is None:
        return "—"
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


def _period(statement: StatementImport, lines: list[Line]) -> str:
    dates = [line.movement.data for line in lines if line.movement.data]
    start = statement.period_from or (min(dates) if dates else None)
    end = statement.period_to or (max(dates) if dates else None)
    if not start and not end:
        return "sense dates"
    return f"{format_date(start)} – {format_date(end)}"


def _status(line: Line) -> tuple[str, object]:
    movement = line.movement
    if not line.is_payment:
        return CATEGORIA_LABEL.get(movement.categoria, "No aplica"), INK_400
    if line.sheets and line.proposed:
        return "Proposta", GOLD
    label = STATUS_LABEL.get(movement.match_status, movement.match_status)
    colour = {"confirmed": OLIVE, "rejected": DANGER, "no_match": DANGER}.get(movement.match_status, GOLD)
    return label, colour


def file_name(statement: StatementImport) -> str:
    stamp = statement.period_to or statement.period_from or date.today()
    account = "".join(ch if ch.isalnum() else "-" for ch in statement.compte.lower()).strip("-")
    return f"dossier-{account or 'extracte'}-{stamp:%Y-%m}.pdf"


# ── Pages ────────────────────────────────────────────────────────────────────


class _Pages:
    """The canvas, plus what every page shares: the footer and its numbering."""

    def __init__(self, target, statement: StatementImport, period: str, total: int):
        self.c = Canvas(target, pagesize=A4, pageCompression=1)
        self.c.setTitle(f"Dossier de justificació — {statement.compte} ({period})")
        self.c.setAuthor("Cosecre")
        self.footer_text = _clean(f"Cosecre · Extracte {statement.compte} · {period}")
        self.total = total
        self.page = 1

    def finish_page(self) -> None:
        c = self.c
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(MARGIN, MARGIN - 8, W - MARGIN, MARGIN - 8)
        c.setFont(SANS, 7)
        c.setFillColor(INK_400)
        c.drawString(MARGIN, MARGIN - 18, self.footer_text)
        c.drawRightString(W - MARGIN, MARGIN - 18, f"{self.page} / {self.total}")
        c.showPage()
        self.page += 1

    def eyebrow(self, text: str, y: float, colour=ACCENT) -> None:
        self.c.setFont(BOLD, 7)
        self.c.setFillColor(colour)
        self.c.drawString(MARGIN, y, text.upper(), charSpace=0.6)


def _rows_per_page(first: bool) -> int:
    top = (FIRST_TABLE_Y if first else NEXT_TABLE_Y) - 8
    return int((top - BOTTOM) // ROW_H)


def _index_pages(count: int) -> int:
    first = _rows_per_page(True)
    if count <= first:
        return 1
    rest = _rows_per_page(False)
    return 1 + -(-(count - first) // rest)


def _draw_index(pages: _Pages, statement: StatementImport, lines: list[Line], period: str, proposals: bool, today: date) -> None:
    c = pages.c
    payments = [line for line in lines if line.is_payment]
    confirmed = [line for line in payments if line.movement.match_status == "confirmed"]
    no_invoice = [line for line in payments if line.movement.match_status in {"rejected", "no_match"}]
    open_lines = len(payments) - len(confirmed) - len(no_invoice)
    paid_total = sum(abs(line.movement.import_value) for line in payments)
    justified_total = sum(abs(line.movement.import_value) for line in confirmed)

    # Header
    pages.eyebrow("Dossier de justificació", TOP - 8)
    c.setFont(BOLD, 18)
    c.setFillColor(INK_900)
    c.drawString(MARGIN, TOP - 30, _fit(f"Extracte {statement.compte}", BOLD, 18, CONTENT_W))
    c.setFont(SANS, 9)
    c.setFillColor(INK_500)
    meta = [f"Període {period}"]
    if statement.account_iban:
        meta.append(f"IBAN {statement.account_iban}")
    if statement.file_name:
        meta.append(statement.file_name)
    c.drawString(MARGIN, TOP - 46, _fit(" · ".join(meta), SANS, 9, CONTENT_W))
    c.setFont(SANS, 8)
    c.setFillColor(INK_400)
    note = f"Generat el {format_date(today)}."
    if proposals:
        note += " Inclou propostes encara no confirmades, marcades com a PROPOSTA."
    c.drawString(MARGIN, TOP - 59, _fit(note, SANS, 8, CONTENT_W))

    # Figures
    share = f"{round(100 * len(confirmed) / len(payments))} %" if payments else "—"
    stats = (
        ("Moviments", str(len(lines)), f"{len(payments)} pagaments"),
        ("Justificats", f"{len(confirmed)} de {len(payments)}", share),
        ("Import justificat", _money(justified_total), f"de {_money(paid_total)}"),
        ("Per resoldre", str(open_lines), f"{len(no_invoice)} sense factura"),
    )
    gap = 8
    box_w = (CONTENT_W - gap * 3) / 4
    box_top = TOP - 74
    for i, (label, value, sub) in enumerate(stats):
        x = MARGIN + i * (box_w + gap)
        c.setFillColor(SURFACE)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.roundRect(x, box_top - 52, box_w, 52, 3, stroke=1, fill=1)
        c.setFont(BOLD, 6.5)
        c.setFillColor(INK_400)
        c.drawString(x + 9, box_top - 14, label.upper(), charSpace=0.5)
        c.setFont(BOLD, 13)
        c.setFillColor(INK_900)
        c.drawString(x + 9, box_top - 31, _fit(value, BOLD, 13, box_w - 18))
        c.setFont(SANS, 7.5)
        c.setFillColor(INK_500)
        c.drawString(x + 9, box_top - 43, _fit(sub, SANS, 7.5, box_w - 18))

    c.setFont(BOLD, 10)
    c.setFillColor(INK_900)
    c.drawString(MARGIN, FIRST_TABLE_Y + 22, "Índex de moviments")

    remaining = list(lines)
    first = True
    while True:
        y = FIRST_TABLE_Y if first else NEXT_TABLE_Y
        if not first:
            pages.eyebrow("Índex de moviments (continuació)", TOP - 8)
        _table_header(c, y)
        take = _rows_per_page(first)
        chunk, remaining = remaining[:take], remaining[take:]
        y -= 8
        for line in chunk:
            y -= ROW_H
            _index_row(c, line, y)
        if not lines and first:
            c.setFont(SANS, 8.5)
            c.setFillColor(INK_400)
            c.drawString(MARGIN, y - ROW_H, "Aquest extracte no té cap moviment.")
        pages.finish_page()
        first = False
        if not remaining:
            break


def _table_header(c: Canvas, y: float) -> None:
    x = MARGIN
    c.setFont(BOLD, 6.5)
    c.setFillColor(INK_400)
    for heading, width, right in COLUMNS:
        if right:
            c.drawRightString(x + width - 4, y, heading.upper(), charSpace=0.5)
        else:
            c.drawString(x + 4, y, heading.upper(), charSpace=0.5)
        x += width
    c.setStrokeColor(LINE_STRONG)
    c.setLineWidth(0.8)
    c.line(MARGIN, y - 5, W - MARGIN, y - 5)


def _index_row(c: Canvas, line: Line, y: float) -> None:
    movement = line.movement
    dim = not line.is_payment
    status, colour = _status(line)
    first = line.sheets[0] if line.sheets else None
    invoice = ""
    if first:
        invoice = " · ".join(p for p in (first.document.num_factura or first.document.internal_doc_number, first.document.proveidor) if p)
        if len(line.sheets) > 1:
            invoice = f"+{len(line.sheets) - 1}  {invoice}"
    cells = (
        format_date(movement.data),
        movement.concepte or movement.mes_dades,
        _money(movement.import_value),
        status,
        invoice,
        str(first.page) if first else "",
    )
    x = MARGIN
    for (_, width, right), text, index in zip(COLUMNS, cells, range(len(cells))):
        font = BOLD if index == 2 and not dim else SANS
        c.setFont(font, 8)
        c.setFillColor(INK_400 if dim and index != 3 else INK_900)
        if index == 3:
            c.setFillColor(colour)
            c.circle(x + 6.5, y + 2.8, 2, stroke=0, fill=1)
            c.drawString(x + 12, y, _fit(text, SANS, 8, width - 14))
        elif right:
            c.drawRightString(x + width - 4, y, _fit(text, font, 8, width - 8))
        else:
            c.drawString(x + 4, y, _fit(text, font, 8, width - 8))
        x += width
    c.setStrokeColor(LINE)
    c.setLineWidth(0.4)
    c.line(MARGIN, y - 4.5, W - MARGIN, y - 4.5)


# ── One sheet per invoice ────────────────────────────────────────────────────


def _panel(c: Canvas, x: float, top: float, width: float, title: str, rows: list[tuple[str, str]], draw: bool) -> float:
    """Key/value rows under a heading; returns the height they take."""
    key_w = 66
    value_w = width - key_w - 16
    y = top - 24
    for key, value in rows:
        wrapped = _wrap(value or "—", SANS, 8.5, value_w, 3)
        if draw:
            c.setFont(SANS, 7.5)
            c.setFillColor(INK_400)
            c.drawString(x + 8, y, key)
            c.setFont(SANS, 8.5)
            c.setFillColor(INK_900 if value else INK_400)
            for i, text in enumerate(wrapped):
                c.drawString(x + 8 + key_w, y - i * 10.5, text)
        y -= 10.5 * len(wrapped) + 3.5
    height = top - y + 2
    if draw:
        c.setFont(BOLD, 6.5)
        c.setFillColor(ACCENT)
        c.drawString(x + 8, top - 11, title.upper(), charSpace=0.6)
    return height


def _draw_sheet(pages: _Pages, line: Line, sheet: Sheet, total_lines: int) -> None:
    c = pages.c
    movement, document, match = line.movement, sheet.document, sheet.match
    proposal = match.status != "confirmed"

    # Heading: which line, and its state.
    label = f"Moviment {line.number} de {total_lines}"
    if sheet.of > 1:
        label += f" · factura {sheet.position} de {sheet.of}"
    pages.eyebrow(label, TOP - 8, INK_400)
    tag = f"Proposta · {match.confidence} %" if proposal else "Justificat"
    tag_fg, tag_bg = (GOLD, GOLD_BG) if proposal else (OLIVE, OLIVE_BG)
    c.setFont(BOLD, 7)
    tag_w = stringWidth(tag.upper(), BOLD, 7) + len(tag) * 0.5 + 12
    c.setFillColor(tag_bg)
    c.roundRect(W - MARGIN - tag_w, TOP - 12, tag_w, 13, 2, stroke=0, fill=1)
    c.setFillColor(tag_fg)
    c.drawString(W - MARGIN - tag_w + 6, TOP - 8, tag.upper(), charSpace=0.5)

    amount = _money(movement.import_value)
    c.setFont(BOLD, 15)
    c.setFillColor(INK_900)
    c.drawRightString(W - MARGIN, TOP - 32, amount)
    title_w = CONTENT_W - stringWidth(amount, BOLD, 15) - 16
    c.setFont(BOLD, 13)
    c.drawString(MARGIN, TOP - 32, _fit(movement.concepte or "Moviment sense concepte", BOLD, 13, title_w))
    c.setFont(SANS, 8.5)
    c.setFillColor(INK_500)
    c.drawString(MARGIN, TOP - 45, _fit(f"{format_date(movement.data)} · {movement.compte}", SANS, 8.5, title_w))

    # The bank's side and the register's, side by side.
    bank = [
        ("Data", format_date(movement.data)),
        ("Data valor", format_date(movement.data_valor)),
        ("Concepte", movement.concepte),
        ("Més dades", movement.mes_dades),
        ("Import", _money(movement.import_value)),
        ("Saldo", _money(movement.saldo) if movement.saldo is not None else ""),
        ("Tipus", movement.tipus),
        ("Compte", movement.compte),
        ("Referència", movement.external_ref),
    ]
    register = [
        ("Núm. factura", document.num_factura),
        ("Núm. intern", document.internal_doc_number),
        ("Tipus", document.tipus_document),
        ("Data factura", format_date(document.data_factura)),
        ("Proveïdor", document.proveidor),
        ("CIF", document.cif_proveidor),
        ("Import", _money(document.import_value)),
        ("Descripció", document.descripcio or document.descripcio_compra),
        ("Compte", document.pressupost_afectat),
        ("Mètode", document.metode_pagament),
        ("Data pagament", format_date(document.data_pagament)),
        ("Responsable", document.responsable_nom),
        ("Validat", "Sí" if document.validat else "No"),
    ]
    gap = 10
    panel_w = (CONTENT_W - gap) / 2
    top = TOP - 58
    height = max(
        _panel(c, MARGIN, top, panel_w, "Extracte", bank, draw=False),
        _panel(c, MARGIN + panel_w + gap, top, panel_w, "Registre", register, draw=False),
    )
    for x, title, rows in ((MARGIN, "Extracte", bank), (MARGIN + panel_w + gap, "Registre", register)):
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.roundRect(x, top - height, panel_w, height, 3, stroke=1, fill=0)
        _panel(c, x, top, panel_w, title, rows, draw=True)

    # Does the money agree? Several invoices paid at once are summed.
    y = top - height - 14
    invoiced = [s.document.import_value for s in line.sheets]
    paid = abs(movement.import_value)
    if any(v is None for v in invoiced):
        check, colour = "Alguna factura no té import: no es pot comprovar la suma.", GOLD
    elif abs(sum(invoiced) - paid) < 0.01:
        what = "La factura" if len(invoiced) == 1 else f"Les {len(invoiced)} factures"
        check, colour = f"{what} sumen exactament l'import del moviment.", OLIVE
    else:
        check, colour = (
            f"Les factures sumen {_money(sum(invoiced))} i el moviment és de {_money(paid)}.",
            DANGER,
        )
    decided = DECIDED_LABEL.get(match.decided_by, match.decided_by)
    if proposal:
        how = f"Proposat {decided}, pendent de confirmar."
    else:
        when = f" el {format_date(match.confirmed_at.date())}" if match.confirmed_at else ""
        how = f"Relacionat {decided}{when}."
    c.setFillColor(colour)
    c.circle(MARGIN + 3, y + 2.8, 2.2, stroke=0, fill=1)
    c.setFont(SANS, 8)
    c.drawString(MARGIN + 10, y, _fit(check, SANS, 8, CONTENT_W * 0.62))
    c.setFillColor(INK_400)
    c.drawRightString(W - MARGIN, y, _fit(how, SANS, 8, CONTENT_W * 0.36))

    # The original fills the rest of the page.
    box_top = y - 12
    _draw_original(c, sheet, MARGIN, BOTTOM, CONTENT_W, box_top - BOTTOM)
    pages.finish_page()


def _draw_original(c: Canvas, sheet: Sheet, x: float, y: float, width: float, height: float) -> None:
    original = sheet.original
    c.setFont(BOLD, 6.5)
    c.setFillColor(ACCENT)
    c.drawString(x, y + height - 2, "ORIGINAL", charSpace=0.6)
    if original.name:
        c.setFont(SANS, 7.5)
        c.setFillColor(INK_400)
        c.drawString(x + 44, y + height - 2, _fit(original.name, SANS, 7.5, width - 44))
    frame_top = y + height - 9
    frame_h = frame_top - y
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)

    message = ""
    if original.kind == "image":
        try:
            reader, (px_w, px_h) = _image(original.path)
        except Exception:  # noqa: BLE001 — a photo that will not open is said so on the sheet
            logger.warning("Unreadable image original %s", original.path, exc_info=True)
            message = "No s'ha pogut llegir la foto original."
        else:
            scale = min((width - 12) / px_w, (frame_h - 12) / px_h)
            draw_w, draw_h = px_w * scale, px_h * scale
            image_x = x + (width - draw_w) / 2
            image_y = frame_top - 6 - draw_h
            c.drawImage(reader, image_x, image_y, draw_w, draw_h)
            c.rect(image_x, image_y, draw_w, draw_h, stroke=1, fill=0)
            return
    elif original.kind == "pdf":
        first = sheet.page + 1
        last = sheet.page + original.pages
        where = f"pàgina {first}" if first == last else f"pàgines {first}–{last}"
        message = f"L'original és un PDF i es reprodueix sencer a continuació ({where})."
    elif original.kind == "unreadable":
        message = "L'original és un PDF que no s'ha pogut llegir; descarrega'l del registre."
    else:
        message = "Aquesta entrada del registre no té cap original al servidor."

    c.setFillColor(SURFACE)
    c.roundRect(x, y, width, frame_h, 3, stroke=1, fill=1)
    c.setFont(SANS, 9)
    c.setFillColor(INK_500)
    c.drawCentredString(x + width / 2, y + frame_h / 2, _fit(message, SANS, 9, width - 24))


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


def build(session: Session, statement: StatementImport, *, proposals: bool = False, today: date | None = None) -> Path:
    """Write the dossier to a temporary file and return its path; the caller deletes it."""
    today = today or date.today()
    lines = _lines(session, statement, proposals)
    period = _period(statement, lines)

    # Number every page before drawing any: index, then each sheet followed by
    # its PDF original, if it has one.
    page = _index_pages(len(lines)) + 1
    for line in lines:
        for sheet in line.sheets:
            sheet.page = page
            page += 1 + (sheet.original.pages if sheet.original.kind == "pdf" else 0)
    total = page - 1

    handle, out_path = tempfile.mkstemp(prefix="cosecre-dossier-", suffix=".pdf")
    os.close(handle)
    try:
        drawn = io.BytesIO()
        pages = _Pages(drawn, statement, period, total)
        _draw_index(pages, statement, lines, period, proposals, today)
        for line in lines:
            for sheet in line.sheets:
                _draw_sheet(pages, line, sheet, len(lines))
        pages.c.save()
        drawn.seek(0)

        own = PdfReader(drawn)
        writer = PdfWriter()
        index_count = _index_pages(len(lines))
        for i in range(index_count):
            writer.add_page(own.pages[i])
        cursor = index_count
        for line in lines:
            for sheet in line.sheets:
                writer.add_page(own.pages[cursor])
                cursor += 1
                if sheet.original.kind == "pdf":
                    for original_page in PdfReader(sheet.original.path).pages:
                        writer.add_page(original_page)

        # Bookmarks, so a reader's sidebar jumps straight to a line.
        writer.add_outline_item("Índex de moviments", 0)
        for line in lines:
            if line.sheets:
                movement = line.movement
                title = f"{format_date(movement.data)} · {_money(movement.import_value)} · {movement.concepte}"
                writer.add_outline_item(_clean(title)[:90], line.sheets[0].page - 1)
        writer.add_metadata({"/Title": _clean(f"Dossier de justificació — {statement.compte} ({period})"), "/Author": "Cosecre"})
        with open(out_path, "wb") as sink:
            writer.write(sink)
    except Exception:
        os.unlink(out_path)
        raise
    return Path(out_path)
