from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import invoices as invoices_api
from backend.config import Settings
from backend.main import create_app
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
    sheet_rows: dict[str, InvoiceRecord] = {}
    next_row_number = 2

    def fake_extract_invoice(self, _file_path, _mime_type, internal_doc_number: str, *_args, **_kwargs):
        return InvoiceExtraction(
            num_factura="F-2026-001",
            proveidor="Initial vendor",
            import_value="100.00",
            num_doc_intern=internal_doc_number,
        )

    def fake_is_ready(self, _workspace):
        return True

    def fake_list_invoices(self, _workspace):
        return [
            record.model_copy(
                update={
                    "sheet_row_ref": record.sheet_row_ref,
                    "extraction_status": "validated" if record.validat else "needs_validation",
                }
            )
            for record in sheet_rows.values()
        ]

    def fake_append_invoice(self, _workspace, invoice: InvoiceExtraction):
        nonlocal next_row_number
        row_number = next_row_number
        next_row_number += 1
        sheet_rows[invoice.num_doc_intern] = InvoiceRecord(
            **invoice.model_dump(by_alias=False),
            validat=False,
            extraction_status="needs_validation",
            sheet_row_ref=row_number,
        )
        return SheetWriteResult(row_number=row_number)

    def fake_update_invoice(self, _workspace, invoice: InvoiceRecord):
        existing = sheet_rows[invoice.num_doc_intern]
        sheet_rows[invoice.num_doc_intern] = invoice.model_copy(
            update={
                "sheet_row_ref": existing.sheet_row_ref,
                "extraction_status": "validated" if invoice.validat else "needs_validation",
            }
        )
        return SheetWriteResult(row_number=existing.sheet_row_ref or 2)

    def fake_delete_invoice(self, _workspace, internal_doc_number: str):
        sheet_rows.pop(internal_doc_number, None)

    monkeypatch.setattr(invoices_api.OpenAIExtractionService, "extract_invoice", fake_extract_invoice)
    monkeypatch.setattr(invoices_api.GoogleSheetsService, "is_ready", fake_is_ready)
    monkeypatch.setattr(invoices_api.GoogleSheetsService, "list_invoices", fake_list_invoices)
    monkeypatch.setattr(invoices_api.GoogleSheetsService, "append_invoice", fake_append_invoice)
    monkeypatch.setattr(invoices_api.GoogleSheetsService, "update_invoice", fake_update_invoice)
    monkeypatch.setattr(invoices_api.GoogleSheetsService, "delete_invoice", fake_delete_invoice)

    return sheet_rows


def upload_invoice(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/invoices/upload",
        headers=headers,
        files={"file": ("invoice.jpg", b"fake-image", "image/jpeg")},
    )
    assert response.status_code == 200
    return response.json()["internal_doc_number"]


def test_processed_upload_is_written_to_sheet_and_listed(tmp_path: Path, monkeypatch):
    sheet_rows = install_fake_sheet(monkeypatch)

    with build_test_client(tmp_path) as client:
        headers = register_admin(client)
        internal_doc_number = upload_invoice(client, headers)

        assert internal_doc_number in sheet_rows

        response = client.get("/api/invoices", headers=headers)
        assert response.status_code == 200
        payload = response.json()

        assert [item["num_doc_intern"] for item in payload] == [internal_doc_number]
        assert payload[0]["proveidor"] == "Initial vendor"
        assert payload[0]["extraction_status"] == "needs_validation"


def test_sheet_and_app_changes_stay_in_sync(tmp_path: Path, monkeypatch):
    sheet_rows = install_fake_sheet(monkeypatch)

    with build_test_client(tmp_path) as client:
        headers = register_admin(client)
        internal_doc_number = upload_invoice(client, headers)

        sheet_rows[internal_doc_number] = sheet_rows[internal_doc_number].model_copy(
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
        assert sheet_rows[internal_doc_number].proveidor == "Edited in app"
        assert sheet_rows[internal_doc_number].validat is False

        del sheet_rows[internal_doc_number]

        deleted_response = client.get("/api/invoices", headers=headers)
        assert deleted_response.status_code == 200
        assert deleted_response.json() == []
