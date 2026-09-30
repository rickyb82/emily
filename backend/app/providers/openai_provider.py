from __future__ import annotations

import json
from collections.abc import AsyncIterator

from .base import PROGRESS_STEP, BaseProvider, ProviderEvent, ToolSpec, truncated_tool_warning, writing_status


class OpenAIProvider(BaseProvider):
    id = "openai"
    label = "ChatGPT (OpenAI)"

    fallback_models = ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "o4-mini"]

    image_models: list[str] = []

    async def discover_models(self) -> list[dict]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)
        page = await client.models.list()
        self.image_models = sorted({m.id for m in page.data if m.id.startswith(("gpt-image", "dall-e"))}, reverse=True)
        skip = ("realtime", "audio", "tts", "transcribe", "whisper", "embedding", "image", "dall-e", "moderation",
                "instruct", "search", "davinci", "babbage", "codex", "computer-use", "sora")
        ids = sorted({m.id for m in page.data
                      if (m.id.startswith("gpt-") or m.id.startswith("o") and m.id[1:2].isdigit() or m.id.startswith("chatgpt-"))
                      and not any(k in m.id for k in skip)}, reverse=True)
        # metti prima i modelli "generici" (senza data) e il default
        ids.sort(key=lambda i: (i != self.default_model, any(ch.isdigit() for ch in i.split("-")[-1]) and len(i.split("-")[-1]) >= 4, i))
        return [{"id": i, "label": i} for i in ids]

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
                      stream_options={"include_usage": True}, max_completion_tokens=max_tokens)
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                                  "parameters": t.input_schema}} for t in tools]
        pending: dict[int, dict] = {}
        usage = {}
        finish_reason = None
        async for chunk in await client.chat.completions.create(**kwargs):
            if chunk.usage:
                usage = {"input_tokens": chunk.usage.prompt_tokens, "output_tokens": chunk.usage.completion_tokens}
            if not chunk.choices:
                continue
            finish_reason = chunk.choices[0].finish_reason or finish_reason
            delta = chunk.choices[0].delta
            if delta.content:
                yield ProviderEvent("text_delta", text=delta.content)
            for tc in delta.tool_calls or []:
                p = pending.setdefault(tc.index, {"id": "", "name": "", "args": "", "next": PROGRESS_STEP})
                if tc.id:
                    p["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        p["name"] += tc.function.name
                        yield ProviderEvent("status", text=writing_status(p["name"], 0))
                    if tc.function.arguments:
                        p["args"] += tc.function.arguments
                        if len(p["args"]) >= p["next"]:
                            p["next"] += PROGRESS_STEP
                            yield ProviderEvent("status", text=writing_status(p["name"], len(p["args"])))
        for p in pending.values():
            try:
                args = json.loads(p["args"]) if p["args"].strip() else {}
            except json.JSONDecodeError:
                yield ProviderEvent("text_delta", text=truncated_tool_warning(p["name"]))
                continue
            yield ProviderEvent("tool_use", tool_use={"id": p["id"], "name": p["name"], "input": args})
        if finish_reason == "length" and not pending:
            yield ProviderEvent("text_delta", text="\n\n⚠️ Risposta interrotta per lunghezza massima: chiedimi di continuare.")
        yield ProviderEvent("usage", usage=usage)
