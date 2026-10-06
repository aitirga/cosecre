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


def test_the_dossier_is_the_statement_then_only_the_original_documents(register):
    client, headers, _, _ = register
    photo = upload(client, headers, content=_jpeg())
    scanned = upload(client, headers, source="file", name="f.pdf", content=_pdf(2), mime="application/pdf")
    proposed = upload(client, headers, source="file", name="p.pdf", content=_pdf(1), mime="application/pdf")
    statement_id = _statement(
        client,
        [
            (-100.0, "confirmed", [(photo, "confirmed")], "pagament"),  # G_001: a photo → no page
            (-40.0, "confirmed", [(scanned, "confirmed")], "pagament"),  # G_002: the PDF, with its code
            (-12.5, "proposed", [(proposed, "proposed")], "pagament"),  # G_003: a guess → nothing
            (-3.0, "not_applicable", [], "comissio"),  # G_004: a fee
            (-9.0, "unmatched", [], "pagament"),  # G_005: no invoice → no blank page
        ],
    )

    response = client.get(f"{DOSSIER}/{statement_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "dossier-general-2026-03.pdf" in response.headers["content-disposition"]

    pdf = PdfReader(io.BytesIO(response.content))
    assert len(pdf.pages) == 3  # the statement and the PDF's two pages
    table = pdf.pages[0].extract_text()
    assert "Extracte General" in table and "CODI" in table and "INTERN FACTURA" not in table
    assert all(f"G_00{n}" in table for n in range(1, 6))
    assert table.count("G_001") == 1  # the code is written once, not twice
    assert photo not in table and scanned not in table  # the register's own codes are not the code
    assert "F-2026/001" in table  # the invoice number, filled in
    assert pdf.pages[0].mediabox.width > pdf.pages[0].mediabox.height  # landscape, like the bank's sheet
    assert "1 / 3" in table

    for number, page in enumerate(pdf.pages[1:], start=1):
        text = page.extract_text()
        assert f"Factura en PDF, pàgina {number}" in text
        assert text.count("G_002") == 1  # the line's code, on top of each page
        assert abs(float(page.mediabox.width) - 595.27) < 1  # the original's own size

    outline = [item.title for item in pdf.outline]
    assert outline[0] == "Extracte"
    assert [title.split(" · ")[0] for title in outline[1:]] == ["G_002"]


def test_the_caixeta_reads_in_its_code_order_and_the_rest_by_date(register):
    client, headers, _, _ = register
    with client.app.state.session_factory() as session:
        statement = StatementImport(source="caixeta_sheet", compte="Caixeta", file_name="caixeta")
        session.add(statement)
        session.flush()
        # Out of date order on purpose: the caixeta's sheet numbers them its own way.
        for number, day in ((3, 1), (1, 9), (12, 2), (2, 5)):
            session.add(BankMovement(
                import_id=statement.id, fingerprint=f"c{number}", source="caixeta_sheet", compte="Caixeta",
                data=date(2026, 1, day), concepte=f"Caixa {number}", import_value=-1.0,
                codi=f"Cix_{number:03d}", external_ref=f"Cix_{number:03d}", categoria="pagament",
            ))
        session.commit()
        statement_id = statement.id
    text = PdfReader(io.BytesIO(client.get(f"{DOSSIER}/{statement_id}", headers=headers).content)).pages[0].extract_text()
    positions = [text.index(f"Cix_{n:03d}") for n in (1, 2, 3, 12)]
    assert positions == sorted(positions)


def test_an_unreadable_original_or_an_empty_statement_still_gives_a_dossier(register):
    client, headers, _, _ = register
    broken = upload(client, headers, source="file", name="b.pdf", content=b"%PDF-1.4 broken", mime="application/pdf")
    statement_id = _statement(client, [(-5.0, "confirmed", [(broken, "confirmed")], "pagament")])
    pdf = PdfReader(io.BytesIO(client.get(f"{DOSSIER}/{statement_id}", headers=headers).content))
    assert len(pdf.pages) == 1

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
    # The statement and the PDF's two pages; no blank page for 4 January.
    assert len(pdf.pages) == 3
    table = pdf.pages[0].extract_text()
    assert "G_002" in table and "G_001" not in table
    assert "Només els moviments" in table

    nothing = client.get(f"{DOSSIER}/{statement_id}?date_from=2026-02-01", headers=headers)
    assert len(PdfReader(io.BytesIO(nothing.content)).pages) == 1
    backwards = client.get(f"{DOSSIER}/{statement_id}?date_from=2026-01-05&date_to=2026-01-01", headers=headers)
    assert backwards.status_code == 422
