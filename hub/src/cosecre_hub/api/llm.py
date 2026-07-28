"""The model gateway.

Every Cosecre app reaches models through here, which is the whole point: the API
key lives on the hub and never ships inside a desktop binary or a browser bundle.
"""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from ..deps import get_current_user, get_llm_registry
from ..models import User
from ..schemas import (
    CompletionRequestBody,
    CompletionResponse,
    ProviderRead,
    StructuredRequestBody,
    StructuredResponse,
    UsageRead,
)
from ..services.llm import (
    CompletionRequest,
    FileExtractionRequest,
    LLMError,
    LLMNotConfigured,
    LLMRegistry,
    Message,
    StructuredRequest,
)

router = APIRouter()

_MAX_INLINE_FILE_BYTES = 25 * 1024 * 1024


@contextmanager
def _as_llm_errors():
    """Translate provider failures into responses a client can act on.

    503 means "fix the hub's configuration", 502 means "the provider had a bad
    day" — the distinction is what stops a client retrying forever against a hub
    that has no API key at all.
    """
    try:
        yield
    except LLMNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except LLMError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _usage(usage) -> UsageRead:
    return UsageRead(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def _messages(body: CompletionRequestBody | StructuredRequestBody) -> list[Message]:
    return [Message(role=item.role, content=item.content) for item in body.as_messages()]


@router.get("/providers", response_model=list[ProviderRead])
def list_providers(
    registry: LLMRegistry = Depends(get_llm_registry),
    _: User = Depends(get_current_user),
):
    return [
        ProviderRead(
            id=info.id,
            label=info.label,
            configured=info.configured,
            default_model=info.default_model,
            models=info.models,
        )
        for info in registry.describe()
    ]


@router.post("/complete", response_model=CompletionResponse)
def complete(
    body: CompletionRequestBody,
    registry: LLMRegistry = Depends(get_llm_registry),
    _: User = Depends(get_current_user),
):
    with _as_llm_errors():
        provider = registry.get(body.provider)
        result = provider.complete(
            CompletionRequest(
                messages=_messages(body),
                instructions=body.instructions,
                model=body.model,
                max_output_tokens=body.max_output_tokens,
                temperature=body.temperature,
            )
        )
    return CompletionResponse(
        text=result.text, provider=result.provider, model=result.model, usage=_usage(result.usage)
    )


@router.post("/structured", response_model=StructuredResponse)
def structured(
    body: StructuredRequestBody,
    registry: LLMRegistry = Depends(get_llm_registry),
    _: User = Depends(get_current_user),
):
    """Return JSON matching a caller-supplied schema."""
    with _as_llm_errors():
        provider = registry.get(body.provider)
        result = provider.structured(
            StructuredRequest(
                messages=_messages(body),
                schema_name=body.schema_name,
                json_schema=body.json_schema,
                instructions=body.instructions,
                model=body.model,
                max_output_tokens=body.max_output_tokens,
                temperature=body.temperature,
            )
        )
    return StructuredResponse(
        data=result.data, provider=result.provider, model=result.model, usage=_usage(result.usage)
    )


@router.post("/extract", response_model=StructuredResponse)
async def extract(
    file: UploadFile = File(..., description="An image or PDF to read."),
    json_schema: str = Form(..., description="JSON Schema object, as a JSON string."),
    prompt: str = Form("Extract the fields from this document."),
    instructions: str = Form(""),
    schema_name: str = Form("extraction"),
    provider: str | None = Form(None),
    model: str | None = Form(None),
    registry: LLMRegistry = Depends(get_llm_registry),
    _: User = Depends(get_current_user),
):
    """Structured extraction straight from an uploaded document.

    The file is held in a temp path for the duration of the call and never
    retained: this endpoint is a passthrough for apps that have their own
    storage, unlike the documents module which keeps what it ingests.
    """
    schema = _parse_schema(json_schema)
    payload = await file.read()
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file was empty."
        )
    if len(payload) > _MAX_INLINE_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Files larger than {_MAX_INLINE_FILE_BYTES // (1024 * 1024)} MB are not accepted.",
        )

    suffix = Path(file.filename or "").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as scratch:
        scratch.write(payload)
        scratch.flush()
        with _as_llm_errors():
            result = registry.get(provider).extract_file(
                FileExtractionRequest(
                    file_path=Path(scratch.name),
                    mime_type=file.content_type or "application/octet-stream",
                    schema_name=schema_name,
                    json_schema=schema,
                    prompt=prompt,
                    instructions=instructions or None,
                    model=model,
                )
            )

    return StructuredResponse(
        data=result.data, provider=result.provider, model=result.model, usage=_usage(result.usage)
    )


def _parse_schema(raw: str) -> dict[str, Any]:
    # 422 as a literal: Starlette renamed its constant, and the numeric code is
    # the one thing that is stable across both spellings.
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="'json_schema' is not valid JSON.") from exc
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise HTTPException(status_code=422, detail="'json_schema' must be a JSON Schema object.")
    return schema
