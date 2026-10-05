"""Justifying a statement: candidates, rules, the two models, and confirmation.

The register is seeded with invoices that the real sample statement pays, plus
traps: the same amount from another supplier, a set of invoices that add up to
one transfer, a card charge with no invoice at all.
"""

from __future__ import annotations

from datetime import date

import pytest

from conftest import build_client, register_admin
from fake_sheets import FakeSheets
from statement_fakes import LONG_XLS, SAMPLE_XLS, RoutingProvider, jev_classifier, pick

from cosecre_hub.models import BankMovement, Document, PaymentMatch
from cosecre_hub.services.matching import confidence as conf
from cosecre_hub.services.matching import signals as sig
from cosecre_hub.services.sheets import row_colour

INVOICES = [
    # num, supplier, CIF, date, amount, method
    ("PRF26-00001", "Editorial Teide SA", "A08000000", date(2026, 9, 15), 151.20, "Transferència bancària"),
    ("0397", "Edisama SL", "B60000001", date(2026, 9, 10), 70.00, "Transferència bancària"),
    ("A-12", "Llibreria Calders", "B60000002", date(2026, 9, 12), 70.00, ""),
    ("R-312", "Carlin Catalunya SL", "B64902166", date(2026, 9, 1), 312.40, "Rebut domiciliat"),
    ("R-205", "Carlin Catalunya SL", "B64902166", date(2026, 9, 1), 205.10, "Rebut domiciliat"),
    ("R-98", "Carlin Catalunya SL", "B64902166", date(2026, 9, 3), 98.35, "Rebut domiciliat"),
    ("2026/116574-A", "Hermex Iberica SL", "B60000003", date(2026, 9, 1), 3000.00, ""),
    ("2026/116575-B", "Hermex Iberica SL", "B60000003", date(2026, 9, 2), 1321.50, ""),
    ("INV-778", "OpenAI LLC", "", date(2026, 9, 24), 78.01, "Targeta de dèbit"),
    ("IK-1", "Ikea Iberica SAU", "A28812618", date(2026, 9, 9), 812.30, ""),
    ("LM-9", "Leroy Merlin", "A80000000", date(2026, 9, 8), 812.30, ""),
]


def seed(client) -> dict[str, int]:
    ids = {}
    with client.app.state.session_factory() as session:
        for index, (number, supplier, cif, when, amount, method) in enumerate(INVOICES):
            document = Document(
                internal_doc_number=f"DOC-{index:03d}",
                num_factura=number,
                proveidor=supplier,
                cif_proveidor=cif,
                data_factura=when,
                import_value=amount,
                metode_pagament=method,
                status="needs_validation",
                sheet_state="synced",
            )
            session.add(document)
            session.flush()
            ids[number] = document.id
        session.commit()
    return ids


def ingest(client, headers) -> int:
    response = client.post(
        "/api/v1/statements/upload",
        headers=headers,
        files={"file": ("Moviments_compte.xls", SAMPLE_XLS, "application/vnd.ms-excel")},
        data={"compte": "General"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def movement(client, concept, amount=None) -> BankMovement:
    with client.app.state.session_factory() as session:
        query = session.query(BankMovement).filter(BankMovement.concepte == concept)
        if amount is not None:
            query = query.filter(BankMovement.import_value == amount)
        return query.one()


def detail(client, headers, concept, amount=None):
    found = movement(client, concept, amount)
    return client.get(f"/api/v1/reconciliation/movements/{found.id}", headers=headers).json()


def proposal(body):
    return [m for m in body["matches"] if m["status"] == "proposed"]


def chooser(opts):
    """What a sensible model would say for the cases below."""
    for key, text in opts.items():
        if "Conjunt" in text and "Hermex" in text:
            return key, 0.8
    for word in ("OpenAI", "Ikea"):
        for key, text in opts.items():
            if word in text:
                return key, 0.9
    return "cap", 0.7


@pytest.fixture
def reconciled(tmp_path):
    provider = RoutingProvider(chooser=chooser)
    client, _ = build_client(
        tmp_path,
        provider=provider,
        sheet_service=FakeSheets(),
        classifier=jev_classifier(chooser),
    )
    with client:
        headers = register_admin(client)
        ids = seed(client)
        statement_id = ingest(client, headers)
        run = client.post("/api/v1/reconciliation/runs", headers=headers, json={"import_id": statement_id})
        assert run.status_code == 200, run.text
        yield client, headers, provider, ids, statement_id, run.json()


def test_a_run_goes_over_every_unmatched_payment(reconciled):
    client, headers, _, _, statement_id, run = reconciled
    done = client.get(f"/api/v1/reconciliation/runs/{run['id']}", headers=headers).json()
    # 20 lines: 3 fees/transfers between accounts and 1 income are not payments.
    assert (done["status"], done["total"], done["processed"]) == ("done", 16, 16)

    again = client.post("/api/v1/reconciliation/runs", headers=headers, json={"import_id": statement_id}).json()
    assert again["total"] == 0  # nothing left nobody has looked at

    listing = client.get("/api/v1/reconciliation/statements", headers=headers).json()[0]
    assert listing["payments"] == 16 and listing["unmatched"] == 0
    assert listing["proposed"] == done["proposed"]
    assert sum(listing["bands"].values()) == listing["proposed"]


def test_number_in_the_concept_is_decided_by_the_rules(reconciled):
    client, headers, provider, ids, *_ = reconciled
    body = detail(client, headers, "FAC:PRF26-00001")
    lead = proposal(body)
    assert [m["document"]["num_factura"] for m in lead] == ["PRF26-00001"]
    assert lead[0]["decided_by"] == "rules"
    assert lead[0]["band"] == "high"
    assert lead[0]["signals"]["number"] == 1.0 and lead[0]["signals"]["amount"] == 1.0


def test_same_amount_other_supplier_is_only_an_alternative(reconciled):
    client, headers, *_ = reconciled
    body = detail(client, headers, "FAC:0397")
    assert proposal(body)[0]["document"]["proveidor"] == "Edisama SL"
    alternatives = [m["document"]["proveidor"] for m in body["matches"] if m["status"] == "alternative"]
    assert "Llibreria Calders" in alternatives
    alt = next(m for m in body["matches"] if m["document"]["proveidor"] == "Llibreria Calders")
    assert alt["confidence"] < proposal(body)[0]["confidence"]


def test_direct_debits_pair_by_creditor_cif_and_amount(reconciled):
    client, headers, *_ = reconciled
    for amount, number in [(-312.40, "R-312"), (-205.10, "R-205"), (-98.35, "R-98")]:
        lead = proposal(detail(client, headers, "CARLIN CATALUNYA", amount))
        assert [m["document"]["num_factura"] for m in lead] == [number]
        assert lead[0]["signals"]["cif"] == 1.0


def test_one_transfer_paying_two_invoices_is_proposed_as_a_set(reconciled):
    client, headers, *_ = reconciled
    lead = proposal(detail(client, headers, "FAC:2026/116574"))
    assert sorted(m["document"]["num_factura"] for m in lead) == ["2026/116574-A", "2026/116575-B"]
    # A set never reads as certain.
    assert all(m["confidence"] <= conf.MEDIUM for m in lead)


def test_card_charge_goes_to_the_models(reconciled):
    client, headers, provider, *_ = reconciled
    lead = proposal(detail(client, headers, "OPENAI *CHATGPT S"))
    assert lead[0]["document"]["proveidor"] == "OpenAI LLC"
    assert lead[0]["decided_by"] in {"openai", "jev+openai", "jev"}
    assert lead[0]["ai_trace"]["openai"]["status"] == "ok"


def test_models_agreeing(reconciled):
    client, headers, *_ = reconciled
    lead = proposal(detail(client, headers, "IKEA IBERICA WEB"))
    assert lead[0]["document"]["proveidor"] == "Ikea Iberica SAU"
    assert lead[0]["decided_by"] == "jev+openai"


def test_no_candidate_means_no_model_call(reconciled):
    client, headers, provider, *_ = reconciled
    body = detail(client, headers, "JUNIOR REPORT")
    assert body["match_status"] == "no_match"
    assert body["matches"] == []


def test_confirming_fills_in_the_invoice_and_frees_nobody_else(reconciled):
    client, headers, _, ids, *_ = reconciled
    sheets: FakeSheets = client.app.state.sheet_service
    body = detail(client, headers, "FAC:PRF26-00001")
    confirmed = client.post(
        f"/api/v1/reconciliation/movements/{body['id']}/confirm",
        headers=headers,
        json={"document_refs": [proposal(body)[0]["document"]["num_doc_intern"]]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["match_status"] == "confirmed"

    with client.app.state.session_factory() as session:
        document = session.get(Document, ids["PRF26-00001"])
        assert (document.pagament, document.data_pagament) == ("Pagat", date(2026, 9, 29))
        assert (document.metode_pagament, document.pressupost_afectat) == ("Transferència bancària", "General")
    assert sheets.row_for(document.internal_doc_number)["pagament"] == "Pagat"

    payments = client.get(
        f"/api/v1/reconciliation/documents/{document.internal_doc_number}/payments", headers=headers
    ).json()
    assert [p["status"] for p in payments] == ["confirmed"]

    # The same invoice cannot justify a second movement.
    other = detail(client, headers, "FAC:0397")
    clash = client.post(
        f"/api/v1/reconciliation/movements/{other['id']}/confirm",
        headers=headers,
        json={"document_refs": [document.internal_doc_number]},
    )
    assert clash.status_code == 409


def test_a_justified_invoice_turns_its_row_green_until_undone(reconciled):
    client, headers, _, ids, *_ = reconciled
    sheets: FakeSheets = client.app.state.sheet_service
    body = detail(client, headers, "FAC:PRF26-00001")
    reference = proposal(body)[0]["document"]["num_doc_intern"]
    client.post(
        f"/api/v1/reconciliation/movements/{body['id']}/confirm",
        headers=headers,
        json={"document_refs": [reference]},
    )
    row = sheets.row_for(reference)
    assert row_colour(row) == row_colour({"justificat": True})

    client.post(f"/api/v1/reconciliation/movements/{body['id']}/undo", headers=headers)
    assert sheets.row_for(reference)["justificat"] is False
    assert row_colour(sheets.row_for(reference)) != row_colour({"justificat": True})


def test_not_this_one_puts_the_next_candidate_forward(reconciled):
    client, headers, *_ = reconciled
    body = detail(client, headers, "FAC:0397")
    lead = proposal(body)[0]
    after = client.post(f"/api/v1/reconciliation/matches/{lead['id']}/reject", headers=headers).json()
    assert proposal(after)[0]["document"]["proveidor"] == "Llibreria Calders"

    none = client.post(f"/api/v1/reconciliation/movements/{after['id']}/reject", headers=headers).json()
    assert none["match_status"] == "rejected"
    undone = client.post(f"/api/v1/reconciliation/movements/{after['id']}/undo", headers=headers).json()
    assert undone["match_status"] == "unmatched"


def test_models_disagreeing_caps_the_confidence(tmp_path):
    provider = RoutingProvider(chooser=pick("Ikea", 0.9))
    client, _ = build_client(
        tmp_path, provider=provider, sheet_service=FakeSheets(), classifier=jev_classifier(pick("Leroy", 0.6))
    )
    with client:
        headers = register_admin(client)
        seed(client)
        ingest(client, headers)
        client.post("/api/v1/reconciliation/runs", headers=headers, json={})
        lead = proposal(detail(client, headers, "IKEA IBERICA WEB"))
        # Jev is not sure enough to override: gpt-6-luna's pick stands, flagged.
        assert lead[0]["document"]["proveidor"] == "Ikea Iberica SAU"
        assert lead[0]["decided_by"] == "openai"
        assert lead[0]["confidence"] <= 50 and lead[0]["band"] == "low"


def test_manual_link_from_search(reconciled):
    client, headers, *_ = reconciled
    found = client.get("/api/v1/reconciliation/documents/search?q=Calders", headers=headers).json()
    assert [d["num_factura"] for d in found] == ["A-12"]
    by_amount = client.get("/api/v1/reconciliation/documents/search?q=812,30", headers=headers).json()
    assert {d["num_factura"] for d in by_amount} == {"IK-1", "LM-9"}

    body = detail(client, headers, "JUNIOR REPORT")
    linked = client.post(
        f"/api/v1/reconciliation/movements/{body['id']}/confirm",
        headers=headers,
        json={"document_refs": [found[0]["num_doc_intern"]]},
    ).json()
    assert linked["match_status"] == "confirmed"
    assert linked["matches"][0]["decided_by"] == "person"


def test_a_monthly_charge_keeps_its_invoice_on_the_right_month(tmp_path):
    """Four identical subscription charges, one invoice: only the same-day one keeps it."""
    client, _ = build_client(
        tmp_path,
        provider=RoutingProvider(chooser=pick("OpenAI", 0.95)),
        sheet_service=FakeSheets(),
        classifier=jev_classifier(pick("OpenAI", 0.9)),
    )
    with client:
        headers = register_admin(client)
        with client.app.state.session_factory() as session:
            session.add(
                Document(
                    internal_doc_number="DOC-OPENAI", num_factura="LMWGI18F-0010",
                    proveidor="OpenAI Ireland Limited", data_factura=date(2026, 6, 24),
                    import_value=78.01, status="needs_validation", sheet_state="synced",
                )
            )
            session.commit()
        response = client.post(
            "/api/v1/statements/upload",
            headers=headers,
            files={"file": ("Moviments_compte.xls", LONG_XLS, "application/vnd.ms-excel")},
            data={"compte": "General"},
        )
        client.post("/api/v1/reconciliation/runs", headers=headers, json={"import_id": response.json()["id"]})
        proposed = client.get(
            "/api/v1/reconciliation/movements?status=proposed", headers=headers
        ).json()
        assert [(m["concepte"], m["data"]) for m in proposed] == [("OPENAI *CHATGPT S", "2026-06-24")]
        later = [
            m for m in client.get("/api/v1/reconciliation/movements?status=no_match", headers=headers).json()
            if m["concepte"] == "OPENAI *CHATGPT S"
        ]
        assert len(later) == 5  # April (61,11 €), May, July, August, September


# ── Pure pieces ──────────────────────────────────────────────────────────────


def test_confidence_bands():
    strong = {"amount": 1, "number": 1, "name": 1, "date": 1, "consistency": 1}
    both = conf.ModelView(openai=0.95, jev=0.9)
    assert conf.combined(strong, both) >= conf.HIGH
    assert conf.combined(strong, conf.ModelView(rules_only=True)) == 95  # capped without both models
    assert conf.combined(strong, conf.ModelView(openai=0.95, disagree=True)) <= 50
    loose = {"amount": 0.0, "name": 1, "date": 1}
    assert conf.combined(loose, both) <= conf.MEDIUM
    assert conf.band(90) == "high" and conf.band(70) == "medium" and conf.band(20) == "low"
    assert conf.band(None) == "none"


def test_number_signal_handles_truncation_and_noise():
    assert sig.number_signal("PRF26-01609", "", "PRF26-01609") == 1.0
    assert sig.number_signal("TRA2026A06-0", "", "TRA2026A06-012") == 1.0  # cut by the bank
    assert sig.number_signal("140927 CUSTOM", "", "140927") == 1.0
    assert sig.number_signal("0397", "", "397") == 1.0
    assert sig.number_signal("0397", "", "1397") == 0.0


def test_name_signal_tolerates_case_forms_and_truncation():
    assert sig.name_signal("NOVES DISTR.CATAL", "Noves Distribucions Catalanes SL") >= 0.9
    assert sig.name_signal("EDITORIAL TEIDE", "Editorial Teide SA") == 1.0
    assert sig.name_signal("THOMANN", "Ikea Iberica SAU") == 0.0
