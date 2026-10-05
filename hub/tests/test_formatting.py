from __future__ import annotations

from datetime import date

import pytest

from cosecre_hub.schemas.documents import canonical_choice
from cosecre_hub.services.classification import JevAnswer, combine
from cosecre_hub.services.sheets import (
    REGISTER_COLUMNS,
    RegisterLayout,
    GoogleSheetsService,
    cell_to_value,
    drive_file_id_from_link,
    row_colour,
    value_to_cell,
)
from cosecre_hub.services.text_format import (
    format_date,
    iban_is_valid,
    name_case,
    normalize_iban,
    parse_amount,
    parse_date,
    sentence_case,
    split_address,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6/2/2026 9:29", date(2026, 2, 6)),
        ("24/03/2026", date(2026, 3, 24)),
        ("01-12-26", date(2026, 12, 1)),
        ("2026-01-31", date(2026, 1, 31)),
        (46106, date(2026, 3, 25)),
        ("31/02/2026", None),
        ("dimarts", None),
        ("", None),
    ],
)
def test_dates_are_read_day_first(raw, expected):
    assert parse_date(raw) == expected


def test_dates_are_shown_as_dd_mm_yyyy():
    assert format_date(date(2026, 2, 6)) == "06/02/2026"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("505,55", 505.55), ("1.234,56 €", 1234.56), ("75.0 €", 75.0), ("8.20", 8.2), ("EUR 4,45", 4.45)],
)
def test_amounts(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("FERRETERIA MARTÍ SL", "Ferreteria Martí SL"),
        ("L'HOSPITALET DE LLOBREGAT", "L'Hospitalet de Llobregat"),
        ("INSTITUT D'ESTUDIS CATALANS", "Institut d'Estudis Catalans"),
        ("estucinema", "Estucinema"),
        ("bonÀrea Agrupa", "bonÀrea Agrupa"),  # mixed case is a choice; leave it
        ("SANT JOAN-DESPÍ", "Sant Joan-Despí"),
    ],
)
def test_names_lose_their_capitals_but_not_their_shape(raw, expected):
    assert name_case(raw) == expected


def test_descriptions_get_sentence_case_and_keep_acronyms():
    assert sentence_case("MATERIAL ESO GENERAL") == "Material ESO general"
    assert sentence_case("Quota del Cangur") == "Quota del Cangur"


def test_iban_checksum_catches_a_misread_digit():
    good = normalize_iban("es1421000963610200057373")
    assert good == "ES14 2100 0963 6102 0005 7373"
    assert iban_is_valid(good)
    assert not iban_is_valid("ES14 2100 0963 6102 0005 7378")
    assert not iban_is_valid("ES68 0081 0472 1600 0114 5225 ES38 0128")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C/ Sabastida 6 baixos 08031 Barcelona", ("C/ Sabastida 6 baixos", "08031", "Barcelona")),
        ("PLAZA TRINITAT,6,BARCELONA 08033 BARCELONA", ("PLAZA TRINITAT,6,BARCELONA", "08033", "BARCELONA")),
        ("C. del Carme, 47. 08001 Barcelona.", ("C. del Carme, 47", "08001", "Barcelona")),
        ("/ CARAVIS 16 ZARAGOZA", ("/ CARAVIS 16 ZARAGOZA", "", "")),
        ("", ("", "", "")),
    ],
)
def test_old_addresses_split_on_the_postcode(raw, expected):
    assert split_address(raw) == expected


def test_choices_match_ignoring_case_and_accents():
    assert canonical_choice("metode_pagament", "transferencia bancaria") == "Transferència bancària"
    assert canonical_choice("pagament", "") == ""
    assert canonical_choice("pagament", "a mitges") == "a mitges"


# ── Combining the two models ─────────────────────────────────────────────────


def test_agreement_is_trusted():
    value, hint = combine("Factura", JevAnswer("Factura", 0.7))
    assert value == "Factura" and hint.source == "jev+openai" and not hint.review


def test_a_sure_jev_overrides_but_is_flagged():
    value, hint = combine("Factura simplificada", JevAnswer("Factura", 0.9))
    assert value == "Factura" and hint.review and hint.alternative == "Factura simplificada"


def test_an_unsure_jev_does_not_override():
    value, hint = combine("Tiquet de rebut", JevAnswer("Factura simplificada", 0.6))
    assert value == "Tiquet de rebut" and hint.review and hint.alternative == "Factura simplificada"


def test_a_lone_unsure_jev_answer_is_dropped():
    assert combine("", JevAnswer("Pagat", 0.3)) == ("", None)
    value, hint = combine("", JevAnswer("Pagat", 0.8))
    assert value == "Pagat" and hint.review


def test_without_jev_the_vision_answer_stands_unflagged():
    value, hint = combine("Efectiu", None)
    assert value == "Efectiu" and hint.source == "openai" and not hint.review


# ── Typed cells ──────────────────────────────────────────────────────────────


def test_cells_are_written_typed_so_sheets_never_reparses_them():
    assert value_to_cell("text", "1/2")["userEnteredValue"] == {"stringValue": "1/2"}
    assert value_to_cell("text", "08033")["userEnteredFormat"]["numberFormat"]["type"] == "TEXT"
    dated = value_to_cell("date", date(2026, 2, 6))
    assert dated["userEnteredValue"] == {"numberValue": 46059}
    assert dated["userEnteredFormat"]["numberFormat"]["pattern"] == "dd/mm/yyyy"
    assert value_to_cell("file", '=IMAGE("x")')["userEnteredValue"] == {"formulaValue": '=IMAGE("x")'}
    assert value_to_cell("bool", True)["userEnteredValue"] == {"boolValue": True}
    assert value_to_cell("amount", None) == {}


def test_cells_read_back_into_values():
    assert cell_to_value("date", "data_factura", 46059) == date(2026, 2, 6)
    assert cell_to_value("text", "codi_postal", 8033) == "08033"
    assert cell_to_value("text", "num_factura", 52211.0) == "52211"
    assert cell_to_value("bool", "validat", True) is True
    assert cell_to_value("choice", "pagament", "PAGAT") == "Pagat"


def test_writes_skip_columns_the_register_does_not_own(tmp_path):
    from conftest import build_settings

    service = GoogleSheetsService(build_settings(tmp_path))
    columns = {c.field: i for i, c in enumerate(REGISTER_COLUMNS)}
    # Someone inserted their own column at index 3.
    columns = {name: (i + 1 if i >= 3 else i) for name, i in columns.items()}
    layout = RegisterLayout("s", 7, "Registre", columns, len(REGISTER_COLUMNS) + 1, 1000)
    requests = service._row_requests(layout, 5, {c.field: "" for c in REGISTER_COLUMNS}, colour=False)
    written = set()
    for request in requests:
        cells = request["updateCells"]
        start = cells["start"]["columnIndex"]
        written.update(range(start, start + len(cells["rows"][0]["values"])))
    assert 3 not in written
    assert written == set(range(len(REGISTER_COLUMNS) + 1)) - {3}


def test_a_justified_row_is_green_even_before_it_is_validated():
    pending, done, justified = (
        row_colour({"validat": False}),
        row_colour({"validat": True}),
        row_colour({"validat": False, "justificat": True}),
    )
    assert len({str(pending), str(done), str(justified)}) == 3
    assert justified["green"] > justified["red"] and justified["green"] > justified["blue"]
    assert row_colour({"validat": True, "justificat": True}) == justified

    layout = RegisterLayout("s", 7, "Registre", {"validat": 0}, 1, 1000)
    requests = GoogleSheetsService.__new__(GoogleSheetsService)._row_requests(
        layout, 5, {"validat": True, "justificat": True}, colour=True
    )
    # The flag colours the row; it is never written as a cell.
    assert [r["updateCells"]["rows"][0]["values"] for r in requests if "updateCells" in r] == [
        [{"userEnteredValue": {"boolValue": True}}]
    ]
    assert requests[-1]["repeatCell"]["cell"]["userEnteredFormat"]["backgroundColor"] == justified


def test_drive_ids_are_recovered_from_formulas_and_links():
    assert drive_file_id_from_link('=IMAGE("https://drive.google.com/uc?export=view&id=1AbC_def-123")') == "1AbC_def-123"
    assert drive_file_id_from_link("https://drive.google.com/file/d/1AbC_def-123/view") == "1AbC_def-123"
    assert drive_file_id_from_link("") is None


def test_an_old_budget_column_becomes_the_account_dropdown_and_the_reference_hides():
    headers = [c.header for c in REGISTER_COLUMNS]
    headers[headers.index("Compte")] = "Pressupost afectat"
    sent: list[dict] = []
    service = GoogleSheetsService.__new__(GoogleSheetsService)

    class Values:
        def get(self, **_):
            return self

        def execute(self):
            return {"values": [headers]}

    service._values = lambda: Values()
    service._batch = lambda _id, requests: sent.extend(requests)

    layout = service._map_register("sheet", {"title": "Registre", "sheetId": 7})

    account = headers.index("Pressupost afectat")
    assert layout.columns["pressupost_afectat"] == account
    relabel = next(r["updateCells"] for r in sent if "updateCells" in r)
    assert relabel["start"]["columnIndex"] == account
    assert relabel["rows"][0]["values"][0]["userEnteredValue"]["stringValue"] == "Compte"
    dropdown = next(r["setDataValidation"] for r in sent if "setDataValidation" in r)
    assert [v["userEnteredValue"] for v in dropdown["rule"]["condition"]["values"]][2] == "Menjador"
    hidden = next(r["updateDimensionProperties"] for r in sent if "updateDimensionProperties" in r)
    assert hidden["range"]["startIndex"] == headers.index("Núm. doc. intern")


def test_the_account_is_a_closed_list():
    assert canonical_choice("pressupost_afectat", "targeta prepagament") == "Targeta Prepagament"


def test_the_account_is_proposed_by_vision_and_decided_by_jev():
    from cosecre_hub.schemas import DocumentExtraction
    from cosecre_hub.services.classification import DocumentClassifier
    from cosecre_hub.services.extraction import DocumentExtractionService

    class FakeJev:
        model = "jev-test"

        def decide(self, state, questions):
            assert "pressupost_afectat" in questions
            assert "metode_pagament: Efectiu" in state
            return {"pressupost_afectat": JevAnswer("Caixeta", 0.93)}

    raw = DocumentExtraction.model_validate(
        {
            "transcripcio": "FACTURA SIMPLIFICADA\nTOTAL 12,40\nEFECTIVO 20,00 CAMBIO 7,60",
            "tipus_document": "Factura simplificada",
            "metode_pagament": "Efectiu",
            "pressupost_afectat": "General",
        }
    )
    service = DocumentExtractionService(registry=None, classifier=DocumentClassifier(FakeJev()))
    result = service.finish(raw)

    assert result.fields["pressupost_afectat"] == "Caixeta"
    hint = result.hints["pressupost_afectat"]
    assert hint.source == "jev" and hint.alternative == "General" and hint.review
    assert result.trace["final"]["pressupost_afectat"]["value"] == "Caixeta"
    assert result.trace["vision"]["proposal"]["pressupost_afectat"] == "General"


def test_a_register_inside_a_table_gets_a_dropdown_typed_column_instead():
    headers = [c.header for c in REGISTER_COLUMNS]
    account = headers.index("Compte")
    headers[account] = "Pressupost afectat"
    sent: list[list[dict]] = []
    service = GoogleSheetsService.__new__(GoogleSheetsService)

    class Call:
        def __init__(self, payload):
            self.payload = payload

        def get(self, **_):
            return self

        def execute(self):
            return self.payload

    table = {
        "tableId": "t1",
        "range": {"sheetId": 7, "startColumnIndex": 0, "endColumnIndex": len(headers)},
        "columnProperties": [
            {"columnIndex": 0, "columnName": "Núm. doc. intern", "columnType": "TEXT"},
            {"columnIndex": account, "columnName": "Pressupost afectat", "columnType": "TEXT"},
        ],
    }

    class Spreadsheets:
        def get(self, **_):
            return Call({"sheets": [{"properties": {"sheetId": 7}, "tables": [table]}]})

    def batch(_id, requests):
        if any("setDataValidation" in r for r in requests):
            raise RuntimeError("This operation is not allowed on cells in typed columns.")
        sent.append(requests)

    service._values = lambda: Call({"values": [headers]})
    service._spreadsheets = lambda: Spreadsheets()
    service._batch = batch

    layout = service._map_register("sheet", {"title": "Registre", "sheetId": 7})

    assert layout.columns["pressupost_afectat"] == account
    update = sent[-1][0]["updateTable"]
    assert update["fields"] == "columnProperties"
    props = {p["columnIndex"]: p for p in update["table"]["columnProperties"]}
    assert props[0]["columnName"] == "Núm. doc. intern"  # the rest is kept
    assert props[account]["columnType"] == "DROPDOWN"
    assert props[account]["columnName"] == "Compte"
