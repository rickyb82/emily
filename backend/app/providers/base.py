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

    def __init__(self, api_key: str, default_model: str):
        self.api_key = api_key
        self.default_model = default_model

    def models(self) -> list[dict]:
        return [{"id": self.default_model, "label": self.default_model}]

    async def stream(self, model: str, system: str, messages: list[dict], tools: list[ToolSpec],
                     max_tokens: int = 4096) -> AsyncIterator[ProviderEvent]:
        raise NotImplementedError
        yield  # pragma: no cover


def text_of(blocks: list[dict]) -> str:
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
