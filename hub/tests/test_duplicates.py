from __future__ import annotations

from datetime import date
from pathlib import Path

from test_documents import RECORDS, register, upload  # noqa: F401  (fixture)

from cosecre_hub.models import BankMovement, Document, PaymentMatch, StatementImport

DUPLICATES = "/api/v1/documents/duplicates"


def _sync(client, headers):
    return client.post(f"{RECORDS}/sync", headers=headers).json()


def test_an_exact_duplicate_is_removed_on_its_own_and_listed(register):
    client, headers, sheet, _ = register
    first = upload(client, headers)
    second = upload(client, headers, source="file", name="same.pdf", content=b"%PDF-1.7", mime="application/pdf")
    assert len(sheet.rows) == 2

    _sync(client, headers)

    references = {d["num_doc_intern"] for d in client.get(RECORDS, headers=headers).json()}
    assert references == {first}  # the older one stays; the photo/PDF origin does not matter
    assert [sheet_row.get("num_doc_intern") for sheet_row in sheet.rows.values()] == [first]
    removed = client.get(DUPLICATES, headers=headers).json()
    assert [(r["reference"], r["kept_reference"], r["kept_exists"]) for r in removed] == [(second, first, True)]
    assert removed[0]["num_factura"] == "F-2026/001" and removed[0]["import_value"] == 100.0

    # The original is not thrown away with the entry.
    with client.app.state.session_factory() as session:
        from cosecre_hub.models import DuplicateRemoval

        log = session.query(DuplicateRemoval).one()
        assert log.stored_path and Path(log.stored_path).exists()
    assert len(sheet.drive) == 2


def test_entries_that_differ_in_anything_are_left_for_a_person(register):
    client, headers, _, _ = register
    first = upload(client, headers)
    second = upload(client, headers)
    assert client.patch(f"{RECORDS}/{second}", headers=headers, json={"descripcio": "Una altra cosa"}).status_code == 200

    _sync(client, headers)

    assert {d["num_doc_intern"] for d in client.get(RECORDS, headers=headers).json()} == {first, second}
    assert client.get(DUPLICATES, headers=headers).json() == []


def test_the_validated_copy_stays_and_payment_links_follow_it(register):
    client, headers, _, _ = register
    first = upload(client, headers)
    second = upload(client, headers)
    assert client.post(f"{RECORDS}/{second}/validate", headers=headers).status_code == 200

    with client.app.state.session_factory() as session:
        duplicate = session.query(Document).filter_by(internal_doc_number=first).one()
        statement = StatementImport(source="caixa_xls", compte="General")
        session.add(statement)
        session.flush()
        movement = BankMovement(
            import_id=statement.id, fingerprint="m1", source="caixa_xls", compte="General",
            data=date(2026, 2, 1), import_value=-100.0, match_status="proposed",
        )
        session.add(movement)
        session.flush()
        session.add(PaymentMatch(movement_id=movement.id, document_id=duplicate.id, status="proposed"))
        session.commit()

    _sync(client, headers)

    assert {d["num_doc_intern"] for d in client.get(RECORDS, headers=headers).json()} == {second}
    with client.app.state.session_factory() as session:
        kept = session.query(Document).filter_by(internal_doc_number=second).one()
        match = session.query(PaymentMatch).one()
        assert match.document_id == kept.id and match.status == "proposed"
