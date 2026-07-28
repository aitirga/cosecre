from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from conftest import register_admin

from cosecre_hub.api.documents import routes
from cosecre_hub.models import ExtractionJob, Upload, User
from cosecre_hub.schemas import InvoiceExtraction, InvoiceRecord
from cosecre_hub.services.sheets import SheetWriteResult


def install_fake_sheet(monkeypatch) -> dict[str, dict[str, InvoiceRecord]]:
    """Stand in for Google Sheets with a dict, keyed by document type.

    Only the six methods the routes actually call are replaced, so a change to
    the real service's surface still shows up as a failure here.
    """
    sheet_rows: dict[str, dict[str, InvoiceRecord]] = {"invoice": {}, "ticket": {}}
    next_row_numbers = {"invoice": 2, "ticket": 2}

    def fake_is_ready(self, _workspace, _document_type="invoice"):
        return True

    def fake_list_documents(self, _workspace, document_type: str):
        return [
            record.model_copy(
                update={
                    "extraction_status": "validated" if record.validat else "needs_validation",
                }
            )
            for record in sheet_rows[document_type].values()
        ]

    def fake_append_document(self, _workspace, document_type: str, invoice: InvoiceExtraction):
        row_number = next_row_numbers[document_type]
        next_row_numbers[document_type] += 1
        payload = invoice.model_dump(by_alias=False)
        payload_document_type = payload.pop("document_type", document_type)
        sheet_rows[document_type][invoice.num_doc_intern] = InvoiceRecord.model_validate(
            payload
        ).model_copy(
            update={
                "document_type": payload_document_type,
                "validat": False,
                "extraction_status": "needs_validation",
                "sheet_row_ref": row_number,
            }
        )
        return SheetWriteResult(row_number=row_number)

    def fake_update_document(self, _workspace, document_type: str, invoice: InvoiceRecord):
        existing = sheet_rows[document_type][invoice.num_doc_intern]
        sheet_rows[document_type][invoice.num_doc_intern] = invoice.model_copy(
            update={
                "sheet_row_ref": existing.sheet_row_ref,
                "extraction_status": "validated" if invoice.validat else "needs_validation",
            }
        )
        return SheetWriteResult(row_number=existing.sheet_row_ref or 2)

    def fake_delete_document(self, _workspace, document_type: str, internal_doc_number: str):
        sheet_rows[document_type].pop(internal_doc_number, None)

    def fake_upload_to_drive(self, _path, _name, _mime, folder_id=None):
        return "https://drive.example/file", "drive-file-id"

    monkeypatch.setattr(routes.GoogleSheetsService, "is_ready", fake_is_ready)
    monkeypatch.setattr(routes.GoogleSheetsService, "list_documents", fake_list_documents)
    monkeypatch.setattr(routes.GoogleSheetsService, "append_document", fake_append_document)
    monkeypatch.setattr(routes.GoogleSheetsService, "update_document", fake_update_document)
    monkeypatch.setattr(routes.GoogleSheetsService, "delete_document", fake_delete_document)
    monkeypatch.setattr(routes.GoogleSheetsService, "upload_file_to_drive", fake_upload_to_drive)

    return sheet_rows


def upload_document(
    client: TestClient, headers: dict[str, str], segment: str, filename: str
) -> str:
    response = client.post(
        f"/api/v1/documents/{segment}/upload",
        headers=headers,
        files={"file": (filename, b"fake-image", "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    # The route queues this as a background task; running it inline keeps the
    # assertions deterministic.
    routes.process_job(client.app, payload["job_id"])

    session = client.app.state.session_factory()
    try:
        job = session.get(ExtractionJob, payload["job_id"])
        assert job is not None
        assert job.error_message is None, job.error_message
    finally:
        session.close()
    return payload["internal_doc_number"]


def test_processed_upload_is_written_to_the_sheet_and_listed(hub, monkeypatch):
    client, provider = hub
    sheet_rows = install_fake_sheet(monkeypatch)
    headers = register_admin(client)

    internal_doc_number = upload_document(client, headers, "invoices", "invoice.jpg")

    assert internal_doc_number in sheet_rows["invoice"]
    response = client.get("/api/v1/documents/invoices", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert [item["num_doc_intern"] for item in payload] == [internal_doc_number]
    assert payload[0]["proveidor"] == "Initial invoice"
    assert payload[0]["import"] == 100.0
    assert payload[0]["extraction_status"] == "needs_validation"
    # Extraction went through the gateway, not a provider SDK in the route.
    assert provider.extractions[0].schema_name == "invoice_extraction"


def test_reference_numbers_are_prefixed_per_document_type(hub, monkeypatch):
    client, _ = hub
    install_fake_sheet(monkeypatch)
    headers = register_admin(client)

    invoice_ref = upload_document(client, headers, "invoices", "invoice.jpg")
    ticket_ref = upload_document(client, headers, "tickets", "ticket.jpg")

    assert invoice_ref.startswith("INV-")
    assert ticket_ref.startswith("TKT-")


def test_sheet_and_app_changes_stay_in_sync(hub, monkeypatch):
    client, _ = hub
    sheet_rows = install_fake_sheet(monkeypatch)
    headers = register_admin(client)
    internal_doc_number = upload_document(client, headers, "invoices", "invoice.jpg")

    # An edit made directly in the spreadsheet wins on the next read.
    sheet_rows["invoice"][internal_doc_number] = sheet_rows["invoice"][
        internal_doc_number
    ].model_copy(update={"proveidor": "Edited in sheet", "validat": True})

    payload = client.get("/api/v1/documents/invoices", headers=headers).json()
    assert payload[0]["proveidor"] == "Edited in sheet"
    assert payload[0]["validat"] is True
    assert payload[0]["extraction_status"] == "validated"

    # And an edit made in the app is pushed back out.
    patched = client.patch(
        f"/api/v1/documents/invoices/{internal_doc_number}",
        headers=headers,
        json={"proveidor": "Edited in app", "validat": False},
    )
    assert patched.status_code == 200
    assert sheet_rows["invoice"][internal_doc_number].proveidor == "Edited in app"
    assert sheet_rows["invoice"][internal_doc_number].validat is False

    del sheet_rows["invoice"][internal_doc_number]
    assert client.get("/api/v1/documents/invoices", headers=headers).json() == []


def test_validating_marks_the_row_in_both_places(hub, monkeypatch):
    client, _ = hub
    sheet_rows = install_fake_sheet(monkeypatch)
    headers = register_admin(client)
    internal_doc_number = upload_document(client, headers, "invoices", "invoice.jpg")

    response = client.post(
        f"/api/v1/documents/invoices/{internal_doc_number}/validate", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["validat"] is True
    assert sheet_rows["invoice"][internal_doc_number].validat is True

    job = client.get(
        f"/api/v1/documents/invoices/jobs/{_job_id(client, internal_doc_number)}", headers=headers
    ).json()
    assert job["status"] == "validated"


def test_tickets_use_their_own_sheet_stream(hub, monkeypatch):
    client, _ = hub
    sheet_rows = install_fake_sheet(monkeypatch)
    headers = register_admin(client)

    internal_doc_number = upload_document(client, headers, "tickets", "ticket.jpg")

    assert internal_doc_number in sheet_rows["ticket"]
    assert sheet_rows["invoice"] == {}
    payload = client.get("/api/v1/documents/tickets", headers=headers).json()
    assert [item["num_doc_intern"] for item in payload] == [internal_doc_number]
    assert payload[0]["document_type"] == "ticket"
    assert payload[0]["proveidor"] == "Initial ticket"


def test_deleting_removes_the_row_and_the_local_record(hub, monkeypatch):
    client, _ = hub
    sheet_rows = install_fake_sheet(monkeypatch)
    headers = register_admin(client)
    internal_doc_number = upload_document(client, headers, "invoices", "invoice.jpg")

    deleted = client.delete(
        f"/api/v1/documents/invoices/{internal_doc_number}", headers=headers
    )

    assert deleted.status_code == 204
    assert sheet_rows["invoice"] == {}
    assert client.get("/api/v1/documents/invoices", headers=headers).json() == []


def test_the_original_file_can_be_fetched_back(hub, monkeypatch):
    client, _ = hub
    install_fake_sheet(monkeypatch)
    headers = register_admin(client)
    internal_doc_number = upload_document(client, headers, "invoices", "invoice.jpg")

    response = client.get(
        f"/api/v1/documents/invoices/{internal_doc_number}/file", headers=headers
    )

    assert response.status_code == 200
    assert response.content == b"fake-image"


def test_an_in_flight_job_is_listed_before_it_reaches_the_sheet(hub, monkeypatch):
    client, _ = hub
    install_fake_sheet(monkeypatch)
    headers = register_admin(client)
    # The rows are written directly rather than by uploading: TestClient drains
    # background tasks before returning, so a real upload is already finished by
    # the time the response arrives, and this state would never be observable.
    internal_doc_number = _insert_pending_job(client, "invoices-in-flight.jpg")

    payload = client.get("/api/v1/documents/invoices", headers=headers).json()

    assert [item["num_doc_intern"] for item in payload] == [internal_doc_number]
    assert payload[0]["extraction_status"] == "pending"
    assert payload[0]["source_file_name"] == "invoices-in-flight.jpg"
    assert payload[0]["file_url"] == f"/documents/invoices/{internal_doc_number}/file"


def test_uploads_reject_an_unsupported_content_type(hub, monkeypatch):
    client, _ = hub
    install_fake_sheet(monkeypatch)
    headers = register_admin(client)

    response = client.post(
        "/api/v1/documents/invoices/upload",
        headers=headers,
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 400


def test_workspace_settings_round_trip(hub):
    client, _ = hub
    headers = register_admin(client)

    updated = client.put(
        "/api/v1/documents/settings",
        headers=headers,
        json={
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
            "sheet_name": "Factures",
            "ticket_sheet_name": "Tiquets",
            "openai_model": "gpt-5.4",
            "extraction_prompt": "Use the schema.",
            "polling_interval_seconds": 30,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["sheet_name"] == "Factures"
    assert client.get("/api/v1/documents/settings", headers=headers).json()[
        "ticket_sheet_name"
    ] == "Tiquets"


def test_only_admins_can_change_workspace_settings(hub):
    client, _ = hub
    admin_headers = register_admin(client)
    client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": "staff@example.com", "password": "staff-password"},
    )
    staff_token = client.post(
        "/api/v1/auth/login", json={"email": "staff@example.com", "password": "staff-password"}
    ).json()["access_token"]
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    # Readable, because clients pace their polling from it.
    assert client.get("/api/v1/documents/settings", headers=staff_headers).status_code == 200
    assert (
        client.put(
            "/api/v1/documents/settings",
            headers=staff_headers,
            json={"sheet_name": "Nope", "openai_model": "gpt-5.4"},
        ).status_code
        == 403
    )


def _job_id(client: TestClient, internal_doc_number: str) -> str:
    session = client.app.state.session_factory()
    try:
        upload = (
            session.query(Upload)
            .filter(Upload.internal_doc_number == internal_doc_number)
            .first()
        )
        assert upload is not None and upload.job is not None
        return upload.job.id
    finally:
        session.close()


def _insert_pending_job(client: TestClient, filename: str) -> str:
    """An upload that has been accepted but not yet extracted."""
    internal_doc_number = routes.generate_internal_doc_number("invoice")
    stored_path = client.app.state.settings.upload_dir / f"{internal_doc_number}-{filename}"
    stored_path.write_bytes(b"fake-image")

    session = client.app.state.session_factory()
    try:
        user = session.query(User).first()
        assert user is not None
        upload = Upload(
            user_id=user.id,
            internal_doc_number=internal_doc_number,
            document_type="invoice",
            source_file_name=filename,
            source_file_type="image/jpeg",
            stored_path=str(stored_path),
            status="pending",
        )
        session.add(upload)
        session.flush()
        session.add(
            ExtractionJob(id=str(uuid4()), user_id=user.id, upload_id=upload.id, status="pending")
        )
        session.commit()
    finally:
        session.close()
    return internal_doc_number
