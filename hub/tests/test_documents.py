from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from conftest import FakeProvider, build_client, register_admin
from fake_sheets import FakeSheets

from cosecre_hub.models import Document, Responsable
from cosecre_hub.services.classification import DocumentClassifier, JevAnswer, JevClient
from cosecre_hub.services.sheets import LegacyTab, SheetRow, cell_to_value

RECORDS = "/api/v1/documents/records"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


class FakeJev(JevClient):
    def __init__(self, answers: dict[str, JevAnswer] | None = None, fail: bool = False):
        self.model = "jev-fake"
        self.answers = answers or {}
        self.fail = fail
        self.states: list[str] = []

    def decide(self, state, questions):
        from cosecre_hub.services.classification import JevError

        self.states.append(state)
        if self.fail:
            raise JevError("down")
        return dict(self.answers)

    def close(self):
        pass


@pytest.fixture
def register(tmp_path):
    """``(client, headers, sheet, provider)`` with a fake sheet and no Jev."""
    sheet = FakeSheets()
    client, provider = build_client(tmp_path, sheet_service=sheet)
    with client:
        headers = register_admin(client)
        yield client, headers, sheet, provider


def upload(client, headers, *, source="camera", name="ticket.jpg", content=JPEG, mime="image/jpeg"):
    response = client.post(
        f"{RECORDS}/upload",
        headers=headers,
        files={"file": (name, content, mime)},
        data={"source": source},
    )
    assert response.status_code == 200, response.text
    return response.json()["internal_doc_number"]


# ── Extraction ───────────────────────────────────────────────────────────────


def test_a_photo_becomes_a_formatted_register_entry_in_db_and_sheet(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)

    record = client.get(f"{RECORDS}/{reference}", headers=headers).json()
    assert record["extraction_status"] == "needs_validation"
    assert record["origen"] == "Foto"
    assert record["tipus_document"] == "Factura simplificada"
    assert record["data_factura"] == "2026-01-31"
    assert record["import"] == 100.0
    # House formatting, enforced rather than trusted to the model.
    assert record["ciutat"] == "Barcelona"
    assert record["carrer"] == "C/ Major 5"
    assert record["cif_proveidor"] == "B12345678"
    assert record["descripcio"] == "Material de ferreteria"
    assert record["pagament"] == "Pagat" and record["metode_pagament"] == "Efectiu"
    assert "FERRETERIA" in record["transcripcio"]

    row = sheet.row_for(reference)
    assert row["data_factura"] == date(2026, 1, 31)
    assert row["file_link"].startswith("=IMAGE(")
    assert record["sheet_state"] == "synced"
    # One folder, named by date and number; the slash is not a path.
    assert list(sheet.drive.values())[0]["name"] == "2026-01-31_F-2026-001.jpg"

    with client.app.state.session_factory() as session:
        stored = session.query(Document).filter_by(internal_doc_number=reference).one()
        assert stored.codi_postal == "08033"


def test_uploaded_files_are_originals(register):
    client, headers, _, _ = register
    reference = upload(client, headers, source="file", name="invoice.pdf", content=b"%PDF-1.7", mime="application/pdf")
    assert client.get(f"{RECORDS}/{reference}", headers=headers).json()["origen"] == "Original"


def test_originals_download_one_by_one_or_all_together(register):
    client, headers, _, _ = register
    first = upload(client, headers)
    upload(client, headers)

    single = client.get(f"{RECORDS}/{first}/file", headers=headers)
    assert single.content == JPEG
    assert "2026-01-31_F-2026-001.jpg" in single.headers["content-disposition"]

    response = client.get(f"{RECORDS}/files.zip", headers=headers)
    assert response.status_code == 200
    assert "cosecre-originals-" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        # Same date and number twice: the second one gets its reference.
        assert len(names) == 2 and len(set(names)) == 2
        assert "2026-01-31_F-2026-001.jpg" in names
        assert archive.read(names[0]) == JPEG


def test_several_photos_queue_as_separate_documents(register):
    client, headers, sheet, _ = register
    references = {upload(client, headers) for _ in range(3)}
    assert len(references) == 3
    assert len(sheet.rows) == 3
    names = [f["name"] for f in sheet.drive.values()]
    assert len(set(names)) == 3  # same date and number: later ones get a suffix


def test_the_register_works_without_a_sheet_and_catches_up_later(register):
    client, headers, sheet, _ = register
    sheet.ready = False
    reference = upload(client, headers)
    record = client.get(f"{RECORDS}/{reference}", headers=headers).json()
    assert record["extraction_status"] == "needs_validation"
    assert record["sheet_state"] == "pending"
    assert not sheet.rows

    sheet.ready = True
    assert client.post(f"{RECORDS}/sync", headers=headers).json()["pushed"] == 1
    assert sheet.row_for(reference)["proveidor"] == "Initial document"


# ── Two-way sync ─────────────────────────────────────────────────────────────


def diff_of(client, headers):
    return client.get(f"{RECORDS}/sync/diff", headers=headers).json()


def test_a_sheet_edit_the_app_did_not_touch_comes_in_on_its_own_and_can_be_undone(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    sheet.row_for(reference).update({"proveidor": "Edited in sheet", "validat": True})

    status = client.post(f"{RECORDS}/sync", headers=headers).json()
    assert status["pulled"] == 1 and status["waiting"] == 0
    record = client.get(f"{RECORDS}/{reference}", headers=headers).json()
    assert record["proveidor"] == "Edited in sheet"
    assert record["extraction_status"] == "validated"
    assert diff_of(client, headers)["entries"] == []

    # The hub's own action: listed in Configuració's history, undone from there.
    action = client.get("/api/v1/history", headers=headers).json()["actions"][0]
    assert (action["label"], action["kind"]) == ("Canvis del full integrats", "auto")
    assert client.post(f"/api/v1/history/{action['id']}/undo", headers=headers).status_code == 200
    assert client.get(f"{RECORDS}/{reference}", headers=headers).json()["proveidor"] == "Initial document"


def test_a_pull_a_person_asks_for_is_preceded_by_a_backup(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    sheet.row_for(reference).update({"proveidor": "From the sheet"})
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"proveidor": "From the app"})

    status = client.post(f"{RECORDS}/sync", headers=headers).json()
    assert status["pulled"] == 0 and status["waiting"] == 1 and status["conflicts"] == 1

    applied = client.post(f"{RECORDS}/sync/pull", headers=headers, json={}).json()
    assert applied["applied"] == 1 and applied["backup"]
    backups = client.get("/api/v1/backups", headers=headers).json()["backups"]
    assert backups[0]["kind"] == "pre-pull" and backups[0]["has_sheet"] is True
    assert client.get(f"{RECORDS}/{reference}", headers=headers).json()["proveidor"] == "From the sheet"


def test_unticked_checkboxes_in_text_columns_are_empty_cells():
    # A sheet table can type a whole column as checkboxes; FALSE is not a name, nor 0 €.
    assert cell_to_value("text", "responsable_nom", False) == ""
    assert cell_to_value("text", "responsable_email", True) == ""
    assert cell_to_value("amount", "import_value", False) is None
    assert cell_to_value("bool", "validat", False) is False


def test_the_same_person_on_several_new_rows_is_remembered_once(register):
    client, headers, sheet, _ = register
    for row in (50, 51):
        sheet.rows[row] = {"num_doc_intern": "", "proveidor": f"Typed {row}", "responsable_nom": "Anna",
                           "responsable_email": "anna@example.org", "validat": False}
    assert client.post(f"{RECORDS}/sync", headers=headers).json()["pulled"] == 2
    session = client.app.state.session_factory()
    try:
        person = session.query(Responsable).one()
        assert (person.nom, person.uses) == ("Anna", 2)
    finally:
        session.close()


def test_app_edits_reach_the_sheet_on_their_own_even_after_an_outage(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    sheet.fail_writes = True
    response = client.patch(f"{RECORDS}/{reference}", headers=headers, json={"proveidor": "Mine"})
    assert response.status_code == 200
    assert response.json()["sheet_state"] == "pending"
    assert "full de càlcul" in response.json()["error_message"]

    sheet.fail_writes = False
    assert client.post(f"{RECORDS}/sync", headers=headers).json()["pushed"] == 1
    assert sheet.row_for(reference)["proveidor"] == "Mine"


def test_an_edit_on_both_sides_is_a_conflict_and_never_silently_overwritten(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    sheet.row_for(reference).update({"proveidor": "From the sheet"})
    saved = client.patch(f"{RECORDS}/{reference}", headers=headers, json={"proveidor": "From the app"}).json()
    assert "integrat" in saved["error_message"]
    assert sheet.row_for(reference)["proveidor"] == "From the sheet"

    entry = diff_of(client, headers)["entries"][0]
    assert entry["status"] == "conflict"
    # The person decides: here, the app's version wins.
    pushed = client.post(f"{RECORDS}/sync/push", headers=headers, json={"references": [reference]}).json()
    assert pushed["applied"] == 1
    assert sheet.row_for(reference)["proveidor"] == "From the app"
    assert diff_of(client, headers)["entries"] == []


def test_rows_typed_into_the_sheet_are_integrated_on_their_own(register):
    client, headers, sheet, _ = register
    sheet.rows[2] = {"num_doc_intern": "", "proveidor": "Typed by hand", "import_value": 12.5, "validat": False}
    assert client.post(f"{RECORDS}/sync", headers=headers).json()["pulled"] == 1
    reference = sheet.rows[2]["num_doc_intern"]
    assert reference.startswith("DOC-")
    assert client.get(f"{RECORDS}/{reference}", headers=headers).json()["proveidor"] == "Typed by hand"


def test_a_row_deleted_in_the_sheet_is_kept_and_comes_back_when_saved(register):
    client, headers, sheet, _ = register
    keep = [upload(client, headers) for _ in range(3)]
    sheet.delete_row(None, sheet.find_row(None, keep[0]))
    assert diff_of(client, headers)["counts"] == {"missing": 1}

    client.post(f"{RECORDS}/sync/pull", headers=headers, json={})
    record = client.get(f"{RECORDS}/{keep[0]}", headers=headers).json()
    assert record["sheet_state"] == "removed"

    client.patch(f"{RECORDS}/{keep[0]}", headers=headers, json={"descripcio_compra": "Per al taller"})
    assert sheet.row_for(keep[0])["descripcio_compra"] == "Per al taller"


def test_a_cleared_tab_is_refilled_from_the_database(register):
    client, headers, sheet, _ = register
    references = [upload(client, headers) for _ in range(7)]
    for index, reference in enumerate(references):
        # Seven different invoices: identical ones would be folded into one.
        client.patch(f"{RECORDS}/{reference}", headers=headers, json={"num_factura": f"F-{index}"})
    sheet.rows.clear()
    status = client.post(f"{RECORDS}/sync", headers=headers).json()
    assert status["waiting"] == 7  # shown, never acted on automatically
    assert len(client.get(RECORDS, headers=headers).json()) == 7
    client.post(f"{RECORDS}/sync/push", headers=headers, json={})
    assert {sheet.rows[n]["num_doc_intern"] for n in sheet.rows} == set(references)


# ── Versions ─────────────────────────────────────────────────────────────────


def test_a_version_can_be_compared_and_restored_and_the_present_is_kept(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    first = client.post("/api/v1/backups", headers=headers).json()["backups"][0]["name"]
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"proveidor": "Changed later"})
    second = upload(client, headers)

    comparison = client.get(f"/api/v1/backups/{first}/compare", headers=headers).json()
    assert comparison["counts"] == {"changed": 1, "only_now": 1}
    changed = next(e for e in comparison["entries"] if e["status"] == "changed")
    assert changed["changes"][0]["backup"] == "Initial document"
    assert changed["changes"][0]["now"] == "Changed later"

    result = client.post(f"/api/v1/backups/{first}/restore", headers=headers).json()
    assert result["restored"] == 1
    assert client.get(f"{RECORDS}/{reference}", headers=headers).json()["proveidor"] == "Initial document"
    assert client.get(f"{RECORDS}/{second}", headers=headers).status_code == 404
    # The sheet follows the restore; nothing newer is pulled back from it.
    status = client.post(f"{RECORDS}/sync", headers=headers).json()
    assert status["pulled"] == 0 and status["waiting"] == 1  # the second entry's row, for a person
    assert sheet.row_for(reference)["proveidor"] == "Initial document"
    assert client.get(f"{RECORDS}/{second}", headers=headers).status_code == 404
    # The present was saved first, and restoring it undoes the restore.
    safety = result["safety_backup"]
    assert result["overview"]["backups"][0]["kind"] == "pre-restore"
    client.post(f"/api/v1/backups/{safety}/restore", headers=headers)
    assert client.get(f"{RECORDS}/{second}", headers=headers).status_code == 200
    # Accounts are untouched: still signed in.
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


def test_versions_record_what_changed_since_the_previous_one(register):
    client, headers, _, _ = register
    client.post("/api/v1/backups", headers=headers)
    reference = upload(client, headers)
    upload(client, headers)
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"proveidor": "X"})
    latest = client.post("/api/v1/backups", headers=headers).json()["backups"][0]
    assert (latest["added"], latest["removed"], latest["changed"]) == (2, 0, 0)
    assert latest["author"] == "admin@example.com" and latest["kind_label"] == "Manual"


def test_a_downloaded_version_can_be_uploaded_back(register):
    client, headers, _, _ = register
    upload(client, headers)
    name = client.post("/api/v1/backups", headers=headers).json()["backups"][0]["name"]
    content = client.get(f"/api/v1/backups/{name}", headers=headers).content

    uploaded = client.post(
        "/api/v1/backups/upload", headers=headers, files={"file": ("copia.zip", content, "application/zip")}
    ).json()["backups"][0]
    assert uploaded["kind"] == "upload" and uploaded["documents"] == 1

    with zipfile.ZipFile(__import__("io").BytesIO(content)) as archive:
        raw_db = archive.read("cosecre.db")
    as_db = client.post(
        "/api/v1/backups/upload", headers=headers, files={"file": ("cosecre.db", raw_db, "application/octet-stream")}
    )
    assert as_db.status_code == 200
    bad = client.post(
        "/api/v1/backups/upload", headers=headers, files={"file": ("x.db", b"not a database", "application/octet-stream")}
    )
    assert bad.status_code == 400


def test_restore_waits_while_documents_are_being_read(register):
    client, headers, _, _ = register
    name = client.post("/api/v1/backups", headers=headers).json()["backups"][0]["name"]
    client.app.state.enrichment_running = True
    try:
        response = client.post(f"/api/v1/backups/{name}/restore", headers=headers)
    finally:
        client.app.state.enrichment_running = False
    assert response.status_code == 400 and "llegint" in response.json()["detail"]


def test_originals_missing_from_drive_are_uploaded_on_request(tmp_path):
    sheet = FakeSheets()
    client, _ = build_client(tmp_path, sheet_service=sheet, google_drive_documents_folder_id="folder-1")
    with client:
        headers = register_admin(client)
        reference = upload(client, headers)
        with client.app.state.session_factory() as session:
            document = session.query(Document).filter_by(internal_doc_number=reference).one()
            document.drive_file_id = None
            session.commit()
        sheet.drive.clear()
        report = client.post("/api/v1/documents/migration/drive", headers=headers).json()
        assert report["drive_configured"] is True
        status = client.get("/api/v1/documents/migration/status", headers=headers).json()
        assert status["drive_missing"] == 0
        assert list(sheet.drive.values())[0]["folder"] == "folder-1"
        assert sheet.row_for(reference)["file_link"].startswith("=IMAGE(")


# ── Editing ──────────────────────────────────────────────────────────────────


def test_validation_confirms_every_model_suggestion(tmp_path):
    jev = FakeJev({"tipus_document": JevAnswer("Factura", 0.95)})
    sheet = FakeSheets()
    client, _ = build_client(tmp_path, sheet_service=sheet, classifier=DocumentClassifier(jev))
    with client:
        headers = register_admin(client)
        reference = upload(client, headers)
        record = client.get(f"{RECORDS}/{reference}", headers=headers).json()
        # The vision model said "Factura simplificada", Jev is sure it is a Factura.
        assert record["tipus_document"] == "Factura"
        assert record["ai_hints"]["tipus_document"]["review"] is True
        assert record["ai_hints"]["tipus_document"]["alternative"] == "Factura simplificada"

        # The step-by-step trace: the vision proposal, Jev's answer, the outcome.
        trace = record["ai_trace"]
        assert trace["vision"]["proposal"]["tipus_document"] == "Factura simplificada"
        assert trace["vision"]["proposal"]["proveidor"] == "Initial document"  # raw, before casing
        assert trace["jev"]["status"] == "ok"
        assert trace["jev"]["answers"]["tipus_document"]["label"] == "Factura"
        assert trace["final"]["tipus_document"]["value"] == "Factura"
        assert trace["final"]["tipus_document"]["hint"]["source"] == "jev"
        assert "transcripcio" not in trace["vision"]["proposal"]  # kept apart, not duplicated

        validated = client.post(f"{RECORDS}/{reference}/validate", headers=headers).json()
        assert validated["validat"] is True
        assert not any(h["review"] for h in validated["ai_hints"].values())
        assert sheet.row_for(reference)["validat"] is True


def test_edits_reject_bad_dates_and_values_off_the_list(register):
    client, headers, _, _ = register
    reference = upload(client, headers)
    bad_date = client.patch(f"{RECORDS}/{reference}", headers=headers, json={"data_pagament": "31/02/2026"})
    assert bad_date.status_code == 422
    bad_choice = client.patch(f"{RECORDS}/{reference}", headers=headers, json={"pagament": "Potser"})
    assert bad_choice.status_code == 422
    ok = client.patch(
        f"{RECORDS}/{reference}",
        headers=headers,
        json={"data_pagament": "05/02/2026", "pagament": "pendent de pagament", "subministrat": "No aplica"},
    )
    assert ok.status_code == 200
    assert ok.json()["data_pagament"] == "2026-02-05"
    assert ok.json()["pagament"] == "Pendent de pagament"


def test_changing_date_or_number_renames_the_drive_file(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"num_factura": "A/77", "data_factura": "2026-03-02"})
    assert list(sheet.drive.values())[0]["name"] == "2026-03-02_A-77.jpg"


def test_deleting_removes_row_drive_file_and_entry(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    assert client.delete(f"{RECORDS}/{reference}", headers=headers).status_code == 204
    assert not sheet.rows and not sheet.drive
    assert client.get(f"{RECORDS}/{reference}", headers=headers).status_code == 404


def test_the_original_file_can_be_fetched_back(register):
    client, headers, _, _ = register
    reference = upload(client, headers)
    response = client.get(f"{RECORDS}/{reference}/file", headers=headers)
    assert response.status_code == 200
    assert response.content == JPEG


def test_uploads_reject_an_unsupported_content_type(register):
    client, headers, _, _ = register
    response = client.post(
        f"{RECORDS}/upload", headers=headers, files={"file": ("notes.txt", b"hi", "text/plain")}
    )
    assert response.status_code == 400


def test_an_unreadable_document_is_kept_as_an_error_and_can_be_filled_by_hand(tmp_path):
    class Broken(FakeProvider):
        def extract_file(self, request):
            from cosecre_hub.services.llm import LLMError

            raise LLMError("unreadable")

    sheet = FakeSheets()
    client, _ = build_client(tmp_path, provider=Broken(), sheet_service=sheet)
    with client:
        headers = register_admin(client)
        reference = upload(client, headers)
        record = client.get(f"{RECORDS}/{reference}", headers=headers).json()
        assert record["extraction_status"] == "error"
        saved = client.patch(f"{RECORDS}/{reference}", headers=headers, json={"proveidor": "A mà"}).json()
        assert saved["extraction_status"] == "needs_validation"
        assert sheet.row_for(reference)["proveidor"] == "A mà"


# ── Migration ────────────────────────────────────────────────────────────────


def legacy(title, rows):
    return LegacyTab(title=title, rows=[SheetRow(n, values) for n, values in rows], reference_column=9)


def test_migration_copies_both_tabs_converts_fields_and_is_idempotent(register):
    client, headers, sheet, _ = register
    sheet.legacy["Factures"] = legacy("Factures", [
        (2, {"num_doc_intern": "INV-1", "num_factura": "14/2026", "data_factura": 46106,
             "proveidor": "ELK SPORT DISTRIBUCIONES S L U", "adreca_proveidor": "C/ Sabastida 6 baixos 08031 Barcelona",
             "import_value": "185,64€", "validat": True, "file_link": '=IMAGE("https://drive.google.com/uc?export=view&id=abcdefghijkl")'}),
    ])
    sheet.legacy["Tiquets"] = legacy("Tiquets", [
        (2, {"num_doc_intern": "", "num_factura": "52211", "data_factura": "6/2/2026 9:29", "proveidor": "BASAR MERCASA"}),
        (3, {"num_doc_intern": "", "proveidor": "", "data_factura": "", "validat": True}),  # checkbox-only row
    ])

    sheet.drive["abcdefghijkl"] = {"name": "IMG_0001.jpg", "folder": "old-invoices", "bytes": JPEG}

    preview = client.get("/api/v1/documents/migration", headers=headers).json()
    assert preview["to_create"] == 2 and preview["references_generated"] == 1
    assert not sheet.rows

    result = client.post("/api/v1/documents/migration", headers=headers).json()
    assert result["created"] == 2
    records = {r["num_factura"]: r for r in client.get(RECORDS, headers=headers).json()}
    invoice = records["14/2026"]
    assert invoice["data_factura"] == "2026-03-25"
    assert invoice["proveidor"] == "Elk Sport Distribuciones S L U"
    assert (invoice["carrer"], invoice["codi_postal"], invoice["ciutat"]) == ("C/ Sabastida 6 baixos", "08031", "Barcelona")
    assert invoice["import"] == 185.64 and invoice["validat"] is True
    assert invoice["legacy_type"] == "invoice" and invoice["origen"] == "Foto"
    ticket = records["52211"]
    assert ticket["data_factura"] == "2026-02-06"
    assert sheet.legacy_references and sheet.legacy_references[0][0] == "Tiquets"

    # The Drive original was read again and filled the new fields — only those.
    assert invoice["tipus_document"] == "Factura simplificada"
    assert invoice["pagament"] == "Pagat"
    assert invoice["num_factura"] == "14/2026"  # the person's value, not the model's
    # The ticket has no original anywhere: its type comes from its old tab, flagged.
    assert ticket["tipus_document"] == "Factura simplificada"
    assert ticket["ai_hints"]["tipus_document"]["source"] == "migracio"
    # …and the Drive original moved into the one folder under its new name.
    assert sheet.drive["abcdefghijkl"]["name"] == "2026-03-25_14-2026.jpg"

    # An upload whose extraction never reached a tab is recovered from the database.
    with client.app.state.session_factory() as session:
        from cosecre_hub.models import ExtractionJob, Upload

        stranded = Upload(user_id=1, internal_doc_number="TKT-STRANDED", document_type="ticket",
                          source_file_name="t.jpg", source_file_type="image/jpeg",
                          stored_path="/nowhere/t.jpg", status="error")
        session.add(ExtractionJob(id="stranded", user_id=1, upload=stranded, status="error",
                                  extracted_payload={"proveidor": "FARMACIA", "import": "4,50"}))
        session.commit()
    recovered = client.post("/api/v1/documents/migration", headers=headers).json()
    assert recovered["from_database"] == 1 and recovered["created"] == 1
    stranded_record = client.get(f"{RECORDS}/TKT-STRANDED", headers=headers).json()
    assert stranded_record["proveidor"] == "Farmacia" and stranded_record["import"] == 4.5
    assert sheet.row_for("TKT-STRANDED")["proveidor"] == "Farmacia"

    again = client.post("/api/v1/documents/migration", headers=headers).json()
    assert again["created"] == 0 and again["already_migrated"] == 2
    assert len(sheet.rows) == 3


# ── Backups ──────────────────────────────────────────────────────────────────


def test_backups_hold_the_database_and_a_readable_register(register):
    client, headers, _, _ = register
    upload(client, headers)
    created = client.post("/api/v1/backups", headers=headers).json()
    assert len(created["backups"]) == 1
    name = created["backups"][0]["name"]

    download = client.get(f"/api/v1/backups/{name}", headers=headers)
    assert download.status_code == 200
    path = client.app.state.backup_service.path_for(name)
    with zipfile.ZipFile(path) as archive:
        assert {"cosecre.db", "registre.json", "registre.csv", "manifest.json"} <= set(archive.namelist())
        csv_text = archive.read("registre.csv").decode("utf-8-sig")
        assert "Núm. doc. intern;Tipus document" in csv_text
        assert "31/01/2026" in csv_text and "100,00" in csv_text

    assert client.get("/api/v1/backups/../../etc/passwd", headers=headers).status_code == 404


def test_backups_are_pruned_and_only_taken_when_due(register):
    client, headers, _, _ = register
    service = client.app.state.backup_service
    service.settings.backup_keep = 2
    import time

    for _ in range(3):
        service.create("test")
        time.sleep(1.1)  # names have one-second resolution
    assert len(service.list()) == 2
    assert service.due() is False
    upload(client, headers)
    assert service.changed_since_last() is True


# ── Responsible person ───────────────────────────────────────────────────────

PEOPLE = "/api/v1/documents/responsables"


def test_responsible_person_is_saved_remembered_and_reaches_the_sheet(register):
    client, headers, sheet, _ = register
    reference = upload(client, headers)
    response = client.patch(
        f"{RECORDS}/{reference}",
        headers=headers,
        json={"responsable_nom": "  Susana   Pérez ", "responsable_email": "SPerez@XTEC.cat"},
    )
    assert response.status_code == 200, response.text
    record = response.json()
    assert (record["responsable_nom"], record["responsable_email"]) == ("Susana Pérez", "sperez@xtec.cat")
    assert sheet.row_for(reference)["responsable_nom"] == "Susana Pérez"
    assert sheet.row_for(reference)["responsable_email"] == "sperez@xtec.cat"

    everyone = client.get(PEOPLE, headers=headers).json()
    assert everyone["matches"] == [{"nom": "Susana Pérez", "email": "sperez@xtec.cat"}]
    assert client.get(PEOPLE, headers=headers, params={"q": "per"}).json()["matches"][0]["nom"] == "Susana Pérez"
    by_email = client.get(PEOPLE, headers=headers, params={"field": "email", "q": "sper"}).json()
    assert by_email["matches"][0]["email"] == "sperez@xtec.cat"


def test_only_xtec_addresses_are_accepted(register):
    client, headers, _, _ = register
    reference = upload(client, headers)
    for bad in ("susana@gmail.com", "susana@xtec.cat.com", "no és un email"):
        response = client.patch(f"{RECORDS}/{reference}", headers=headers, json={"responsable_email": bad})
        assert response.status_code == 422, bad
    ok = client.patch(f"{RECORDS}/{reference}", headers=headers, json={"responsable_email": ""})
    assert ok.status_code == 200


def test_an_obvious_typo_of_a_known_name_gets_a_suggestion(register):
    client, headers, _, _ = register
    reference = upload(client, headers)
    client.patch(f"{RECORDS}/{reference}", headers=headers, json={"responsable_nom": "Susana Pérez"})

    def suggestion(q, field="nom"):
        return client.get(PEOPLE, headers=headers, params={"q": q, "field": field}).json()["suggestion"]

    assert suggestion("Susna")["nom"] == "Susana Pérez"
    assert suggestion("Susana Peerz")["nom"] == "Susana Pérez"
    assert suggestion("susana perez") is None  # the same person, not a typo
    assert suggestion("Ana") is None  # too short to second-guess
    assert suggestion("Marta") is None


def test_edit_distance_counts_a_swap_as_one():
    from cosecre_hub.services.people import edit_distance

    assert edit_distance("susana", "susna") == 1
    assert edit_distance("perez", "peerz") == 1
    assert edit_distance("marta", "susana") > 2
