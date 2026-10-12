from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from .anthropic_provider import AnthropicProvider
from .base import BaseProvider
from .gemini_provider import GeminiProvider
from .mock_provider import MockProvider
from .ollama_provider import OllamaProvider
from .openai_compat_provider import OpenAICompatProvider
from .openai_provider import OpenAIProvider


LOCAL_IDS = {"ollama", "custom"}   # provider "di casa": gratis, dati che non escono


def local_provider_id() -> str | None:
    """Il provider locale che risponde con il router Auto."""
    s = get_settings()
    provs = _providers()
    pref = (s.router_local_provider or "auto").lower()
    if pref in provs and pref in LOCAL_IDS:
        return pref
    for k in ("custom", "ollama"):
        if k in provs:
            return k
    return None


@lru_cache
def _providers() -> dict[str, BaseProvider]:
    s = get_settings()
    out: dict[str, BaseProvider] = {}
    if s.anthropic_api_key:
        out["anthropic"] = AnthropicProvider(s.anthropic_api_key, s.anthropic_default_model)
    if s.openai_api_key:
        out["openai"] = OpenAIProvider(s.openai_api_key, s.openai_default_model)
        out["openai"].reasoning_effort = s.openai_reasoning_effort
    if s.gemini_api_key:
        out["gemini"] = GeminiProvider(s.gemini_api_key, s.gemini_default_model)
    if s.ollama_url:
        out["ollama"] = OllamaProvider(s.ollama_url, s.ollama_default_model)
    if s.custom_llm_url:
        out["custom"] = OpenAICompatProvider(s.custom_llm_url, s.custom_llm_model, s.custom_llm_key, s.custom_llm_label)
    if s.enable_mock_provider or not out:
        out["mock"] = MockProvider("", "mock-1")
    mode = (s.thinking_mode or "cloud").lower()
    for pid, p in out.items():
        p.thinking = mode == "all" or (mode == "cloud" and pid in ("anthropic", "gemini", "openai"))
        p.thinking_budget = int(s.thinking_budget or 4096)
    return out


def reload_providers() -> None:
    """Ricostruisce il registro (dopo modifica chiavi dal pannello admin)."""
    _providers.cache_clear()


async def refresh_models() -> None:
    """Chiede a ogni provider la lista aggiornata dei modelli (chiamato all'avvio e dopo un cambio chiavi)."""
    import asyncio

    await asyncio.gather(*(p.refresh_models() for p in _providers().values()), return_exceptions=True)


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
    out = [{"id": p.id, "label": p.label, "models": p.models(), "default_model": p.default_model}
           for p in _providers().values()]
    s = get_settings()
    if LOCAL_IDS & set(_providers()) and (s.router_mode or "locale").lower() != "off" and len(_providers()) > 1:
        # pseudo-provider: il router decide a ogni messaggio tra locale e cloud
        out.insert(0, {"id": "auto", "label": "Auto (locale + cloud)",
                       "models": [{"id": "auto", "label": "decide il router"}], "default_model": "auto"})
    return out
