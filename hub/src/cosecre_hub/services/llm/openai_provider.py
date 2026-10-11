from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ...config import Settings
from .base import (
    CompletionRequest,
    CompletionResult,
    FileExtractionRequest,
    LLMError,
    LLMNotConfigured,
    LLMProvider,
    Message,
    StreamEvent,
    StructuredRequest,
    StructuredResult,
    ToolCall,
    ToolEvent,
    ToolSession,
    ToolTurnRequest,
    Usage,
    to_strict_json_schema,
)

#: Models the UI offers by default. Any other id can still be passed through —
#: this list exists so a settings screen has something to populate a select with.
KNOWN_MODELS = ["gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol", "gpt-5.4", "gpt-5.4-mini", "gpt-5.1", "gpt-4.1", "gpt-4.1-mini"]

_INLINE_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}


class OpenAIProvider(LLMProvider):
    id = "openai"
    label = "OpenAI"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: Any | None = None

    def is_configured(self) -> bool:
        return bool(self._settings.openai_api_key)

    def default_model(self) -> str:
        return self._settings.openai_model

    def known_models(self) -> list[str]:
        configured = self.default_model()
        return [configured, *[model for model in KNOWN_MODELS if model != configured]]

    # ------------------------------------------------------------------ client
    def _openai(self):
        """Build the SDK client lazily.

        Importing ``openai`` is cheap but constructing a client is not free, and
        a hub with no key configured must still start and serve everything else.
        """
        if not self.is_configured():
            raise LLMNotConfigured("No OpenAI API key is configured on this hub.")
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._settings.openai_api_key)
        return self._client

    def _extra_args(self, temperature: float | None, effort: str | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {}
        effort = self._settings.openai_reasoning_effort if effort is None else effort
        if effort:
            args["reasoning"] = {"effort": effort}
        # Reasoning models reject `temperature` outright, so it is only sent when
        # a caller explicitly asked for one.
        if temperature is not None:
            args["temperature"] = temperature
        return args

    # ------------------------------------------------------------------- calls
    def complete(self, request: CompletionRequest) -> CompletionResult:
        client = self._openai()
        model = request.model or self.default_model()
        try:
            response = client.responses.create(
                model=model,
                instructions=request.instructions or None,
                input=_as_input(request.messages),
                max_output_tokens=request.max_output_tokens,
                **self._extra_args(request.temperature),
            )
        except Exception as exc:  # noqa: BLE001 — SDK raises a wide family
            raise LLMError(_describe(exc)) from exc

        return CompletionResult(
            text=_output_text(response),
            model=model,
            provider=self.id,
            usage=_usage(response),
        )

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        """Stream a completion off the Responses API.

        Event names verified against the installed SDK rather than assumed:
        ``response.output_text.delta`` carries increments, ``response.completed``
        carries the finished response with its usage, and ``error`` is the
        vendor reporting a mid-stream failure — which is raised, not yielded,
        so a partial answer can never be mistaken for a whole one.
        """
        client = self._openai()
        model = request.model or self.default_model()
        chunks: list[str] = []

        try:
            stream = client.responses.create(
                model=model,
                instructions=request.instructions or None,
                input=_as_input(request.messages),
                max_output_tokens=request.max_output_tokens,
                stream=True,
                **self._extra_args(request.temperature),
            )
            for event in stream:
                kind = getattr(event, "type", "")
                if kind == "response.output_text.delta":
                    delta = getattr(event, "delta", "") or ""
                    if delta:
                        chunks.append(delta)
                        yield StreamEvent(type="delta", text=delta)
                elif kind == "error":
                    raise LLMError(getattr(event, "message", "") or "El model ha fallat.")
                elif kind == "response.completed":
                    response = getattr(event, "response", None)
                    yield StreamEvent(
                        type="completed",
                        text=getattr(response, "output_text", None) or "".join(chunks),
                        usage=_usage(response),
                        model=model,
                        provider=self.id,
                    )
                    return
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 — SDK raises a wide family
            raise LLMError(_describe(exc)) from exc

        # The stream ended without a terminal event. Everything received is
        # still worth returning; usage is simply unknown.
        yield StreamEvent(
            type="completed", text="".join(chunks), usage=Usage(), model=model, provider=self.id
        )

    def start_tools(self, request: ToolTurnRequest) -> ToolSession:
        return _OpenAIToolSession(self, request)

    def structured(self, request: StructuredRequest) -> StructuredResult:
        client = self._openai()
        model = request.model or self.default_model()
        try:
            response = client.responses.create(
                model=model,
                instructions=request.instructions or None,
                input=_as_input(request.messages),
                max_output_tokens=request.max_output_tokens,
                text=_json_schema_format(request.schema_name, request.json_schema),
                **self._extra_args(request.temperature),
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(_describe(exc)) from exc

        return StructuredResult(
            data=_parse_json(_output_text(response)),
            model=model,
            provider=self.id,
            usage=_usage(response),
        )

    def extract_file(self, request: FileExtractionRequest) -> StructuredResult:
        client = self._openai()
        model = request.model or self.default_model()
        content: list[dict[str, Any]] = [{"type": "input_text", "text": request.prompt}]

        if request.mime_type in _INLINE_IMAGE_TYPES:
            content.append(_image_part(request.file_path, request.mime_type))
        else:
            # PDFs (and anything else) have to be uploaded first; there is no
            # base64 input part for them.
            try:
                with request.file_path.open("rb") as stream:
                    uploaded = client.files.create(file=stream, purpose="user_data")
            except Exception as exc:  # noqa: BLE001
                raise LLMError(f"Could not upload the document: {_describe(exc)}") from exc
            content.append({"type": "input_file", "file_id": uploaded.id})

        try:
            response = client.responses.create(
                model=model,
                instructions=request.instructions or None,
                input=[{"role": "user", "content": content}],
                text=_json_schema_format(request.schema_name, request.json_schema),
                **self._extra_args(None),
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(_describe(exc)) from exc

        return StructuredResult(
            data=_parse_json(_output_text(response)),
            model=model,
            provider=self.id,
            usage=_usage(response),
        )


class _OpenAIToolSession(ToolSession):
    """Function calling over the Responses API, stateless.

    ``store=False`` with the reasoning carried along encrypted: nothing of the
    conversation is kept on OpenAI's side, so deleting a chat here deletes it.
    The transcript is the list of input items, grown with every output item
    the model produces and every result handed back — the documented way to
    keep a reasoning model's thread across calls without stored responses.
    """

    def __init__(self, provider: OpenAIProvider, request: ToolTurnRequest):
        self._provider = provider
        self._request = request
        self._model = request.model or provider.default_model()
        self._items: list[dict[str, Any]] = _as_input(request.messages)
        self._tools = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                # Optional arguments are the norm here; strict mode would make
                # every one of them required.
                "strict": False,
            }
            for tool in request.tools
        ]

    def step(self) -> Iterator[ToolEvent]:
        client = self._provider._openai()
        chunks: list[str] = []
        try:
            stream = client.responses.create(
                model=self._model,
                instructions=self._request.instructions or None,
                input=self._items,
                tools=self._tools or None,
                max_output_tokens=self._request.max_output_tokens,
                store=False,
                include=["reasoning.encrypted_content"],
                stream=True,
                **self._provider._extra_args(None, self._request.reasoning_effort),
            )
            for event in stream:
                kind = getattr(event, "type", "")
                if kind == "response.output_text.delta":
                    delta = getattr(event, "delta", "") or ""
                    if delta:
                        chunks.append(delta)
                        yield ToolEvent(type="delta", text=delta)
                elif kind == "error":
                    raise LLMError(getattr(event, "message", "") or "El model ha fallat.")
                elif kind == "response.failed":
                    error = getattr(getattr(event, "response", None), "error", None)
                    raise LLMError(getattr(error, "message", "") or "El model ha fallat.")
                elif kind in {"response.completed", "response.incomplete"}:
                    response = getattr(event, "response", None)
                    yield self._finish(response, "".join(chunks))
                    return
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 — SDK raises a wide family
            raise LLMError(_describe(exc)) from exc
        raise LLMError("El model ha tancat la resposta sense acabar-la.")

    def _finish(self, response: Any, streamed: str) -> ToolEvent:
        calls: list[ToolCall] = []
        for item in getattr(response, "output", None) or []:
            payload = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else dict(item)
            self._items.append(payload)
            if payload.get("type") == "function_call":
                calls.append(
                    ToolCall(
                        call_id=payload.get("call_id", ""),
                        name=payload.get("name", ""),
                        arguments=payload.get("arguments", "") or "{}",
                    )
                )
        return ToolEvent(
            type="completed",
            text=getattr(response, "output_text", None) or streamed,
            tool_calls=calls,
            usage=_usage(response),
            model=self._model,
        )

    def add_results(self, results: list[tuple[str, str]]) -> None:
        self._items.extend(
            {"type": "function_call_output", "call_id": call_id, "output": output}
            for call_id, output in results
        )


# --------------------------------------------------------------------- helpers


def _image_part(path: Path, mime_type: str) -> dict[str, Any]:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return {
        "type": "input_image",
        "image_url": f"data:{mime_type};base64,{encoded}",
        "detail": "high",
    }


def _as_input(messages: list[Message]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        content: list[dict[str, Any]] = [
            {
                # The Responses API distinguishes input from output text, and an
                # assistant turn replayed as `input_text` is rejected.
                "type": "output_text" if message.role == "assistant" else "input_text",
                "text": message.content,
            }
        ]
        # User turns only: there is no output-image input part, so attaching one
        # to an assistant turn would be a 400 rather than a picture.
        if message.role != "assistant":
            content.extend(
                _image_part(item.path, item.mime_type)
                for item in message.attachments
                if item.mime_type in _INLINE_IMAGE_TYPES
            )
        payload.append({"role": message.role, "content": content})
    return payload


def _json_schema_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "schema": to_strict_json_schema(schema),
            "strict": True,
        }
    }


def _output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if not text:
        raise LLMError("The model returned an empty response.")
    return text


def _parse_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("The model did not return valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise LLMError("The model returned JSON that is not an object.")
    return parsed


def _usage(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
    )


def _describe(error: Exception) -> str:
    """A message worth showing a user, without leaking request internals."""
    message = str(error).strip()
    return message or error.__class__.__name__
