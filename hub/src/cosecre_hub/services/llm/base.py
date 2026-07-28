"""Provider-agnostic LLM contract.

Client apps never hold a model API key: they ask the hub, the hub asks the
provider. Everything a provider must implement is in this file, so adding
Anthropic or a local model means one new module and one registry entry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]


class LLMError(RuntimeError):
    """A model call failed for a reason the caller can be told about."""


class LLMNotConfigured(LLMError):
    """The provider exists but has no credentials, so it cannot be used."""


@dataclass(slots=True)
class Message:
    role: Role
    content: str


@dataclass(slots=True)
class CompletionRequest:
    messages: list[Message]
    instructions: str | None = None
    model: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None


@dataclass(slots=True)
class StructuredRequest:
    messages: list[Message]
    schema_name: str
    json_schema: dict[str, Any]
    instructions: str | None = None
    model: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None


@dataclass(slots=True)
class FileExtractionRequest:
    """Structured extraction from a document — an image or a PDF."""

    file_path: Path
    mime_type: str
    schema_name: str
    json_schema: dict[str, Any]
    prompt: str
    instructions: str | None = None
    model: str | None = None


@dataclass(slots=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(slots=True)
class CompletionResult:
    text: str
    model: str
    provider: str
    usage: Usage = field(default_factory=Usage)


@dataclass(slots=True)
class StructuredResult:
    data: dict[str, Any]
    model: str
    provider: str
    usage: Usage = field(default_factory=Usage)


class LLMProvider(ABC):
    """One model vendor."""

    id: str
    label: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether a credential is present. Checked before every call."""

    @abstractmethod
    def default_model(self) -> str: ...

    def known_models(self) -> list[str]:
        """Advertised models. Informational — any model id may still be passed."""
        return [self.default_model()]

    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResult: ...

    @abstractmethod
    def structured(self, request: StructuredRequest) -> StructuredResult: ...

    @abstractmethod
    def extract_file(self, request: FileExtractionRequest) -> StructuredResult: ...


def to_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Tighten a JSON Schema until a strict structured-output mode accepts it.

    Strict mode requires every object to list *all* of its properties as
    required and to forbid extras. Pydantic's ``model_json_schema()`` does
    neither, and hand-written schemas rarely do, so this normalises both instead
    of making every caller remember.

    Optionality is not lost: a field that may be absent should be typed as
    nullable, which strict mode does allow.
    """
    if not isinstance(schema, dict):
        return schema

    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "default":
            # Strict mode makes every field required, so a default can never
            # apply — and some providers reject the keyword outright.
            continue
        if key in {"properties", "$defs", "definitions"} and isinstance(value, dict):
            result[key] = {name: to_strict_json_schema(sub) for name, sub in value.items()}
        elif key in {"anyOf", "oneOf", "allOf", "prefixItems"} and isinstance(value, list):
            result[key] = [to_strict_json_schema(item) for item in value]
        elif key == "items":
            result[key] = to_strict_json_schema(value)
        else:
            result[key] = value

    if isinstance(result.get("properties"), dict):
        result["additionalProperties"] = False
        result["required"] = list(result["properties"].keys())

    return result
