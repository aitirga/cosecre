from __future__ import annotations

from datetime import date

from test_documents import RECORDS, register, upload  # noqa: F401  (fixture)

from cosecre_hub.models import BankMovement, Document, PaymentMatch, StatementImport


def test_a_confirmed_payment_shows_on_both_sides(register):
    client, headers, _, _ = register
    paid = upload(client, headers)
    unpaid = upload(client, headers, source="file", name="b.pdf", content=b"%PDF-1.7", mime="application/pdf")
    client.patch(f"{RECORDS}/{unpaid}", headers=headers, json={"num_factura": "ALTRA-1"})
    with client.app.state.session_factory() as session:
        document = session.query(Document).filter_by(internal_doc_number=paid).one()
        statement = StatementImport(source="caixa_xls", compte="General")
        session.add(statement)
        session.flush()
        movement = BankMovement(
            import_id=statement.id, fingerprint="m1", source="caixa_xls", compte="General",
            data=date(2026, 2, 1), import_value=-100.0, match_status="confirmed",
        )
        session.add(movement)
        session.flush()
        session.add(PaymentMatch(movement_id=movement.id, document_id=document.id, status="confirmed"))
        session.commit()
        statement_id = statement.id

    records = {d["num_doc_intern"]: d for d in client.get(RECORDS, headers=headers).json()}
    assert records[paid]["matched_movements"] == 1
    assert [(p["compte"], p["import_value"]) for p in records[paid]["paid_by"]] == [("General", -100.0)]
    assert records[unpaid]["matched_movements"] == 0 and records[unpaid]["paid_by"] == []
    assert client.get(f"{RECORDS}/{paid}", headers=headers).json()["matched_movements"] == 1

    lines = client.get(f"/api/v1/statements/imports/{statement_id}/movements", headers=headers).json()
    assert [(d["num_doc_intern"], d["num_factura"]) for d in lines[0]["matched"]] == [(paid, "F-2026/001")]
