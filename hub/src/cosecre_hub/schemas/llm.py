from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ProviderRead(BaseModel):
    id: str
    label: str
    configured: bool
    default_model: str
    models: list[str]


class UsageRead(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class _BaseLLMRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    #: Provider-level system prompt. Kept separate from ``messages`` because the
    #: Responses API treats it as a distinct field, not a turn.
    instructions: str | None = None
    prompt: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    max_output_tokens: int | None = Field(default=None, ge=1, le=128_000)
    temperature: float | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def require_input(self) -> "_BaseLLMRequest":
        if not self.prompt and not self.messages:
            raise ValueError("Provide either 'prompt' or a non-empty 'messages' list.")
        if self.prompt and self.messages:
            raise ValueError("Provide 'prompt' or 'messages', not both.")
        return self

    def as_messages(self) -> list[ChatMessage]:
        if self.prompt:
            return [ChatMessage(role="user", content=self.prompt)]
        return self.messages


class CompletionRequestBody(_BaseLLMRequest):
    pass


class CompletionResponse(BaseModel):
    text: str
    provider: str
    model: str
    usage: UsageRead


class StructuredRequestBody(_BaseLLMRequest):
    #: Name the provider attaches to the schema. Purely a label.
    schema_name: str = Field(default="result", min_length=1, max_length=64)
    json_schema: dict[str, Any] = Field(
        description="A JSON Schema object describing the expected result.",
    )

    @model_validator(mode="after")
    def require_object_schema(self) -> "StructuredRequestBody":
        if self.json_schema.get("type") != "object":
            raise ValueError("'json_schema' must describe an object.")
        if not isinstance(self.json_schema.get("properties"), dict):
            raise ValueError("'json_schema' must declare 'properties'.")
        return self


class StructuredResponse(BaseModel):
    data: dict[str, Any]
    provider: str
    model: str
    usage: UsageRead
