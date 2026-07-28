from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cosecre_hub.config import Settings
from cosecre_hub.main import create_app
from cosecre_hub.services.llm import (
    CompletionRequest,
    CompletionResult,
    FileExtractionRequest,
    LLMNotConfigured,
    LLMProvider,
    LLMRegistry,
    StructuredRequest,
    StructuredResult,
    Usage,
)

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "supersecure"


@dataclass
class FakeProvider(LLMProvider):
    """A provider that answers instantly and records what it was asked.

    Every test that touches a model goes through this rather than the network,
    which is only possible because the registry is injected into ``create_app``.
    """

    id: str = "fake"
    label: str = "Fake"
    configured: bool = True
    text: str = "hello from the fake provider"
    structured_payload: dict[str, Any] = field(default_factory=lambda: {"answer": 42})
    completions: list[CompletionRequest] = field(default_factory=list)
    structures: list[StructuredRequest] = field(default_factory=list)
    extractions: list[FileExtractionRequest] = field(default_factory=list)

    def is_configured(self) -> bool:
        return self.configured

    def default_model(self) -> str:
        return "fake-model-1"

    def known_models(self) -> list[str]:
        return ["fake-model-1", "fake-model-2"]

    def _guard(self) -> None:
        if not self.configured:
            raise LLMNotConfigured("The fake provider has no credentials.")

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self._guard()
        self.completions.append(request)
        return CompletionResult(
            text=self.text,
            model=request.model or self.default_model(),
            provider=self.id,
            usage=Usage(input_tokens=11, output_tokens=7, total_tokens=18),
        )

    def structured(self, request: StructuredRequest) -> StructuredResult:
        self._guard()
        self.structures.append(request)
        return StructuredResult(
            data=dict(self.structured_payload),
            model=request.model or self.default_model(),
            provider=self.id,
            usage=Usage(total_tokens=5),
        )

    def extract_file(self, request: FileExtractionRequest) -> StructuredResult:
        self._guard()
        self.extractions.append(request)
        # The documents module asks for `<type>_extraction`, and the values are
        # tagged with the type so a test can prove invoices and tickets do not
        # cross over.
        document_type = request.schema_name.removesuffix("_extraction") or "invoice"
        prefix = "F" if document_type == "invoice" else "T"
        return StructuredResult(
            data={
                "num_factura": f"{prefix}-2026-001",
                "data_factura": "2026-01-31",
                "proveidor": f"Initial {document_type}",
                "cif_proveidor": "",
                "adreca_proveidor": "",
                "import": 100.0,
                "cif_proveit": "",
                "descripcio": "",
                "pressupost_afectat": "",
            },
            model=request.model or self.default_model(),
            provider=self.id,
            usage=Usage(total_tokens=9),
        )


def build_settings(tmp_path: Path, **overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "secret_key": "test-secret-with-at-least-thirty-two-bytes",
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        "upload_dir": tmp_path / "uploads",
        "seed_users_file": None,
        "bootstrap_admin_email": None,
        "bootstrap_admin_password": None,
        "openai_api_key": None,
    }
    defaults.update(overrides)
    # `_env_file=None` keeps a developer's real hub/.env out of the test run.
    return Settings(_env_file=None, **defaults)


def build_client(
    tmp_path: Path, *, provider: FakeProvider | None = None, **overrides: Any
) -> tuple[TestClient, FakeProvider]:
    fake = provider or FakeProvider()
    settings = build_settings(tmp_path, **overrides)
    return TestClient(create_app(settings, llm_registry=LLMRegistry([fake]))), fake


@pytest.fixture
def hub(tmp_path: Path):
    """A running hub with a fake model provider, as ``(client, provider)``."""
    client, provider = build_client(tmp_path)
    with client:
        yield client, provider


def register_admin(client: TestClient, email: str = ADMIN_EMAIL) -> dict[str, str]:
    """Create the first account — which the hub makes an admin — and return its headers."""
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": ADMIN_PASSWORD, "client": "pytest"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
