"""Esfer@ export plans: preflight, payload and the runner's journal.

Synthetic IDs throughout. The valid invoice mirrors the shape that saved and
read back in formació on 2026-10-12: one line with its cost centre, zero VAT
and withholding, one transfer due date.
"""

from datetime import date
import pytest
from conftest import register_admin

from cosecre_hub.api.sfera import preflight, routes
from cosecre_hub.api.sfera.schemas import ExportContext, InvoiceIn

URL = "/api/v1/sfera/export-plans"
TODAY = date(2026, 10, 12)
CONTEXT = {
    "environment": "training", "centre_code": "00000001", "remote_centre_id": 900,
    "remote_budget_id": 901, "financial_year": 2026, "vat_settlement": False,
}


def invoice(**changes):
    body = {
        "source_ref": "DOC-2026-0001",
        "supplier_remote_id": 1001,
        "document_number": "CSC-POC-abc123-M001",
        "internal_number": "POC-M001",
        "document_date": "2026-10-10",
        "accounting_date": "2026-10-12",
        "description": "COSECRE POC · material d'oficina",
        "observations": "Dades fictícies.",
        "total": "30.00",
        "lines": [{"partida_remote_id": 2001, "cost_centre_remote_id": 7001, "base": "30.00", "vat_amount": "0.00"}],
        "due_dates": [{"date": "2026-11-12", "amount": "30.00", "payment_type": "TR", "bank_account_remote_id": 7002}],
    }
    body.update(changes)
    return body


def codes(context=CONTEXT, **changes):
    problems = preflight.check_invoice(ExportContext(**context), InvoiceIn(**invoice(**changes)), today=TODAY)
    return {p.code for p in problems if p.blocking}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(routes, "_today", lambda: TODAY)


# --- Preflight: one rule per lesson -------------------------------------------------

def test_valid_invoice_has_no_blocking_problem():
    assert codes() == set()


def test_line_without_cost_centre_is_blocked():
    # Without it Esfer@ fails server-side and the PUT surfaces as a generic 405.
    assert "cost_centre_missing" in codes(lines=[{"partida_remote_id": 2001, "base": "30.00", "vat_amount": "0"}])


@pytest.mark.parametrize("field,value", [
    ("document_number", "COSECRE-POC-abcdefgh-M001"),  # 25: validate passes, desa fails
    ("internal_number", "X" * 21),
    ("description", "D" * 101),
    ("observations", "O" * 501),
])
def test_values_longer_than_esfera_columns_are_blocked(field, value):
    assert "too_long" in codes(**{field: value})


def test_twenty_character_number_is_accepted():
    assert codes(document_number="N" * 20) == set()


def test_vat_must_be_stated_and_only_zero_is_verified():
    assert "vat_unknown" in codes(lines=[{"partida_remote_id": 2001, "cost_centre_remote_id": 1, "base": "30.00"}])
    assert "vat_unverified" in codes(total="36.30", lines=[{"partida_remote_id": 2001, "cost_centre_remote_id": 1, "base": "30.00", "vat_amount": "6.30"}],
                                     due_dates=[{"date": "2026-11-12", "amount": "36.30", "payment_type": "TR", "bank_account_remote_id": 1}])


def test_totals_must_add_up_exactly():
    assert "lines_total_mismatch" in codes(total="30.01", due_dates=[{"date": "2026-11-12", "amount": "30.01", "payment_type": "TR", "bank_account_remote_id": 1}])
    assert "due_total_mismatch" in codes(due_dates=[{"date": "2026-11-12", "amount": "29.99", "payment_type": "TR", "bank_account_remote_id": 1}])
    assert "precision" in codes(total="30.001", lines=[{"partida_remote_id": 2001, "cost_centre_remote_id": 1, "base": "30.001", "vat_amount": "0"}],
                                due_dates=[{"date": "2026-11-12", "amount": "30.001", "payment_type": "TR", "bank_account_remote_id": 1}])


def test_split_lines_and_due_dates_are_fine_when_they_add_up():
    assert codes(
        lines=[{"partida_remote_id": 2001, "cost_centre_remote_id": 1, "base": "10.10", "vat_amount": "0"},
               {"partida_remote_id": 2002, "cost_centre_remote_id": 1, "base": "19.90", "vat_amount": "0"}],
        due_dates=[{"date": "2026-11-12", "amount": "15.00", "payment_type": "TR", "bank_account_remote_id": 1},
                   {"date": "2026-12-12", "amount": "15.00", "payment_type": "R", "bank_account_remote_id": 1}],
    ) == set()


def test_unverified_payment_types_and_missing_bank_are_blocked():
    assert "payment_type_unverified" in codes(due_dates=[{"date": "2026-11-12", "amount": "30.00", "payment_type": "T", "bank_account_remote_id": 1}])
    assert "bank_account_missing" in codes(due_dates=[{"date": "2026-11-12", "amount": "30.00", "payment_type": "TR"}])


def test_context_outside_the_verified_envelope_is_blocked():
    assert "environment_unverified" in codes({**CONTEXT, "environment": "production"})
    assert "vat_settlement_unverified" in codes({**CONTEXT, "vat_settlement": True})
    assert "year_mismatch" in codes(accounting_date="2025-12-31")
    assert "future_date" in codes(accounting_date="2026-10-13")


def test_negative_amounts_are_not_invoices():
    assert "invalid_amount" in codes(total="-30.00", lines=[{"partida_remote_id": 2001, "cost_centre_remote_id": 1, "base": "-30.00", "vat_amount": "0"}],
                                     due_dates=[{"date": "2026-11-12", "amount": "-30.00", "payment_type": "TR", "bank_account_remote_id": 1}])


def test_payload_has_the_shape_that_saved_in_formacio():
    payload = preflight.esfera_payload(ExportContext(**CONTEXT), InvoiceIn(**invoice()))
    assert payload["dataDocument"] == "10/10/2026" and payload["dataRegistre"] == "12/10/2026"
    assert payload["pressupost"] == {"id": 901, "any": 2026, "idCentre": 900}
    assert payload["proveidor"] == {"id": 1001}
    assert payload["importTotalFinal"] == payload["importPendent"] == 30.0
    assert payload["liquidat"] == "F" and payload["tipusDocument"] == "F" and payload["despesaSimplificada"] == "F"
    line = payload["partidasFactura"][0]
    assert line["partidaPressupost"] == {"id": 2001} and line["centreCost"] == {"id": 7001}
    assert line["importIrpf"] == "0.00" and line["importBaseProrrata"] == 30.0
    due = payload["vencimentsFactura"][0]
    assert due == {"anulat": "F", "liquidat": "F", "dataVenciment": "12/11/2026", "import_": 30.0, "tipusPagament": "TR",
                   "numeroXec": None, "compteBancari": {"id": 7002}, "descripcio": "Pagament de la factura CSC-POC-abc123-M001"}


def test_plan_hash_changes_with_any_material_change():
    context = ExportContext(**CONTEXT)
    base = preflight.plan_hash(context, [InvoiceIn(**invoice())])
    assert base == preflight.plan_hash(context, [InvoiceIn(**invoice())])
    assert base != preflight.plan_hash(context, [InvoiceIn(**invoice(total="31.00"))])
    assert base != preflight.plan_hash(context, [InvoiceIn(**invoice(description="Una altra"))])
    assert base != preflight.plan_hash(ExportContext(**{**CONTEXT, "remote_budget_id": 902}), [InvoiceIn(**invoice())])


# --- API: plan → approve → claim → report → reconcile --------------------------------

def make_plan(client, auth, *invoices, context=CONTEXT):
    response = client.post(URL, headers=auth, json={"context": context, "invoices": list(invoices) or [invoice()]})
    assert response.status_code == 201, response.text
    return response.json()


def approve(client, auth, plan):
    response = client.post(f"{URL}/{plan['id']}/approve", headers=auth, json={"plan_hash": plan["plan_hash"]})
    assert response.status_code == 200, response.text
    return response.json()


def claim(client, auth, plan, item=0):
    return client.post(f"{URL}/{plan['id']}/items/{plan['items'][item]['id']}/claim", headers=auth)


def readback(**changes):
    return {"supplier_remote_id": 1001, "total": "30.00", "remote_budget_id": 901, "document_number": "CSC-POC-abc123-M001", **changes}


def report(client, auth, plan, attempt_id, item=0, **body):
    return client.post(f"{URL}/{plan['id']}/items/{plan['items'][item]['id']}/result", headers=auth, json={"attempt_id": attempt_id, **body})


def test_capabilities_say_what_was_verified(hub):
    client, _ = hub
    caps = client.get("/api/v1/sfera/capabilities", headers=register_admin(client)).json()
    assert {(c["environment"], c["status"]) for c in caps} == {("training", "verified"), ("production", "disabled")}


def test_routes_need_a_staff_session(hub):
    client, _ = hub
    assert client.get(URL).status_code == 401


def test_happy_path_records_attempt_mapping_and_blocks_reexport(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = make_plan(client, auth)
    assert plan["state"] == "ready" and plan["items"][0]["problems"] == []
    assert plan["items"][0]["payload"]["partidasFactura"][0]["centreCost"] == {"id": 7001}
    plan = approve(client, auth, plan)
    assert plan["state"] == "approved"

    claimed = claim(client, auth, plan).json()
    assert claimed["payload"]["identificadorDocProveidor"] == "CSC-POC-abc123-M001"
    # The attempt exists before the runner calls the portal.
    assert client.get(f"{URL}/{plan['id']}", headers=auth).json()["items"][0]["attempts"][0]["outcome"] == "pending"

    done = report(client, auth, plan, claimed["attempt_id"], outcome="succeeded", remote_id=9001, remote_code="FC-SYNTH-0001", readback=readback(), http_status=200).json()
    assert done["state"] == "succeeded"
    assert done["items"][0]["remote_code"] == "FC-SYNTH-0001"

    again = make_plan(client, auth, invoice(source_ref="DOC-2026-0099"))
    assert again["state"] == "blocked"
    assert "already_exported" in {p["code"] for p in again["items"][0]["problems"]}


def test_same_number_from_another_supplier_is_not_a_duplicate(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = make_plan(client, auth, invoice(), invoice(source_ref="DOC-2", supplier_remote_id=1002))
    assert plan["state"] == "ready"
    dup = make_plan(client, auth, invoice(source_ref="A"), invoice(source_ref="B", document_number=" csc-poc-ABC123-m001 "))
    assert {p["code"] for p in dup["items"][1]["problems"]} >= {"duplicate_in_plan"}


def test_an_item_cannot_sit_in_two_active_plans(hub):
    client, _ = hub
    auth = register_admin(client)
    make_plan(client, auth)
    second = make_plan(client, auth)
    assert "in_other_plan" in {p["code"] for p in second["items"][0]["problems"]}
    # Once the first is cancelled, the source is free again.
    first_id = client.get(URL, headers=auth).json()[-1]["id"]
    client.post(f"{URL}/{first_id}/cancel", headers=auth)
    assert make_plan(client, auth)["state"] == "ready"


def test_blocked_plans_and_stale_hashes_cannot_be_approved(hub):
    client, _ = hub
    auth = register_admin(client)
    blocked = make_plan(client, auth, invoice(lines=[{"partida_remote_id": 2001, "base": "30.00", "vat_amount": "0"}]))
    assert blocked["state"] == "blocked"
    assert client.post(f"{URL}/{blocked['id']}/approve", headers=auth, json={"plan_hash": blocked["plan_hash"]}).status_code == 409
    ready = make_plan(client, auth, invoice(source_ref="DOC-2", document_number="N2"))
    assert client.post(f"{URL}/{ready['id']}/approve", headers=auth, json={"plan_hash": "0" * 64}).status_code == 409
    assert claim(client, auth, ready).status_code == 409  # not approved


def test_unknown_local_links_block(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = make_plan(client, auth, invoice(document_id=999999, movement_id=999999))
    assert {"not_found"} <= {p["code"] for p in plan["items"][0]["problems"]}


def test_failure_without_proof_of_no_effect_is_uncertain_and_blocks_the_centre(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth, invoice(), invoice(source_ref="DOC-2", document_number="N2")))
    attempt = claim(client, auth, plan).json()["attempt_id"]
    out = report(client, auth, plan, attempt, outcome="failed", http_status=405, error="HTTP method PUT is not supported").json()
    assert out["items"][0]["state"] == "uncertain" and out["state"] == "uncertain"
    # Nothing else is written in this centre until the uncertain one is settled.
    assert claim(client, auth, plan, item=1).status_code == 409
    item = plan["items"][0]["id"]
    out = client.post(f"{URL}/{plan['id']}/items/{item}/reconcile", headers=auth, json={"found": False}).json()
    assert out["items"][0]["state"] == "failed"
    # A failed item may be claimed again; the other one too.
    assert claim(client, auth, plan, item=1).status_code == 200


def test_confirmed_failure_can_be_retried(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth))
    first = claim(client, auth, plan).json()["attempt_id"]
    out = report(client, auth, plan, first, outcome="failed", no_effect_confirmed=True, http_status=405).json()
    assert out["items"][0]["state"] == "failed"
    second = claim(client, auth, plan).json()["attempt_id"]
    assert second != first
    out = report(client, auth, plan, second, outcome="succeeded", remote_id=1, readback=readback()).json()
    assert out["state"] == "succeeded" and len(out["items"][0]["attempts"]) == 2


def test_stale_attempt_cannot_report(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth))
    attempt = claim(client, auth, plan).json()["attempt_id"]
    assert report(client, auth, plan, attempt + 1000, outcome="succeeded", remote_id=1, readback=readback()).status_code == 409
    item = plan["items"][0]["id"]
    client.post(f"{URL}/{plan['id']}/items/{item}/recover", headers=auth)
    # The runner that vanished comes back: its attempt is no longer current.
    assert report(client, auth, plan, attempt, outcome="succeeded", remote_id=1, readback=readback()).status_code == 409


def test_double_claim_is_refused(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth))
    assert claim(client, auth, plan).status_code == 200
    assert claim(client, auth, plan).status_code == 409


def test_readback_mismatch_is_a_conflict_not_a_success(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth))
    attempt = claim(client, auth, plan).json()["attempt_id"]
    out = report(client, auth, plan, attempt, outcome="succeeded", remote_id=7, readback=readback(total="31.00")).json()
    assert out["items"][0]["state"] == "conflict" and "total" in out["items"][0]["attempts"][0]["error"]
    item = plan["items"][0]["id"]
    # Reconciling with the same mismatch keeps the conflict; a matching read settles it.
    assert client.post(f"{URL}/{plan['id']}/items/{item}/reconcile", headers=auth, json={"found": True, "remote_id": 7, "readback": readback(total="31.00")}).status_code == 409
    out = client.post(f"{URL}/{plan['id']}/items/{item}/reconcile", headers=auth, json={"found": True, "remote_id": 7, "remote_code": "FC1", "readback": readback()}).json()
    assert out["items"][0]["state"] == "reconciled" and out["state"] == "succeeded"


def test_runner_lost_mid_write_is_recovered_as_uncertain_then_reconciled(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth))
    claim(client, auth, plan)
    item = plan["items"][0]["id"]
    out = client.post(f"{URL}/{plan['id']}/items/{item}/recover", headers=auth).json()
    assert out["items"][0]["state"] == "uncertain" and out["items"][0]["attempts"][0]["outcome"] == "abandoned"
    out = client.post(f"{URL}/{plan['id']}/items/{item}/reconcile", headers=auth, json={"found": True, "remote_id": 55, "readback": readback()}).json()
    assert out["items"][0]["state"] == "reconciled"


def test_cancel_keeps_confirmed_items(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth, invoice(), invoice(source_ref="DOC-2", document_number="N2")))
    attempt = claim(client, auth, plan).json()["attempt_id"]
    report(client, auth, plan, attempt, outcome="succeeded", remote_id=1, readback=readback())
    out = client.post(f"{URL}/{plan['id']}/cancel", headers=auth).json()
    assert [i["state"] for i in out["items"]] == ["succeeded", "cancelled"] and out["state"] == "finished"


def test_mappings_are_per_environment_and_centre(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth))
    attempt = claim(client, auth, plan).json()["attempt_id"]
    report(client, auth, plan, attempt, outcome="succeeded", remote_id=1, readback=readback())
    other_centre = make_plan(client, auth, invoice(source_ref="DOC-X"), context={**CONTEXT, "centre_code": "00000002"})
    assert "already_exported" not in {p["code"] for p in other_centre["items"][0]["problems"]}


def test_extra_fields_and_bad_context_are_rejected(hub):
    client, _ = hub
    auth = register_admin(client)
    assert client.post(URL, headers=auth, json={"context": {**CONTEXT, "token": "x"}, "invoices": [invoice()]}).status_code == 422
    assert client.post(URL, headers=auth, json={"context": {**CONTEXT, "centre_code": "123"}, "invoices": [invoice()]}).status_code == 422
    assert client.post(URL, headers=auth, json={"context": CONTEXT, "invoices": []}).status_code == 422


# --- Dry run, deletion and removing items ----------------------------------------------

def test_preflight_endpoint_checks_without_keeping_anything(hub):
    client, _ = hub
    auth = register_admin(client)
    body = {"context": CONTEXT, "invoices": [invoice(), invoice(source_ref="B", lines=[{"partida_remote_id": 2001, "base": "30.00", "vat_amount": "0"}])]}
    out = client.post("/api/v1/sfera/preflight", headers=auth, json=body).json()
    assert [o["state"] for o in out] == ["ready", "blocked"]
    assert out[0]["payload"]["partidasFactura"][0]["centreCost"] == {"id": 7001}
    assert client.get(URL, headers=auth).json() == []
    # It also sees the journal: an exported invoice is reported as such.
    plan = approve(client, auth, make_plan(client, auth))
    attempt = claim(client, auth, plan).json()["attempt_id"]
    report(client, auth, plan, attempt, outcome="succeeded", remote_id=1, readback=readback())
    again = client.post("/api/v1/sfera/preflight", headers=auth, json={"context": CONTEXT, "invoices": [invoice(source_ref="Z")]}).json()
    assert "already_exported" in {p["code"] for p in again[0]["problems"]}


def test_untouched_plan_can_be_deleted_and_frees_its_sources(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth))
    assert client.delete(f"{URL}/{plan['id']}", headers=auth).status_code == 204
    assert client.get(f"{URL}/{plan['id']}", headers=auth).status_code == 404
    assert make_plan(client, auth)["state"] == "ready"


def test_plan_with_attempts_keeps_its_journal(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth))
    attempt = claim(client, auth, plan).json()["attempt_id"]
    report(client, auth, plan, attempt, outcome="failed", no_effect_confirmed=True)
    assert client.delete(f"{URL}/{plan['id']}", headers=auth).status_code == 409
    assert client.post(f"{URL}/{plan['id']}/cancel", headers=auth).json()["state"] == "cancelled"
    assert client.delete(f"{URL}/{plan['id']}", headers=auth).status_code == 409


def test_removing_an_item_rehashes_and_rechecks_the_plan(hub):
    client, _ = hub
    auth = register_admin(client)
    plan = make_plan(client, auth, invoice(source_ref="A"), invoice(source_ref="B"))  # same supplier + number
    assert [i["state"] for i in plan["items"]] == ["ready", "blocked"]
    out = client.delete(f"{URL}/{plan['id']}/items/{plan['items'][1]['id']}", headers=auth).json()
    assert len(out["items"]) == 1 and out["state"] == "ready" and out["plan_hash"] != plan["plan_hash"]
    # The old hash no longer approves it; the new one does.
    assert client.post(f"{URL}/{plan['id']}/approve", headers=auth, json={"plan_hash": plan["plan_hash"]}).status_code == 409
    assert client.post(f"{URL}/{plan['id']}/approve", headers=auth, json={"plan_hash": out["plan_hash"]}).status_code == 200
    # Approved plans and last items are not edited.
    assert client.delete(f"{URL}/{plan['id']}/items/{out['items'][0]['id']}", headers=auth).status_code == 409


def test_timestamps_carry_their_time_zone(hub):
    # SQLite drops the zone; without it a browser reads UTC as local time.
    client, _ = hub
    auth = register_admin(client)
    plan = approve(client, auth, make_plan(client, auth))
    claim(client, auth, plan)
    out = client.get(f"{URL}/{plan['id']}", headers=auth).json()
    stamps = [out["created_at"], out["approved_at"], out["items"][0]["attempts"][0]["started_at"], client.get(URL, headers=auth).json()[0]["created_at"]]
    assert all(s.endswith(("Z", "+00:00")) for s in stamps), stamps
