"""The model gateway.

Every Cosecre app reaches models through here, which is the whole point: the API
key lives on the hub and never ships inside a desktop binary or a browser bundle.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

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
    Attachment,
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


@contextmanager
def _messages(body: CompletionRequestBody | StructuredRequestBody):
    """The request's turns, with any inline images written to temp files.

    A context manager because :class:`Attachment` holds a path: providers stream
    a 4 MB photo off disk rather than carrying it in memory, and a client with
    its own storage can only send us bytes. The files live exactly as long as
    the call does — this is a passthrough, and the hub keeps nothing.
    """
    with tempfile.TemporaryDirectory(prefix="cosecre-llm-") as scratch:
        directory = Path(scratch)
        messages: list[Message] = []
        for index, item in enumerate(body.as_messages()):
            attachments: list[Attachment] = []
            # Assistant turns carry no images: there is no output-image input
            # part, so attaching one would be a 400 rather than a picture.
            if item.role != "assistant":
                for position, source in enumerate(item.images):
                    attachments.append(_decode_image(source, directory / f"{index}-{position}"))
            messages.append(
                Message(role=item.role, content=item.content, attachments=attachments)
            )
        yield messages


#: What `data:` URL prefixes we will decode. Matches the provider's own inline
#: set — anything else has to go through `/llm/extract`, which uploads.
_INLINE_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _decode_image(source: str, stem: Path) -> Attachment:
    matched = re.fullmatch(r"data:([\w/+.-]+);base64,(.+)", source, re.DOTALL)
    if matched is None:
        raise HTTPException(
            status_code=422,
            detail="Images must be `data:<mime>;base64,<...>` URLs.",
        )
    mime_type = matched.group(1)
    if mime_type not in _INLINE_IMAGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Images must be one of {', '.join(sorted(_INLINE_IMAGE_TYPES))}.",
        )
    try:
        raw = base64.b64decode(matched.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="An image was not valid base64.") from exc
    if len(raw) > _MAX_INLINE_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Images larger than {_MAX_INLINE_FILE_BYTES // (1024 * 1024)} MB "
                "are not accepted."
            ),
        )

    path = stem.with_suffix(_INLINE_SUFFIXES.get(mime_type, ".bin"))
    path.write_bytes(raw)
    return Attachment(path=path, mime_type=mime_type)


_INLINE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


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
    with _as_llm_errors(), _messages(body) as messages:
        provider = registry.get(body.provider)
        result = provider.complete(
            CompletionRequest(
                messages=messages,
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
    with _as_llm_errors(), _messages(body) as messages:
        provider = registry.get(body.provider)
        result = provider.structured(
            StructuredRequest(
                messages=messages,
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


#: NDJSON, not SSE. SSE's framing exists for `EventSource`, which cannot send an
#: Authorization header and so was never an option here; one JSON.parse per line
#: is simpler and survives a proxy that has never heard of text/event-stream.
_STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


@router.post("/stream")
def stream(
    body: CompletionRequestBody,
    registry: LLMRegistry = Depends(get_llm_registry),
    _: User = Depends(get_current_user),
):
    """Stream a completion, one JSON object per line.

    Frames are `{"type": "delta", "text": ...}` until exactly one terminal
    frame: `completed` with the joined text and usage, or `error` with a
    detail. A failure that arrives mid-stream cannot be an HTTP status — the
    200 and some of the body have already gone out — so it is a frame, and a
    client that only counts `delta`s must treat a missing `completed` as a
    failure. That is the same contract `LLMProvider.stream` states.

    A client app streams through this rather than holding a model key of its
    own; the gateway exists so exactly one machine has the credential.
    """
    provider = registry.get(body.provider)

    def frames() -> Iterator[str]:
        chunks: list[str] = []
        try:
            with _messages(body) as messages:
                request = CompletionRequest(
                    messages=messages,
                    instructions=body.instructions,
                    model=body.model,
                    max_output_tokens=body.max_output_tokens,
                    temperature=body.temperature,
                )
                for event in provider.stream(request):
                    if event.type == "delta":
                        chunks.append(event.text)
                        yield _frame({"type": "delta", "text": event.text})
                        continue
                    yield _frame(
                        {
                            "type": "completed",
                            "text": event.text or "".join(chunks),
                            "model": event.model,
                            "provider": event.provider,
                            "usage": {
                                "input_tokens": event.usage.input_tokens,
                                "output_tokens": event.usage.output_tokens,
                                "total_tokens": event.usage.total_tokens,
                            },
                        }
                    )
                    return
        except LLMNotConfigured as exc:
            yield _frame({"type": "error", "code": "not_configured", "detail": str(exc)})
            return
        except LLMError as exc:
            yield _frame({"type": "error", "code": "provider_failed", "detail": str(exc)})
            return

        # The provider ended without a terminal event. Say so rather than
        # letting a partial answer close cleanly and look whole.
        yield _frame(
            {
                "type": "error",
                "code": "no_completion",
                "detail": "The provider closed the stream without finishing.",
            }
        )

    return StreamingResponse(
        frames(), media_type="application/x-ndjson", headers=_STREAM_HEADERS
    )


def _frame(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


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
