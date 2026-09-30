"""Interfaccia comune ai provider LLM.

Formato interno dei messaggi (indipendente dal provider):
  {"role": "user"|"assistant"|"tool", "content": [blocchi]}
Blocchi:
  {"type": "text", "text": str}
  {"type": "image", "mime": str, "data": base64}
  {"type": "tool_use", "id": str, "name": str, "input": dict}
  {"type": "tool_result", "tool_use_id": str, "name": str, "content": str, "is_error": bool}
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ProviderEvent:
    type: str  # text_delta | tool_use | usage | error | done
    text: str = ""
    tool_use: dict | None = None
    usage: dict = field(default_factory=dict)
    error: str = ""


class BaseProvider:
    id: str = "base"
    label: str = "Base"
    supports_images: bool = True

    fallback_models: list[str] = []

    def __init__(self, api_key: str, default_model: str):
        self.api_key = api_key
        self.default_model = default_model
        self._models: list[dict] | None = None   # scoperti via API (refresh_models)

    def models(self) -> list[dict]:
        if self._models:
            return self._models
        ids = [self.default_model] + [m for m in self.fallback_models if m != self.default_model]
        return [{"id": m, "label": m} for m in ids if m]

    async def discover_models(self) -> list[dict]:
        """Interroga l'API del provider per la lista dei modelli chat disponibili."""
        return []

    async def refresh_models(self) -> None:
        try:
            found = await self.discover_models()
        except Exception:
            found = []
        if found:
            self._models = found
            ids = {m["id"] for m in found}
            if self.default_model not in ids:
                # il default configurato non esiste (piu'): usa il primo consigliato
                self.default_model = found[0]["id"]

    async def stream(self, model: str, system: str, messages: list[dict], tools: list[ToolSpec],
                     max_tokens: int = 4096) -> AsyncIterator[ProviderEvent]:
        raise NotImplementedError
        yield  # pragma: no cover


def text_of(blocks: list[dict]) -> str:
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
