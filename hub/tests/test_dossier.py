from __future__ import annotations

import io
from datetime import date, timedelta

from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from test_documents import RECORDS, register, upload  # noqa: F401  (fixture)

from cosecre_hub.models import BankMovement, Document, PaymentMatch, StatementImport

DOSSIER = "/api/v1/tools/statement-dossier"


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (600, 900), "#f5ecdd").save(buffer, "JPEG")
    return buffer.getvalue()


def _pdf(pages: int) -> bytes:
    buffer = io.BytesIO()
    canvas = Canvas(buffer)
    for number in range(pages):
        canvas.drawString(100, 700, f"Factura en PDF, pàgina {number + 1}")
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _statement(client, lines):
    """``lines``: ``(amount, status, [(reference, match status)], categoria)``."""
    with client.app.state.session_factory() as session:
        statement = StatementImport(
            source="caixa_xls", compte="General", file_name="extracte.xls",
            period_from=date(2026, 1, 1), period_to=date(2026, 3, 31),
        )
        session.add(statement)
        session.flush()
        for day, (amount, status, matches, categoria) in enumerate(lines, start=1):
            movement = BankMovement(
                import_id=statement.id, fingerprint=f"m{day}", source="caixa_xls", compte="General",
                data=date(2026, 1, 1) + timedelta(days=day), concepte=f"COMPRA {day} · Café Ñandú", import_value=amount,
                codi=f"G_{day:03d}",
                match_status=status, categoria=categoria,
            )
            session.add(movement)
            session.flush()
            for reference, match_status in matches:
                document = session.query(Document).filter_by(internal_doc_number=reference).one()
                session.add(PaymentMatch(movement_id=movement.id, document_id=document.id, status=match_status, confidence=91))
        session.commit()
        return statement.id


def test_the_dossier_is_the_statement_then_each_payments_paper_in_order(register):
    client, headers, _, _ = register
    photo = upload(client, headers, content=_jpeg())
    scanned = upload(client, headers, source="file", name="f.pdf", content=_pdf(2), mime="application/pdf")
    proposed = upload(client, headers, content=_jpeg())
    statement_id = _statement(
        client,
        [
            (-100.0, "confirmed", [(photo, "confirmed")], "pagament"),  # G_001: ticket page
            (-40.0, "confirmed", [(scanned, "confirmed")], "pagament"),  # G_002: the PDF, whole
            (-12.5, "proposed", [(proposed, "proposed")], "pagament"),  # G_003: a guess → blank page
            (-3.0, "not_applicable", [], "comissio"),  # G_004: a fee, no page
            (-9.0, "unmatched", [], "pagament"),  # G_005: blank page
        ],
    )

    response = client.get(f"{DOSSIER}/{statement_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "dossier-general-2026-03.pdf" in response.headers["content-disposition"]

    pdf = PdfReader(io.BytesIO(response.content))
    assert len(pdf.pages) == 6
    table = pdf.pages[0].extract_text()
    assert "Extracte General" in table and "CODI INTERN FACTURA" in table
    assert all(f"G_00{n}" in table for n in range(1, 6))
    assert photo in table and scanned in table
    assert proposed not in table  # a proposal is not written in
    assert pdf.pages[0].mediabox.width > pdf.pages[0].mediabox.height  # landscape, like the bank's sheet

    ticket = pdf.pages[1].extract_text()
    assert "CODI INTERN" in ticket and "G_001" in ticket and photo in ticket and "-100,00" in ticket
    assert "Factura en PDF, pàgina 1" in pdf.pages[2].extract_text()
    assert "Factura en PDF, pàgina 2" in pdf.pages[3].extract_text()
    blank = pdf.pages[4].extract_text()
    assert "G_003" in blank and "02/01/2026" not in blank and "-12,50" in blank and proposed not in blank
    assert "G_005" in pdf.pages[5].extract_text()
    assert "6 / 6" in pdf.pages[5].extract_text()

    outline = [item.title for item in pdf.outline]
    assert outline[0] == "Extracte"
    assert [title.split(" · ")[0] for title in outline[1:]] == ["G_001", "G_002", "G_003", "G_005"]


def test_a_broken_photo_or_an_empty_statement_still_gives_a_dossier(register):
    client, headers, _, _ = register
    broken = upload(client, headers)  # the shared fixture's bytes are not a real JPEG
    statement_id = _statement(client, [(-5.0, "confirmed", [(broken, "confirmed")], "pagament")])
    pdf = PdfReader(io.BytesIO(client.get(f"{DOSSIER}/{statement_id}", headers=headers).content))
    assert "No s'ha pogut llegir la foto" in pdf.pages[1].extract_text()

    empty = _statement(client, [])
    pdf = PdfReader(io.BytesIO(client.get(f"{DOSSIER}/{empty}", headers=headers).content))
    assert len(pdf.pages) == 1
    assert client.get(f"{DOSSIER}/999", headers=headers).status_code == 404


def test_a_long_statement_runs_over_several_pages(register):
    client, headers, _, _ = register
    statement_id = _statement(client, [(-1.0, "not_applicable", [], "comissio")] * 60)
    pdf = PdfReader(io.BytesIO(client.get(f"{DOSSIER}/{statement_id}", headers=headers).content))
    assert len(pdf.pages) == 3
    text = "".join(page.extract_text() for page in pdf.pages)
    assert all(f"G_{n:03d}" in text for n in range(1, 61))


def test_a_date_range_keeps_only_the_lines_dated_inside_it(register):
    client, headers, _, _ = register
    early = upload(client, headers, content=_jpeg())
    scanned = upload(client, headers, source="file", name="f.pdf", content=_pdf(2), mime="application/pdf")
    statement_id = _statement(
        client,
        [
            (-100.0, "confirmed", [(early, "confirmed")], "pagament"),  # 2 Jan
            (-40.0, "confirmed", [(scanned, "confirmed")], "pagament"),  # 3 Jan
            (-9.0, "unmatched", [], "pagament"),  # 4 Jan
        ],
    )

    response = client.get(f"{DOSSIER}/{statement_id}?date_from=2026-01-03&date_to=2026-01-04", headers=headers)
    assert response.status_code == 200, response.text
    assert "dossier-general-20260103-20260104.pdf" in response.headers["content-disposition"]
    pdf = PdfReader(io.BytesIO(response.content))
    # The statement, the PDF's two pages, and the 4 January blank page.
    assert len(pdf.pages) == 4
    table = pdf.pages[0].extract_text()
    assert "G_002" in table and "G_001" not in table
    assert "Només els moviments" in table

    nothing = client.get(f"{DOSSIER}/{statement_id}?date_from=2026-02-01", headers=headers)
    assert len(PdfReader(io.BytesIO(nothing.content)).pages) == 1
    backwards = client.get(f"{DOSSIER}/{statement_id}?date_from=2026-01-05&date_to=2026-01-01", headers=headers)
    assert backwards.status_code == 422
