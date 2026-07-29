from __future__ import annotations

import json
from pathlib import Path

from conftest import FakeProvider, build_client, register_admin

from cosecre_hub.services.llm import to_strict_json_schema

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
}


def test_providers_are_listed_with_their_configured_state(hub):
    client, _ = hub
    headers = register_admin(client)

    response = client.get("/api/v1/llm/providers", headers=headers)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "fake",
            "label": "Fake",
            "configured": True,
            "default_model": "fake-model-1",
            "models": ["fake-model-1", "fake-model-2"],
        }
    ]


def test_completion_passes_the_prompt_through(hub):
    client, provider = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/complete",
        headers=headers,
        json={"prompt": "Say hello", "instructions": "Be brief.", "model": "fake-model-2"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == provider.text
    assert response.json()["model"] == "fake-model-2"
    assert response.json()["usage"]["total_tokens"] == 18
    assert provider.completions[0].messages[0].content == "Say hello"
    assert provider.completions[0].instructions == "Be brief."


def test_completion_accepts_a_message_list(hub):
    client, provider = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/complete",
        headers=headers,
        json={
            "messages": [
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "4"},
                {"role": "user", "content": "And 3+3?"},
            ]
        },
    )

    assert response.status_code == 200
    assert [message.role for message in provider.completions[0].messages] == [
        "user",
        "assistant",
        "user",
    ]


def test_completion_rejects_an_empty_request(hub):
    client, _ = hub
    headers = register_admin(client)

    assert client.post("/api/v1/llm/complete", headers=headers, json={}).status_code == 422
    both = client.post(
        "/api/v1/llm/complete",
        headers=headers,
        json={"prompt": "hi", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert both.status_code == 422


def test_structured_output_returns_the_provider_payload(hub):
    client, provider = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/structured",
        headers=headers,
        json={"prompt": "The answer?", "schema_name": "answer", "json_schema": ANSWER_SCHEMA},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"answer": 42}
    assert provider.structures[0].schema_name == "answer"


def test_structured_output_requires_an_object_schema(hub):
    client, _ = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/structured",
        headers=headers,
        json={"prompt": "hi", "json_schema": {"type": "string"}},
    )

    assert response.status_code == 422


def test_file_extraction_reaches_the_provider(hub):
    client, provider = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/extract",
        headers=headers,
        files={"file": ("receipt.jpg", b"fake-image-bytes", "image/jpeg")},
        data={"json_schema": json.dumps(ANSWER_SCHEMA), "prompt": "Read this"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["proveidor"] == "Initial extraction"
    assert provider.extractions[0].mime_type == "image/jpeg"
    assert provider.extractions[0].prompt == "Read this"


def test_file_extraction_rejects_a_bad_schema(hub):
    client, _ = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/extract",
        headers=headers,
        files={"file": ("receipt.jpg", b"bytes", "image/jpeg")},
        data={"json_schema": "not json"},
    )

    assert response.status_code == 422


def test_an_unconfigured_provider_answers_503(tmp_path: Path):
    client, _ = build_client(tmp_path, provider=FakeProvider(configured=False))
    with client:
        headers = register_admin(client)
        response = client.post("/api/v1/llm/complete", headers=headers, json={"prompt": "hi"})

    # 503, not 502: the hub is misconfigured, so retrying will not help.
    assert response.status_code == 503


def test_an_unknown_provider_is_reported(hub):
    client, _ = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/complete", headers=headers, json={"prompt": "hi", "provider": "anthropic"}
    )

    assert response.status_code == 502
    assert "Unknown model provider" in response.json()["detail"]


def test_the_gateway_needs_authentication(hub):
    client, _ = hub
    register_admin(client)

    assert client.get("/api/v1/llm/providers").status_code == 401
    assert client.post("/api/v1/llm/complete", json={"prompt": "hi"}).status_code == 401


# ------------------------------------------------------------------ schema helper


def test_strict_schema_requires_every_property_and_forbids_extras():
    strict = to_strict_json_schema(
        {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "integer", "default": 3}},
            "required": ["a"],
        }
    )

    assert strict["required"] == ["a", "b"]
    assert strict["additionalProperties"] is False
    # A default cannot apply once everything is required, and some providers
    # reject the keyword outright.
    assert "default" not in strict["properties"]["b"]


def test_strict_schema_recurses_into_nested_shapes():
    strict = to_strict_json_schema(
        {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"x": {"type": "number"}}},
                },
                "either": {
                    "anyOf": [
                        {"type": "object", "properties": {"y": {"type": "string"}}},
                        {"type": "null"},
                    ]
                },
            },
        }
    )

    assert strict["properties"]["rows"]["items"]["additionalProperties"] is False
    assert strict["properties"]["rows"]["items"]["required"] == ["x"]
    assert strict["properties"]["either"]["anyOf"][0]["required"] == ["y"]


def test_a_provider_without_a_stream_implementation_falls_back_to_complete():
    """`stream` is concrete on the contract, and must stay that way.

    Making it abstract would break every provider that cannot stream — and the
    fake in `conftest` — for no benefit. A vendor with no streaming API should
    give a slow answer, not a 500.
    """
    from cosecre_hub.services.llm import CompletionRequest, Message
    from cosecre_hub.services.llm.base import CompletionResult, LLMProvider, Usage

    class Silent(LLMProvider):
        id = "silent"
        label = "Silent"

        def is_configured(self):
            return True

        def default_model(self):
            return "silent-1"

        def complete(self, request):
            return CompletionResult(
                text="one shot", model="silent-1", provider=self.id, usage=Usage(total_tokens=4)
            )

        def structured(self, request):  # pragma: no cover - not exercised here
            raise NotImplementedError

        def extract_file(self, request):  # pragma: no cover - not exercised here
            raise NotImplementedError

    events = list(Silent().stream(CompletionRequest(messages=[Message(role="user", content="hi")])))

    assert [event.type for event in events] == ["delta", "completed"]
    assert events[0].text == "one shot"
    assert events[1].usage.total_tokens == 4


# ── Streaming ───────────────────────────────────────────────────────────────
#
# The gateway exists so exactly one machine holds a model key. Streaming had to
# join it for the same reason a client app streams at all: a tutor that answers
# in one silent lump reads as broken, and buying a second API key to avoid that
# would defeat the gateway.


def _frames(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_a_stream_arrives_as_deltas_then_one_completed_frame(hub):
    client, fake = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/stream", headers=headers, json={"prompt": "explain gradients"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    frames = _frames(response)

    assert [frame["type"] for frame in frames[:-1]] == ["delta"] * (len(frames) - 1)
    assert frames[-1]["type"] == "completed"
    # The joined deltas and the terminal text are the same answer, which is what
    # lets a client render optimistically and then trust the final frame.
    assert "".join(frame["text"] for frame in frames[:-1]) == fake.text
    assert frames[-1]["text"] == fake.text
    assert frames[-1]["usage"]["total_tokens"] == 18
    assert frames[-1]["model"] == "fake-model-1"


def test_a_mid_stream_failure_is_a_frame_and_never_a_silent_close(hub):
    """The 200 has already gone out, so a failure cannot be a status code.

    A client that only counts deltas must be able to tell a finished answer from
    an abandoned one, and the only thing that distinguishes them is this frame.
    """
    client, fake = hub
    fake.stream_error = "the provider gave up"
    headers = register_admin(client)

    frames = _frames(
        client.post("/api/v1/llm/stream", headers=headers, json={"prompt": "hello"})
    )

    assert frames[-1] == {
        "type": "error",
        "code": "provider_failed",
        "detail": "the provider gave up",
    }
    assert not any(frame["type"] == "completed" for frame in frames)


def test_an_unconfigured_provider_says_so_in_the_stream(hub):
    client, fake = hub
    fake.configured = False
    headers = register_admin(client)

    frames = _frames(
        client.post("/api/v1/llm/stream", headers=headers, json={"prompt": "hello"})
    )

    assert frames == [
        {
            "type": "error",
            "code": "not_configured",
            "detail": "The fake provider has no credentials.",
        }
    ]


def test_streaming_needs_a_token(hub):
    client, _ = hub
    assert client.post("/api/v1/llm/stream", json={"prompt": "hello"}).status_code == 401


# ── Inline images ───────────────────────────────────────────────────────────
#
# A client with its own storage cannot hand the hub a path — the file is on the
# client's disk. So the bytes travel in the message and the hub materialises
# them for the duration of the call.

#: The smallest valid PNG: 1×1, transparent.
_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def test_an_inline_image_reaches_the_provider_as_a_readable_file(hub):
    """The fake opens it during the call, because that is when it exists.

    `Attachment` carries a path rather than bytes so a provider can stream a
    4 MB photo off disk; this proves the path it gets is one it can open.
    """
    client, fake = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/complete",
        headers=headers,
        json={"messages": [{"role": "user", "content": "what is this?", "images": [_PNG]}]},
    )

    assert response.status_code == 200, response.text
    assert len(fake.seen_images) == 1
    mime_type, raw = fake.seen_images[0]
    assert mime_type == "image/png"
    assert raw.startswith(b"\x89PNG")


def test_the_temp_file_does_not_outlive_the_request(hub):
    """It is a passthrough. The hub stores documents; it does not store these."""
    client, fake = hub
    headers = register_admin(client)

    client.post(
        "/api/v1/llm/complete",
        headers=headers,
        json={"messages": [{"role": "user", "content": "what is this?", "images": [_PNG]}]},
    )

    assert not fake.completions[-1].messages[0].attachments[0].path.exists()


def test_an_image_on_an_assistant_turn_is_dropped(hub):
    """There is no output-image input part; sending one would be a 400."""
    client, fake = hub
    headers = register_admin(client)

    client.post(
        "/api/v1/llm/complete",
        headers=headers,
        json={
            "messages": [
                {"role": "user", "content": "here"},
                {"role": "assistant", "content": "and here", "images": [_PNG]},
            ]
        },
    )

    assert fake.seen_images == []


def test_something_that_is_not_a_data_url_is_refused(hub):
    client, _ = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/complete",
        headers=headers,
        json={
            "messages": [
                {"role": "user", "content": "hi", "images": ["https://example.com/cat.png"]}
            ]
        },
    )

    assert response.status_code == 422
    assert "data:" in response.json()["detail"]


def test_a_pdf_data_url_is_refused_because_it_is_not_an_inline_type(hub):
    client, _ = hub
    headers = register_admin(client)

    response = client.post(
        "/api/v1/llm/complete",
        headers=headers,
        json={
            "messages": [
                {"role": "user", "content": "hi", "images": ["data:application/pdf;base64,JVBERi0="]}
            ]
        },
    )

    assert response.status_code == 422
