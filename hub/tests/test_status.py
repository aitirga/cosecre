"""Estat: the overview counts what the register and the statements say."""

from __future__ import annotations

from datetime import date, timedelta

from conftest import register_admin

from cosecre_hub.models import BankMovement, Document, PaymentMatch, StatementImport


def seed(client) -> None:
    today = date.today()
    with client.app.state.session_factory() as session:
        def statement(compte: str, start: date, end: date) -> StatementImport:
            row = StatementImport(source="caixa_xls", compte=compte, period_from=start, period_to=end)
            session.add(row)
            session.flush()
            return row

        def document(ref: str, amount: float | None, **values) -> Document:
            row = Document(
                internal_doc_number=ref,
                import_value=amount,
                tipus_document=values.pop("tipus_document", "Factura"),
                status=values.pop("status", "needs_validation"),
                sheet_state="synced",
                **values,
            )
            session.add(row)
            session.flush()
            return row

        def movement(statement_row: StatementImport, amount: float, status: str, day: date, **values) -> BankMovement:
            row = BankMovement(
                import_id=statement_row.id,
                fingerprint=f"{statement_row.id}-{amount}-{status}-{day}",
                source="caixa_xls",
                compte=statement_row.compte,
                categoria=values.pop("categoria", "pagament"),
                data=day,
                concepte=values.pop("concepte", "Pagament"),
                import_value=amount,
                match_status=status,
            )
            session.add(row)
            session.flush()
            return row

        # General: January and March, February missing.
        jan = statement("General", date(2026, 1, 2), date(2026, 1, 30))
        mar = statement("General", date(2026, 3, 2), date(2026, 3, 30))

        exact = document("DOC-1", 100.0, num_factura="F1", proveidor="A", pagament="Pagat", pressupost_afectat="General")
        short = document("DOC-2", 40.0, num_factura="F2", proveidor="B", pagament="Pagat", pressupost_afectat="General")
        # Paid, inside a covered period, and no movement justifies it.
        document(
            "DOC-3",
            25.0,
            num_factura="F3",
            proveidor="C",
            pagament="Pagat",
            data_pagament=date(2026, 3, 10),
            pressupost_afectat="General",
        )
        # Waiting to be paid for months.
        document(
            "DOC-4",
            60.0,
            num_factura="F4",
            proveidor="D",
            pagament="Pendent de pagament",
            data_factura=today - timedelta(days=90),
        )
        # A quote is never paid as such.
        document("DOC-5", 999.0, tipus_document="Pressupost", pagament="Pagat")

        ok = movement(jan, -100.0, "confirmed", date(2026, 1, 10))
        off = movement(jan, -50.0, "confirmed", date(2026, 1, 12))
        movement(mar, -30.0, "rejected", date(2026, 3, 5), concepte="Botiga sense factura")
        movement(mar, -12.5, "proposed", date(2026, 3, 8))
        movement(mar, -7.0, "unmatched", date(2026, 3, 9))
        movement(mar, 500.0, "not_applicable", date(2026, 3, 1), categoria="ingres")

        session.add(PaymentMatch(movement_id=ok.id, document_id=exact.id, status="confirmed", confidence=100))
        session.add(PaymentMatch(movement_id=off.id, document_id=short.id, status="confirmed", confidence=100))
        session.commit()


def test_status_overview(hub):
    client, _ = hub
    headers = register_admin(client)
    seed(client)

    response = client.get("/api/v1/status", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    payments = body["payments"]
    assert payments["total"] == {"count": 5, "amount": 199.5}
    assert payments["confirmed"]["count"] == 2
    assert payments["proposed"]["count"] == 1
    assert payments["unmatched"]["count"] == 1
    assert payments["missing"] == {"count": 1, "amount": 30.0}

    general = next(a for a in body["accounts"] if a["compte"] == "General")
    assert general["statements"] == 2
    assert general["gaps"] == [{"from_month": "2026-02", "to_month": "2026-02", "months": 1}]

    assert [m["concepte"] for m in body["missing_invoices"]["items"]] == ["Botiga sense factura"]

    mismatch = body["amount_mismatches"]["items"]
    assert len(mismatch) == 1
    assert mismatch[0]["documents"] == ["DOC-2"]
    assert mismatch[0]["difference"] == 10.0

    paid = body["paid_not_found"]["items"]
    assert [d["num_doc_intern"] for d in paid] == ["DOC-3"]
    assert paid[0]["covered"] is True

    assert [d["num_doc_intern"] for d in body["overdue"]["items"]] == ["DOC-4"]

    assert body["documents"]["payable"] == 4
    assert body["documents"]["justified"] == 2
    assert body["health"]["missing_fields"]["Compte"] == 2


def test_status_needs_a_session(hub):
    client, _ = hub
    assert client.get("/api/v1/status").status_code == 401
