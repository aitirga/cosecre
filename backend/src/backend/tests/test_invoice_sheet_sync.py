from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import document_routes
from backend.config import Settings
from backend.main import create_app
from backend.models import ExtractionJob
from backend.schemas import InvoiceExtraction, InvoiceRecord
from backend.services.sheets_service import SheetWriteResult


def build_test_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        secret_key="test-secret-with-at-least-thirty-two-bytes",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        seed_users_file=tmp_path / "seed_users.json",
        openai_api_key="test-key",
    )
    return TestClient(create_app(settings))


def register_admin(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": "admin@example.com", "password": "supersecure"},
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def install_fake_sheet(monkeypatch):
    sheet_rows: dict[str, dict[str, InvoiceRecord]] = {"invoice": {}, "ticket": {}}
    next_row_numbers = {"invoice": 2, "ticket": 2}

    def fake_extract_document(
        self,
        _file_path,
        _mime_type,
        internal_doc_number: str,
        _model,
        *_args,
        document_type: str = "invoice",
        **_kwargs,
    ):
        prefix = "F" if document_type == "invoice" else "T"
        return InvoiceExtraction(
            num_factura=f"{prefix}-2026-001",
            proveidor=f"Initial {document_type}",
            import_value="100.00",
        )

    def fake_is_ready(self, _workspace, _document_type="invoice"):
        return True

    def fake_list_documents(self, _workspace, document_type: str):
        return [
            record.model_copy(
                update={
                    "sheet_row_ref": record.sheet_row_ref,
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
        sheet_rows[document_type][invoice.num_doc_intern] = InvoiceRecord.model_validate(payload).model_copy(
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

    monkeypatch.setattr(
        document_routes.OpenAIExtractionService,
        "extract_document",
        fake_extract_document,
    )
    monkeypatch.setattr(document_routes.GoogleSheetsService, "is_ready", fake_is_ready)
    monkeypatch.setattr(document_routes.GoogleSheetsService, "list_documents", fake_list_documents)
    monkeypatch.setattr(document_routes.GoogleSheetsService, "append_document", fake_append_document)
    monkeypatch.setattr(document_routes.GoogleSheetsService, "update_document", fake_update_document)
    monkeypatch.setattr(document_routes.GoogleSheetsService, "delete_document", fake_delete_document)

    return sheet_rows


def upload_document(
    client: TestClient,
    headers: dict[str, str],
    endpoint: str,
    filename: str,
) -> str:
    response = client.post(
        f"/api/{endpoint}/upload",
        headers=headers,
        files={"file": (filename, b"fake-image", "image/jpeg")},
    )
    assert response.status_code == 200
    payload = response.json()
    document_routes.process_job(client.app, payload["job_id"])
    session = client.app.state.session_factory()
    try:
        job = session.get(ExtractionJob, payload["job_id"])
        assert job is not None
        assert job.error_message is None, job.error_message
    finally:
        session.close()
    return payload["internal_doc_number"]


def wait_for_sheet_row(sheet_rows: dict[str, dict[str, InvoiceRecord]], document_type: str, internal_doc_number: str):
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if internal_doc_number in sheet_rows[document_type]:
            return
        time.sleep(0.01)
    raise AssertionError(f"{internal_doc_number} was not written to the {document_type} sheet")


def test_processed_upload_is_written_to_sheet_and_listed(tmp_path: Path, monkeypatch):
    sheet_rows = install_fake_sheet(monkeypatch)

    with build_test_client(tmp_path) as client:
        headers = register_admin(client)
        internal_doc_number = upload_document(client, headers, "invoices", "invoice.jpg")

        wait_for_sheet_row(sheet_rows, "invoice", internal_doc_number)

        response = client.get("/api/invoices", headers=headers)
        assert response.status_code == 200
        payload = response.json()

        assert [item["num_doc_intern"] for item in payload] == [internal_doc_number]
        assert payload[0]["proveidor"] == "Initial invoice"
        assert payload[0]["document_type"] == "invoice"
        assert payload[0]["extraction_status"] == "needs_validation"


def test_sheet_and_app_changes_stay_in_sync(tmp_path: Path, monkeypatch):
    sheet_rows = install_fake_sheet(monkeypatch)

    with build_test_client(tmp_path) as client:
        headers = register_admin(client)
        internal_doc_number = upload_document(client, headers, "invoices", "invoice.jpg")
        wait_for_sheet_row(sheet_rows, "invoice", internal_doc_number)

        sheet_rows["invoice"][internal_doc_number] = sheet_rows["invoice"][internal_doc_number].model_copy(
            update={
                "proveidor": "Edited in sheet",
                "validat": True,
                "extraction_status": "validated",
            }
        )

        response = client.get("/api/invoices", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload[0]["proveidor"] == "Edited in sheet"
        assert payload[0]["validat"] is True
        assert payload[0]["extraction_status"] == "validated"

        patch_response = client.patch(
            f"/api/invoices/{internal_doc_number}",
            headers=headers,
            json={"proveidor": "Edited in app", "validat": False},
        )
        assert patch_response.status_code == 200
        assert sheet_rows["invoice"][internal_doc_number].proveidor == "Edited in app"
        assert sheet_rows["invoice"][internal_doc_number].validat is False

        del sheet_rows["invoice"][internal_doc_number]

        deleted_response = client.get("/api/invoices", headers=headers)
        assert deleted_response.status_code == 200
        assert deleted_response.json() == []


def test_tickets_use_their_own_sheet_stream(tmp_path: Path, monkeypatch):
    sheet_rows = install_fake_sheet(monkeypatch)

    with build_test_client(tmp_path) as client:
        headers = register_admin(client)
        internal_doc_number = upload_document(client, headers, "tickets", "ticket.jpg")

        wait_for_sheet_row(sheet_rows, "ticket", internal_doc_number)
        assert sheet_rows["invoice"] == {}

        response = client.get("/api/tickets", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert [item["num_doc_intern"] for item in payload] == [internal_doc_number]
        assert payload[0]["document_type"] == "ticket"
        assert payload[0]["proveidor"] == "Initial ticket"
