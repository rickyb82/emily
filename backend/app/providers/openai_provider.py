from __future__ import annotations

import json
from collections.abc import AsyncIterator

from .base import BaseProvider, ProviderEvent, ToolSpec


class OpenAIProvider(BaseProvider):
    id = "openai"
    label = "ChatGPT (OpenAI)"

    def models(self) -> list[dict]:
        ids = [self.default_model, "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "o4-mini"]
        seen, out = set(), []
        for m in ids:
            if m not in seen:
                seen.add(m)
                out.append({"id": m, "label": m})
        return out

    @staticmethod
    def _convert(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}] if system else []
        for m in messages:
            if m["role"] == "user":
                parts = []
                for b in m["content"]:
                    if b["type"] == "text" and b["text"]:
                        parts.append({"type": "text", "text": b["text"]})
                    elif b["type"] == "image":
                        parts.append({"type": "image_url", "image_url": {"url": f"data:{b['mime']};base64,{b['data']}"}})
                if parts:
                    out.append({"role": "user", "content": parts})
            elif m["role"] == "assistant":
                text = "".join(b["text"] for b in m["content"] if b["type"] == "text")
                calls = [{"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                         for b in m["content"] if b["type"] == "tool_use"]
                msg: dict = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
            elif m["role"] == "tool":
                for b in m["content"]:
                    if b["type"] == "tool_result":
                        out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
        return out

    async def stream(self, model, system, messages, tools, max_tokens=4096) -> AsyncIterator[ProviderEvent]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)
        kwargs = dict(model=model or self.default_model, messages=self._convert(system, messages), stream=True,
                      stream_options={"include_usage": True})
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                                  "parameters": t.input_schema}} for t in tools]
        pending: dict[int, dict] = {}
        usage = {}
        async for chunk in await client.chat.completions.create(**kwargs):
            if chunk.usage:
                usage = {"input_tokens": chunk.usage.prompt_tokens, "output_tokens": chunk.usage.completion_tokens}
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield ProviderEvent("text_delta", text=delta.content)
            for tc in delta.tool_calls or []:
                p = pending.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    p["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        p["name"] += tc.function.name
                    if tc.function.arguments:
                        p["args"] += tc.function.arguments
        for p in pending.values():
            try:
                args = json.loads(p["args"]) if p["args"].strip() else {}
            except json.JSONDecodeError:
                args = {"_raw": p["args"]}
            yield ProviderEvent("tool_use", tool_use={"id": p["id"], "name": p["name"], "input": args})
        yield ProviderEvent("usage", usage=usage)
