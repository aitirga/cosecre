"""The statements mirrored into the accounting spreadsheet, and edits read back."""

from __future__ import annotations

from fake_sheets import FakeSheets
from test_statements_matching import detail, movement, reconciled  # noqa: F401  (fixture)

from cosecre_hub.services.statements import mirror

TAB = "Extracte General"
SYNC = "/api/v1/statements/mirror/sync"
NUM, REF = "Núm. factura", "Codi intern factura"


def sheets(client) -> FakeSheets:
    return client.app.state.sheet_service


def code(client, concept: str) -> str:
    return movement(client, concept).codi


def test_each_account_gets_a_tab_that_reads_like_the_bank_export(reconciled):
    client, headers, *_ = reconciled
    grid = sheets(client).mirror[TAB]
    assert grid[0] == mirror.HEADERS
    assert all(row[0].startswith("G_") for row in grid[1:])
    # Oldest first, like reading the statement.
    dates = [row[1] for row in grid[1:]]
    assert dates == sorted(dates)
    # Proposals are not confirmations: the invoice cells start empty.
    assert all(row[mirror.NUMBERS_COLUMN] == "" and row[mirror.REFS_COLUMN] == "" for row in grid[1:])
    assert set(sheets(client).mirror_tones[TAB]) <= {"pending", "plain"}


def test_confirming_in_the_app_writes_the_invoice_beside_its_line(reconciled):
    client, headers, *_ = reconciled
    body = detail(client, headers, "FAC:PRF26-00001")
    client.post(
        f"/api/v1/reconciliation/movements/{body['id']}/confirm",
        headers=headers,
        json={"document_refs": ["DOC-000"]},
    )
    codi = body["codi"]
    assert sheets(client).mirror_cell(TAB, codi, NUM) == "PRF26-00001"
    assert sheets(client).mirror_cell(TAB, codi, REF) == "DOC-000"
    row = [r[0] for r in sheets(client).mirror[TAB][1:]].index(codi)
    assert sheets(client).mirror_tones[TAB][row] == "justified"


def test_an_internal_code_typed_in_the_sheet_confirms_the_line(reconciled):
    client, headers, *_ = reconciled
    codi = code(client, "FAC:0397")
    sheets(client).set_mirror_cell(TAB, codi, REF, "doc-001")  # case does not matter

    result = client.post(SYNC, headers=headers).json()
    assert [(c["codi"], c["text"]) for c in result["applied"]] == [(codi, "Justificat amb 0397 (DOC-001)")]
    assert movement(client, "FAC:0397").match_status == "confirmed"
    assert sheets(client).mirror_cell(TAB, codi, NUM) == "0397"
    assert sheets(client).mirror_cell(TAB, codi, REF) == "DOC-001"


def test_an_invoice_number_typed_in_the_sheet_is_looked_up(reconciled):
    client, headers, *_ = reconciled
    codi = code(client, "FAC:0397")
    sheets(client).set_mirror_cell(TAB, codi, NUM, "A 12")  # spacing does not matter
    result = client.post(SYNC, headers=headers).json()
    assert result["issues"] == []
    assert sheets(client).mirror_cell(TAB, codi, REF) == "DOC-002"


def test_an_edit_that_cannot_apply_is_reported_and_put_back(reconciled):
    client, headers, *_ = reconciled
    codi = code(client, "FAC:0397")
    sheets(client).set_mirror_cell(TAB, codi, NUM, "NO-EXISTEIX")
    other = code(client, "FAC:PRF26-00001")
    sheets(client).set_mirror_cell(TAB, other, REF, "DOC-999")

    result = client.post(SYNC, headers=headers).json()
    assert result["applied"] == []
    assert {i["codi"] for i in result["issues"]} == {codi, other}
    assert sheets(client).mirror_cell(TAB, codi, NUM) == ""
    assert sheets(client).mirror_cell(TAB, other, REF) == ""


def test_clearing_the_cell_takes_the_confirmation_back(reconciled):
    client, headers, *_ = reconciled
    codi = code(client, "FAC:0397")
    sheets(client).set_mirror_cell(TAB, codi, REF, "DOC-001")
    client.post(SYNC, headers=headers)

    sheets(client).set_mirror_cell(TAB, codi, REF, "")
    sheets(client).set_mirror_cell(TAB, codi, NUM, "")
    result = client.post(SYNC, headers=headers).json()
    assert [c["text"] for c in result["applied"]] == ["Ja no està justificat"]
    assert movement(client, "FAC:0397").match_status == "unmatched"


def test_a_stale_sheet_never_undoes_what_the_app_confirmed(reconciled):
    """Confirmed while Google was down: the sheet's empty cell is old, not an edit."""
    client, headers, *_ = reconciled
    body = detail(client, headers, "FAC:PRF26-00001")
    sheets(client).fail_writes = True
    client.post(
        f"/api/v1/reconciliation/movements/{body['id']}/confirm",
        headers=headers,
        json={"document_refs": ["DOC-000"]},
    )
    assert sheets(client).mirror_cell(TAB, body["codi"], REF) == ""
    sheets(client).fail_writes = False

    result = client.post(SYNC, headers=headers).json()
    assert result["applied"] == [] and result["issues"] == []
    assert movement(client, "FAC:PRF26-00001").match_status == "confirmed"
    assert sheets(client).mirror_cell(TAB, body["codi"], REF) == "DOC-000"


def test_an_invoice_already_paid_elsewhere_is_refused(reconciled):
    client, headers, *_ = reconciled
    first, second = code(client, "FAC:0397"), code(client, "FAC:PRF26-00001")
    sheets(client).set_mirror_cell(TAB, first, REF, "DOC-001")
    client.post(SYNC, headers=headers)
    sheets(client).set_mirror_cell(TAB, second, REF, "DOC-001")
    result = client.post(SYNC, headers=headers).json()
    assert [i["codi"] for i in result["issues"]] == [second]
    assert "ja està justificada" in result["issues"][0]["text"]


def test_lists_and_comparisons_ignore_case_spacing_and_order():
    assert mirror.split_list(" DOC-1 ;doc-2, DOC-1\n") == ["DOC-1", "doc-2"]
    assert mirror.canonical("b, A") == mirror.canonical("a;B")
    assert mirror.number_key(" a-12 ") == mirror.number_key("A 12") == "A12"
    assert mirror.number_key("2026/116574-A") == "2026116574A"


def test_the_real_service_writes_typed_cells_and_creates_a_tab_once():
    """What goes to Google: a new tab gets widths and a warning on the bank's columns."""
    from datetime import date

    from cosecre_hub.services.sheets import GoogleSheetsService, MirrorTabData

    calls: list[dict] = []

    class Call:
        def __init__(self, result):
            self.result = result

        def execute(self):
            return self.result

    class Spreadsheets:
        def get(self, **kwargs):
            return Call({"sheets": [{"properties": {"sheetId": 1, "title": "Registre"}}]})

        def batchUpdate(self, spreadsheetId, body):
            calls.append(body)
            if "addSheet" in body["requests"][0]:
                return Call({"replies": [{"addSheet": {"properties": {"sheetId": 77, "title": TAB}}}]})
            return Call({})

    service = GoogleSheetsService.__new__(GoogleSheetsService)
    service._lock = __import__("threading").RLock()
    service._resources = {"spreadsheets": Spreadsheets()}
    workspace = type("W", (), {"spreadsheet_id": "sheet-1", "spreadsheet_url": ""})()
    tab = MirrorTabData(
        title=TAB,
        headers=mirror.HEADERS,
        kinds=[kind for _, kind in mirror.COLUMNS],
        widths=mirror.WIDTHS,
        protected_columns=mirror.BANK_COLUMNS,
        rows=[["G_001", date(2026, 1, 2), None, "COMPRA", "", -12.5, 100.0, "", ""]],
        tones=["pending"],
    )
    service.write_mirror(workspace, [tab])

    assert calls[0]["requests"] == [{"addSheet": {"properties": {"title": TAB}}}]
    requests = calls[1]["requests"]
    protected = [r["addProtectedRange"]["protectedRange"] for r in requests if "addProtectedRange" in r]
    assert protected[0]["warningOnly"] is True and protected[0]["range"]["endColumnIndex"] == mirror.BANK_COLUMNS
    grid = next(r["updateSheetProperties"] for r in requests if "updateSheetProperties" in r)
    assert grid["properties"]["gridProperties"] == {"rowCount": 3, "columnCount": len(mirror.HEADERS), "frozenRowCount": 1}
    rows = next(r["updateCells"] for r in requests if "updateCells" in r)["rows"]
    line = rows[1]["values"]
    assert line[1]["userEnteredFormat"]["numberFormat"]["pattern"] == "dd/mm/yyyy"
    assert line[5]["userEnteredValue"] == {"numberValue": -12.5}
    # Only the invoice cells of an unjustified payment are tinted.
    assert "backgroundColor" not in line[0]["userEnteredFormat"]
    assert "backgroundColor" in line[mirror.REFS_COLUMN]["userEnteredFormat"]
    assert rows[2] == {"values": [{} for _ in mirror.HEADERS]}
