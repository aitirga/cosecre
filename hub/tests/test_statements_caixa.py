"""Bringing CaixaBank statements in: the parser, the format check, the dropzone."""

from __future__ import annotations

from datetime import date

from conftest import build_client, register_admin
from statement_fakes import GENERAL_IBAN, LONG_ROWS, LONG_XLS, SAMPLE_XLS, RoutingProvider

from cosecre_hub.models import PaymentMatch
from cosecre_hub.services.statements import caixa_xls


def by_concept(statement, concept):
    return [m for m in statement.movements if m.concepte == concept]


def test_parser_reads_the_sample_statement():
    statement = caixa_xls.parse(SAMPLE_XLS, "Moviments_compte.xls")

    assert statement.account_iban == GENERAL_IBAN
    assert len(statement.movements) == 20
    assert statement.period == (date(2026, 9, 10), date(2026, 10, 1))

    teide = by_concept(statement, "FAC:PRF26-00001")[0]
    assert (teide.tipus, teide.categoria, teide.num_factura_hint) == (
        "Transferència bancària", "pagament", "PRF26-00001"
    )
    assert teide.mes_dades == "EDITORIAL TEIDE" and teide.import_value == -151.20

    carlin = by_concept(statement, "CARLIN CATALUNYA")
    assert [m.import_value for m in carlin] == [-312.40, -205.10, -98.35]
    assert all(m.tipus == "Rebut domiciliat" and m.cif_hint == "B64902166" for m in carlin)

    assert by_concept(statement, "OPENAI *CHATGPT S")[0].tipus == "Targeta de dèbit"
    assert by_concept(statement, "MANTENIMENT")[0].categoria == "comissio"
    assert by_concept(statement, "CARREGA.TARG.PREPAG")[0].categoria == "traspas_intern"
    assert by_concept(statement, "CONSOR DEDUCAC.BA")[0].categoria == "ingres"
    assert by_concept(statement, "SIEMENS FINANCIAL")[0].tipus == "Rebut domiciliat"


def test_parser_keeps_whole_references_and_spots_free_text_transfers():
    statement = caixa_xls.parse(LONG_XLS, "Moviments_compte.xls")
    assert len(statement.movements) == len(LONG_ROWS)

    assert by_concept(statement, "Fac: ES 139/2026")[0].num_factura_hint == "ES 139/2026"
    assert by_concept(statement, "Fac: CC 4034")[0].num_factura_hint == "CC 4034"
    # "Més dades" names who was paid: a transfer, not a card purchase.
    assert by_concept(statement, "Reserva P2026076")[0].tipus == "Transferència bancària"
    assert by_concept(statement, "WWW.AMAZON")[0].tipus == "Targeta de dèbit"


def test_fingerprints_are_stable_and_distinct():
    first = caixa_xls.parse(SAMPLE_XLS)
    again = caixa_xls.parse(SAMPLE_XLS)
    prints = [m.fingerprint for m in first.movements]
    assert prints == [m.fingerprint for m in again.movements]
    # Three CARLIN debits on one day are still three movements.
    assert len(set(prints)) == len(prints)


def upload(client, headers, content, compte=None, name="Moviments_compte.xls"):
    data = {"compte": compte} if compte else {}
    return client.post(
        "/api/v1/statements/upload",
        headers=headers,
        files={"file": (name, content, "application/vnd.ms-excel")},
        data=data,
    )


def test_unknown_account_is_asked_once_and_remembered(tmp_path):
    client, _ = build_client(tmp_path, provider=RoutingProvider())
    with client:
        headers = register_admin(client)

        asked = upload(client, headers, SAMPLE_XLS)
        assert asked.status_code == 409
        assert asked.json()["code"] == "needs_account"
        assert asked.json()["iban"] == GENERAL_IBAN

        stored = upload(client, headers, SAMPLE_XLS, compte="General")
        assert stored.status_code == 200, stored.text
        body = stored.json()
        assert (body["compte"], body["rows_total"], body["rows_new"]) == ("General", 20, 20)

        settings = client.get("/api/v1/documents/settings", headers=headers).json()
        assert settings["iban_general"] == GENERAL_IBAN

        # Next time the IBAN is known, and nothing is added twice.
        again = upload(client, headers, SAMPLE_XLS)
        assert again.status_code == 200
        assert (again.json()["rows_new"], again.json()["rows_duplicate"]) == (0, 20)


def test_overlapping_statements_only_add_what_is_new(tmp_path):
    client, _ = build_client(tmp_path, provider=RoutingProvider())
    with client:
        headers = register_admin(client)
        upload(client, headers, SAMPLE_XLS, compte="General")
        longer = upload(client, headers, LONG_XLS).json()
        extra = len(LONG_ROWS) - 20
        assert (longer["rows_total"], longer["rows_new"], longer["rows_duplicate"]) == (len(LONG_ROWS), extra, 20)

        statements = client.get("/api/v1/statements/imports", headers=headers).json()
        movements = client.get(
            f"/api/v1/statements/imports/{statements[0]['id']}/movements", headers=headers
        ).json()
        assert len(movements) == extra
        income = [m for m in movements if m["categoria"] == "ingres"]
        assert income and all(m["match_status"] == "not_applicable" for m in income)

        # Bringing a statement in never matches anything.
        with client.app.state.session_factory() as session:
            assert session.query(PaymentMatch).count() == 0


def test_the_model_can_refuse_a_file_that_only_looks_right(tmp_path):
    provider = RoutingProvider(
        format_verdict={
            "valid": False,
            "bank": "BBVA",
            "account_iban": "",
            "header_row": 2,
            "confidence": 0.9,
            "issues": ["És un extracte d'un altre banc."],
        }
    )
    client, _ = build_client(tmp_path, provider=provider)
    with client:
        headers = register_admin(client)
        refused = upload(client, headers, SAMPLE_XLS, compte="General")
        assert refused.status_code == 422
        assert "altre banc" in refused.json()["detail"]
        assert client.get("/api/v1/statements/imports", headers=headers).json() == []
        checked = [r for r in provider.structures if r.schema_name == "statement_format_check"]
        assert "Moviments del compte" in checked[0].messages[0].content


def test_without_a_model_the_parser_still_decides(tmp_path):
    client, _ = build_client(tmp_path, provider=RoutingProvider(configured=False))
    with client:
        headers = register_admin(client)
        stored = upload(client, headers, SAMPLE_XLS, compte="General")
        assert stored.status_code == 200
        assert any("comprovació amb IA" in w for w in stored.json()["warnings"])


def test_other_files_are_refused(tmp_path):
    client, _ = build_client(tmp_path, provider=RoutingProvider())
    with client:
        headers = register_admin(client)
        response = client.post(
            "/api/v1/statements/upload",
            headers=headers,
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 415


def test_correcting_a_movement(tmp_path):
    client, _ = build_client(tmp_path, provider=RoutingProvider())
    with client:
        headers = register_admin(client)
        statement = upload(client, headers, SAMPLE_XLS, compte="General").json()
        movements = client.get(f"/api/v1/statements/imports/{statement['id']}/movements", headers=headers).json()
        junior = next(m for m in movements if m["concepte"] == "JUNIOR REPORT")

        changed = client.patch(
            f"/api/v1/statements/movements/{junior['id']}",
            headers=headers,
            json={"tipus": "Transferència bancària", "categoria": "devolucio"},
        ).json()
        assert changed["tipus"] == "Transferència bancària"
        assert changed["match_status"] == "not_applicable"
