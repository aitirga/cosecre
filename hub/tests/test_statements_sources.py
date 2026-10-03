"""The two sources that are not a CaixaBank Excel: the caixeta sheet and the prepaid PDF."""

from __future__ import annotations

from conftest import build_client, register_admin
from fake_sheets import FakeSheets
from statement_fakes import SAMPLE_XLS, RoutingProvider

from cosecre_hub.models import BankMovement, StatementImport

# The real CAIXETA'26 header and first rows, as the Sheets API returns them unformatted.
CAIXETA_26 = [
    ["º", "DATA", "Número Factura", "CONCEPTE", "IMPORT", "SALDO", "TICKET", "ESFERA"],
    ["Cix_000", "", "", "SALDO INICIAL", "", 658.91, True, True],
    ["Cix_001", 46034, "60135", "Aigua secretaria", -6, 652.91, True, True],
    ["Cix_002", 46035, "2627-T0322C01-5056", "Altres despeses", -19.77, 633.14, True, True],
    ["Cix_003", 46032, "DESPESA SIMPLIFICADA", "Material Infantil", -2, 631.14, True, True],
    ["Cix_006", 46049, "DEVOLUCIÓ", "Devolució sortida", -10, 612.38, True, True],
    ["Cix_008", 46056, "INGRÉS", "Ingrés efectiu famílies", 513, 1115.38, True, True],
    ["Cix_168"],  # numbered ahead of time, still empty
]
CAIXETA_25 = [
    ["º", "DATA", "CONCEPTE", "IMPORT", "SALDO", "TICKET", "ESFERA"],
    ["Cix_001", 45665, "Material escolar ESO", -3.9, 677.75, True, True],
]


def sheets_with_caixeta() -> FakeSheets:
    sheets = FakeSheets()
    sheets.tabs = {
        "CAIXETA'26": [list(r) for r in CAIXETA_26],
        "CAIXETA'25": [list(r) for r in CAIXETA_25],
        "260929": [["arqueig"], ["50 €", 2]],  # a count tab, not movements
    }
    return sheets


CAIXETA_URL = "https://docs.google.com/spreadsheets/d/test-caixeta/edit"


def caixeta_movements(client):
    with client.app.state.session_factory() as session:
        return {
            (m.raw["tab"], m.external_ref): (m.import_value, m.categoria, m.num_factura_hint, m.tipus)
            for m in session.query(BankMovement).filter(BankMovement.source == "caixeta_sheet")
        }


def test_caixeta_is_read_from_its_yearly_tabs(tmp_path):
    sheets = sheets_with_caixeta()
    client, _ = build_client(
        tmp_path, provider=RoutingProvider(), sheet_service=sheets, caixeta_spreadsheet_url=CAIXETA_URL
    )
    with client:
        headers = register_admin(client)
        status = client.post("/api/v1/statements/caixeta/sync", headers=headers).json()
        assert status["configured"] and status["changed"] is True

        rows = caixeta_movements(client)
        assert len(rows) == 7  # six in '26 (the empty Cix_168 skipped), one in '25
        assert rows[("CAIXETA'26", "Cix_001")] == (-6.0, "pagament", "60135", "Efectiu")
        assert rows[("CAIXETA'26", "Cix_003")][2] == ""  # "DESPESA SIMPLIFICADA" is not a number
        assert rows[("CAIXETA'26", "Cix_000")][1] == "saldo_inicial"
        assert rows[("CAIXETA'26", "Cix_006")][1] == "devolucio"
        assert rows[("CAIXETA'26", "Cix_008")][1] == "ingres"
        assert rows[("CAIXETA'25", "Cix_001")][0] == -3.9

        with client.app.state.session_factory() as session:
            living = session.query(StatementImport).filter_by(source="caixeta_sheet").one()
            assert living.compte == "Caixeta"


def test_caixeta_unchanged_is_not_rewritten_and_edits_update_in_place(tmp_path):
    sheets = sheets_with_caixeta()
    client, _ = build_client(
        tmp_path, provider=RoutingProvider(), sheet_service=sheets, caixeta_spreadsheet_url=CAIXETA_URL
    )
    with client:
        headers = register_admin(client)
        client.post("/api/v1/statements/caixeta/sync", headers=headers)
        with client.app.state.session_factory() as session:
            before = {m.external_ref: m.id for m in session.query(BankMovement)}

        # Opening the app again right away: throttled, no read at all.
        reads = sheets.tab_reads
        client.post("/api/v1/statements/caixeta/sync?if_due=true", headers=headers)
        assert sheets.tab_reads == reads

        # Someone fixes an amount in the sheet.
        sheets.tabs["CAIXETA'26"][2][4] = -6.5
        client.post("/api/v1/statements/caixeta/sync", headers=headers)
        rows = caixeta_movements(client)
        assert rows[("CAIXETA'26", "Cix_001")][0] == -6.5
        with client.app.state.session_factory() as session:
            after = {m.external_ref: m.id for m in session.query(BankMovement)}
        assert after == before  # same rows, updated — not re-created

        # A row deleted in the sheet goes away here too.
        del sheets.tabs["CAIXETA'26"][3]
        client.post("/api/v1/statements/caixeta/sync", headers=headers)
        assert ("CAIXETA'26", "Cix_002") not in caixeta_movements(client)


PREPAID = {
    "kind": "prepaid_statement",
    "card_number": "4000 0000 0000 0002",
    "contract": "0000.00-0000000-00",
    "print_date": "03/10/2026",
    "month_operations": "13,20",
    "balance": "379,46",
    "rows": [
        {"establiment": "RECARGA TARJETA PREPAGO", "data": "29/09/2026", "import": "400,00"},
        {"establiment": "MERCASA", "data": "29/09/2026", "import": "-11,75"},
        {"establiment": "MERCASA", "data": "30/09/2026", "import": "-2,60"},
        {"establiment": "CONDIS", "data": "01/10/2026", "import": "-13,20"},
    ],
}


def drop_pdf(client, headers):
    return client.post(
        "/api/v1/statements/upload",
        headers=headers,
        files={"file": ("targeta.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )


def test_prepaid_pdf_is_read_and_its_top_up_paired_with_the_account_charge(tmp_path):
    provider = RoutingProvider(extraction_payload=PREPAID)
    client, _ = build_client(tmp_path, provider=provider)
    with client:
        headers = register_admin(client)
        client.post(
            "/api/v1/statements/upload",
            headers=headers,
            files={"file": ("Moviments_compte.xls", SAMPLE_XLS, "application/vnd.ms-excel")},
            data={"compte": "General"},
        )
        response = drop_pdf(client, headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["compte"], body["rows_total"], body["warnings"]) == ("Targeta Prepagament", 4, [])
        assert provider.extractions[-1].schema_name == "prepaid_statement"

        with client.app.state.session_factory() as session:
            top_up = session.query(BankMovement).filter_by(concepte="RECARGA TARJETA PREPAGO").one()
            charge = session.query(BankMovement).filter_by(concepte="CARREGA.TARG.PREPAG").one()
            assert top_up.linked_movement_id == charge.id and charge.linked_movement_id == top_up.id
            assert top_up.match_status == "not_applicable"
            condis = session.query(BankMovement).filter_by(concepte="CONDIS").one()
            assert (condis.tipus, condis.match_status) == ("Targeta de prepagament", "unmatched")

        settings = client.get("/api/v1/documents/settings", headers=headers).json()
        assert settings["prepaid_card_number"] == "4000 0000 0000 0002"

        # The same printout again adds nothing.
        assert drop_pdf(client, headers).json()["rows_new"] == 0


def test_prepaid_totals_that_do_not_add_up_are_flagged(tmp_path):
    client, _ = build_client(
        tmp_path, provider=RoutingProvider(extraction_payload={**PREPAID, "month_operations": "20,00"})
    )
    with client:
        headers = register_admin(client)
        warnings = drop_pdf(client, headers).json()["warnings"]
        assert any("13.20" in w for w in warnings)


def test_a_pdf_that_is_not_a_prepaid_statement_is_refused(tmp_path):
    client, _ = build_client(tmp_path, provider=RoutingProvider(extraction_payload={"kind": "other", "rows": []}))
    with client:
        headers = register_admin(client)
        response = drop_pdf(client, headers)
        assert response.status_code == 422
        assert "targeta de prepagament" in response.json()["detail"]
