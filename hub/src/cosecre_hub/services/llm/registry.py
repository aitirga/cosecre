from __future__ import annotations

from dataclasses import dataclass

from ...config import Settings
from .base import LLMError, LLMProvider
from .openai_provider import OpenAIProvider


@dataclass(slots=True)
class ProviderInfo:
    id: str
    label: str
    configured: bool
    default_model: str
    models: list[str]


class LLMRegistry:
    """The set of model providers this hub can reach.

    Held on ``app.state`` and injected as a dependency, which is also what lets
    a test swap in a fake provider without patching module globals.
    """

    def __init__(self, providers: list[LLMProvider], default_provider_id: str | None = None):
        if not providers:
            raise ValueError("A registry needs at least one provider.")
        self._providers = {provider.id: provider for provider in providers}
        self._default_id = default_provider_id or providers[0].id

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMRegistry":
        return cls([OpenAIProvider(settings)])

    @property
    def default_provider_id(self) -> str:
        return self._default_id

    def get(self, provider_id: str | None = None) -> LLMProvider:
        resolved = provider_id or self._default_id
        provider = self._providers.get(resolved)
        if provider is None:
            known = ", ".join(sorted(self._providers))
            raise LLMError(f"Unknown model provider '{resolved}'. Available: {known}.")
        return provider

    def describe(self) -> list[ProviderInfo]:
        return [
            ProviderInfo(
                id=provider.id,
                label=provider.label,
                configured=provider.is_configured(),
                default_model=provider.default_model(),
                models=provider.known_models(),
            )
            for provider in self._providers.values()
        ]

    def any_configured(self) -> bool:
        return any(provider.is_configured() for provider in self._providers.values())
