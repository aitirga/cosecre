from __future__ import annotations

from collections.abc import Iterator
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
    LLMError,
    LLMNotConfigured,
    LLMProvider,
    LLMRegistry,
    StreamEvent,
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
    streams: list[CompletionRequest] = field(default_factory=list)
    #: `(mime_type, bytes)` for every image the provider was handed, read while
    #: the request was still in flight. Recorded here rather than checked by the
    #: test afterwards because the gateway's temp files are gone by then — which
    #: is the point of them, and its own assertion.
    seen_images: list[tuple[str, bytes]] = field(default_factory=list)
    #: How many `delta` frames one answer arrives in.
    stream_chunks: int = 3
    #: Set to make the stream die partway, which is the case worth testing.
    stream_error: str | None = None

    def is_configured(self) -> bool:
        return self.configured

    def default_model(self) -> str:
        return "fake-model-1"

    def known_models(self) -> list[str]:
        return ["fake-model-1", "fake-model-2"]

    def _guard(self) -> None:
        if not self.configured:
            raise LLMNotConfigured("The fake provider has no credentials.")

    def _read_attachments(self, request) -> None:
        """Open every attachment now, the way a real provider would."""
        for message in request.messages:
            for item in message.attachments:
                self.seen_images.append((item.mime_type, item.path.read_bytes()))

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self._guard()
        self._read_attachments(request)
        self.completions.append(request)
        return CompletionResult(
            text=self.text,
            model=request.model or self.default_model(),
            provider=self.id,
            usage=Usage(input_tokens=11, output_tokens=7, total_tokens=18),
        )

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        """Answer in pieces, so a test can see the frames arrive in order.

        Overriding rather than inheriting the base default on purpose: the
        default answers in one shot, which would hide any ordering bug in the
        endpoint that assembles these.
        """
        self._guard()
        self._read_attachments(request)
        self.streams.append(request)
        for index, part in enumerate(_split(self.text, self.stream_chunks)):
            if index == 1 and self.stream_error:
                raise LLMError(self.stream_error)
            yield StreamEvent(type="delta", text=part)
        yield StreamEvent(
            type="completed",
            text=self.text,
            usage=Usage(input_tokens=11, output_tokens=7, total_tokens=18),
            model=request.model or self.default_model(),
            provider=self.id,
        )

    def structured(self, request: StructuredRequest) -> StructuredResult:
        self._guard()
        self._read_attachments(request)
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


def _split(text: str, parts: int) -> list[str]:
    size = max(1, -(-len(text) // parts))
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


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
