from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from .anthropic_provider import AnthropicProvider
from .base import BaseProvider
from .gemini_provider import GeminiProvider
from .mock_provider import MockProvider
from .openai_provider import OpenAIProvider


@lru_cache
def _providers() -> dict[str, BaseProvider]:
    s = get_settings()
    out: dict[str, BaseProvider] = {}
    if s.anthropic_api_key:
        out["anthropic"] = AnthropicProvider(s.anthropic_api_key, s.anthropic_default_model)
    if s.openai_api_key:
        out["openai"] = OpenAIProvider(s.openai_api_key, s.openai_default_model)
    if s.gemini_api_key:
        out["gemini"] = GeminiProvider(s.gemini_api_key, s.gemini_default_model)
    if s.enable_mock_provider or not out:
        out["mock"] = MockProvider("", "mock-1")
    return out


def reload_providers() -> None:
    """Ricostruisce il registro (dopo modifica chiavi dal pannello admin)."""
    _providers.cache_clear()


def get_provider(pid: str | None) -> BaseProvider:
    provs = _providers()
    if pid and pid in provs:
        return provs[pid]
    # default: primo disponibile in ordine di preferenza
    for k in ("anthropic", "openai", "gemini", "mock"):
        if k in provs:
            return provs[k]
    raise RuntimeError("Nessun provider configurato")


def available_providers() -> list[dict]:
    return [{"id": p.id, "label": p.label, "models": p.models(), "default_model": p.default_model}
            for p in _providers().values()]
