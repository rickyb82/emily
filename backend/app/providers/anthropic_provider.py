from __future__ import annotations

import json
from collections.abc import AsyncIterator

from .base import BaseProvider, ProviderEvent, ToolSpec


class AnthropicProvider(BaseProvider):
    id = "anthropic"
    label = "Claude (Anthropic)"

    def models(self) -> list[dict]:
        ids = [self.default_model, "claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"]
        seen, out = set(), []
        for m in ids:
            if m not in seen:
                seen.add(m)
                out.append({"id": m, "label": m})
        return out

    @staticmethod
    def _convert(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            blocks = []
            for b in m["content"]:
                t = b["type"]
                if t == "text":
                    if b["text"]:
                        blocks.append({"type": "text", "text": b["text"]})
                elif t == "image":
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": b["mime"], "data": b["data"]}})
                elif t == "tool_use":
                    blocks.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": b["input"]})
                elif t == "tool_result":
                    blocks.append({"type": "tool_result", "tool_use_id": b["tool_use_id"],
                                   "content": b["content"], "is_error": bool(b.get("is_error"))})
            role = "user" if m["role"] in ("user", "tool") else "assistant"
            if not blocks:
                continue
            # Anthropic richiede alternanza: unisci messaggi consecutivi dello stesso ruolo
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": blocks})
        return out

    async def stream(self, model, system, messages, tools, max_tokens=4096) -> AsyncIterator[ProviderEvent]:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.api_key)
        kwargs = dict(model=model or self.default_model, system=system, max_tokens=max_tokens,
                      messages=self._convert(messages))
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]

        current_tool: dict | None = None
        json_buf = ""
        usage = {"input_tokens": 0, "output_tokens": 0}
        async with client.messages.stream(**kwargs) as s:
            async for ev in s:
                et = ev.type
                if et == "content_block_start":
                    cb = ev.content_block
                    if cb.type == "tool_use":
                        current_tool = {"id": cb.id, "name": cb.name, "input": {}}
                        json_buf = ""
                elif et == "content_block_delta":
                    d = ev.delta
                    if d.type == "text_delta":
                        yield ProviderEvent("text_delta", text=d.text)
                    elif d.type == "input_json_delta":
                        json_buf += d.partial_json
                elif et == "content_block_stop":
                    if current_tool is not None:
                        try:
                            current_tool["input"] = json.loads(json_buf) if json_buf.strip() else {}
                        except json.JSONDecodeError:
                            current_tool["input"] = {"_raw": json_buf}
                        yield ProviderEvent("tool_use", tool_use=current_tool)
                        current_tool = None
                elif et == "message_start":
                    usage["input_tokens"] = getattr(ev.message.usage, "input_tokens", 0)
                elif et == "message_delta":
                    usage["output_tokens"] = getattr(ev.usage, "output_tokens", 0)
        yield ProviderEvent("usage", usage=usage)
