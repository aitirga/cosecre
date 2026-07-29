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
