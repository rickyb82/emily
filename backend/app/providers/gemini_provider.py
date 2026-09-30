from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator

from .base import BaseProvider, ProviderEvent, ToolSpec


def _clean_schema(schema: dict) -> dict:
    """Gemini accetta un sottoinsieme di JSON Schema: rimuoviamo le chiavi non supportate."""
    allowed = {"type", "description", "properties", "required", "items", "enum", "format", "nullable", "anyOf"}
    out = {}
    for k, v in schema.items():
        if k not in allowed:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _clean_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = _clean_schema(v)
        elif k == "anyOf" and isinstance(v, list):
            out[k] = [_clean_schema(x) for x in v]
        else:
            out[k] = v
    if out.get("type") == "object" and "properties" not in out:
        out["properties"] = {}
    return out


class GeminiProvider(BaseProvider):
    id = "gemini"
    label = "Gemini (Google)"

    def models(self) -> list[dict]:
        ids = [self.default_model, "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
        seen, out = set(), []
        for m in ids:
            if m not in seen:
                seen.add(m)
                out.append({"id": m, "label": m})
        return out

    @staticmethod
    def _convert(messages: list[dict]):
        from google.genai import types

        contents = []
        for m in messages:
            parts = []
            for b in m["content"]:
                t = b["type"]
                if t == "text" and b["text"]:
                    parts.append(types.Part.from_text(text=b["text"]))
                elif t == "image":
                    parts.append(types.Part.from_bytes(data=base64.b64decode(b["data"]), mime_type=b["mime"]))
                elif t == "tool_use":
                    parts.append(types.Part.from_function_call(name=b["name"], args=b["input"]))
                elif t == "tool_result":
                    parts.append(types.Part.from_function_response(
                        name=b.get("name", "tool"), response={"result": b["content"]}))
            if not parts:
                continue
            role = "model" if m["role"] == "assistant" else "user"
            if contents and contents[-1].role == role:
                contents[-1].parts.extend(parts)
            else:
                contents.append(types.Content(role=role, parts=parts))
        return contents

    async def stream(self, model, system, messages, tools, max_tokens=4096) -> AsyncIterator[ProviderEvent]:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        cfg = types.GenerateContentConfig(system_instruction=system or None, max_output_tokens=max_tokens)
        if tools:
            cfg.tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description,
                                          parameters=_clean_schema(t.input_schema)) for t in tools])]
            cfg.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        usage = {}
        stream = await client.aio.models.generate_content_stream(
            model=model or self.default_model, contents=self._convert(messages), config=cfg)
        async for chunk in stream:
            if chunk.usage_metadata:
                usage = {"input_tokens": chunk.usage_metadata.prompt_token_count or 0,
                         "output_tokens": chunk.usage_metadata.candidates_token_count or 0}
            for cand in chunk.candidates or []:
                if not cand.content or not cand.content.parts:
                    continue
                for part in cand.content.parts:
                    if part.text:
                        yield ProviderEvent("text_delta", text=part.text)
                    if part.function_call:
                        fc = part.function_call
                        yield ProviderEvent("tool_use", tool_use={"id": fc.id or f"call_{uuid.uuid4().hex[:12]}",
                                                                   "name": fc.name, "input": dict(fc.args or {})})
        yield ProviderEvent("usage", usage=usage)
