from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from pydantic import BaseModel

from backend.config import Settings
from backend.main import create_app
from backend.schemas import InvoiceExtraction
from backend.services import openai_service as openai_service_module
from backend.services.openai_service import OpenAIExtractionService


def build_settings(tmp_path: Path, openai_api_key: str | None = "test-key") -> Settings:
    return Settings(
        secret_key="test-secret-with-at-least-thirty-two-bytes",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        seed_users_file=tmp_path / "seed_users.json",
        openai_api_key=openai_api_key,
    )


def test_healthcheck_returns_ok(tmp_path: Path):
    settings = build_settings(tmp_path)

    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openai_service_requires_api_key(tmp_path: Path):
    settings = build_settings(tmp_path, openai_api_key=None)
    invoice_file = tmp_path / "invoice.jpg"
    invoice_file.write_bytes(b"fake-image")

    service = OpenAIExtractionService(settings)

    with pytest.raises(RuntimeError, match="OpenAI API key is not configured"):
        service.extract_invoice(
            file_path=invoice_file,
            mime_type="image/jpeg",
            internal_doc_number="INV-001",
            model="gpt-5.4",
        )


def test_openai_service_extracts_images_without_uploading_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    invoice_file = tmp_path / "invoice.jpg"
    invoice_file.write_bytes(b"fake-image")
    settings = build_settings(tmp_path)
    file_calls: list[dict[str, str]] = []
    parse_calls: list[dict[str, object]] = []
    parsed_payload = InvoiceExtraction(num_factura="F-123", proveidor="Vendor", num_doc_intern="")

    class FakeFilesApi:
        def create(self, *, file, purpose: str):
            file_calls.append({"name": Path(file.name).name, "purpose": purpose})
            return type("UploadedFile", (), {"id": "file-123"})()

    class FakeResponsesApi:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return type("ParsedResponse", (), {"output_parsed": parsed_payload})()

    class FakeClient:
        def __init__(self, api_key: str):
            assert api_key == "test-key"
            self.files = FakeFilesApi()
            self.responses = FakeResponsesApi()

    monkeypatch.setattr(openai_service_module, "OpenAI", FakeClient)

    result = OpenAIExtractionService(settings).extract_invoice(
        file_path=invoice_file,
        mime_type="image/jpeg",
        internal_doc_number="INV-001",
        model="gpt-5.4",
        prompt_override="Double check supplier fields.",
    )

    assert file_calls == []
    assert len(parse_calls) == 1
    parse_call = parse_calls[0]
    assert parse_call["model"] == "gpt-5.4"
    assert "Double check supplier fields." in str(parse_call["instructions"])

    content = parse_call["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert "INV-001" in content[0]["text"]
    assert content[1]["type"] == "input_image"
    assert str(content[1]["image_url"]).startswith("data:image/jpeg;base64,")
    assert result.num_doc_intern == "INV-001"
    assert result.num_factura == "F-123"


def test_openai_service_uploads_pdfs_before_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    invoice_file = tmp_path / "invoice.pdf"
    invoice_file.write_bytes(b"%PDF-1.4 fake")
    settings = build_settings(tmp_path)
    file_calls: list[dict[str, str]] = []
    parse_calls: list[dict[str, object]] = []

    class FakeFilesApi:
        def create(self, *, file, purpose: str):
            file_calls.append({"name": Path(file.name).name, "purpose": purpose})
            return type("UploadedFile", (), {"id": "file-456"})()

    class FakeResponsesApi:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return type(
                "ParsedResponse",
                (),
                {"output_parsed": InvoiceExtraction(num_factura="PDF-1", num_doc_intern="")},
            )()

    class FakeClient:
        def __init__(self, api_key: str):
            assert api_key == "test-key"
            self.files = FakeFilesApi()
            self.responses = FakeResponsesApi()

    monkeypatch.setattr(openai_service_module, "OpenAI", FakeClient)

    result = OpenAIExtractionService(settings).extract_invoice(
        file_path=invoice_file,
        mime_type="application/pdf",
        internal_doc_number="INV-PDF-1",
        model="gpt-5.4",
    )

    assert file_calls == [{"name": "invoice.pdf", "purpose": "user_data"}]
    assert len(parse_calls) == 1
    content = parse_calls[0]["input"][0]["content"]
    assert content[1] == {"type": "input_file", "file_id": "file-456"}
    assert result.num_doc_intern == "INV-PDF-1"


def test_openai_live_connection_smoke():
    api_key = os.getenv("COSECRE_OPENAI_API_KEY")
    if not api_key or os.getenv("COSECRE_RUN_OPENAI_LIVE_TEST") != "1":
        pytest.skip("Set COSECRE_OPENAI_API_KEY and COSECRE_RUN_OPENAI_LIVE_TEST=1 to run the live OpenAI smoke test.")

    model = os.getenv("COSECRE_OPENAI_LIVE_MODEL", "gpt-5.4-mini")

    class LiveConnectionPayload(BaseModel):
        status: str

    client = OpenAI(api_key=api_key)
    response = client.responses.parse(
        model=model,
        input="Reply with a JSON object whose status field is exactly 'ok'.",
        text_format=LiveConnectionPayload,
    )

    assert response.output_parsed is not None
    assert response.output_parsed.status == "ok"
