"""Provider per un server LLM di casa con API compatibile OpenAI (vLLM, llama.cpp server, LM Studio, TGI, LocalAI...).
Esempio: http://192.168.4.2:8000 che serve openai/gpt-oss-120b. Chiave API opzionale."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from .base import ProviderEvent
from .ollama_provider import OllamaProvider

log = logging.getLogger(__name__)


class OpenAICompatProvider(OllamaProvider):
    id = "custom"
    label = "Server LLM di casa"
    fallback_models: list[str] = []

    def __init__(self, base_url: str, default_model: str, api_key: str = "", label: str = ""):
        super().__init__(base_url, default_model)
        self.custom_key = api_key or "none"
        self.tools_supported: bool | None = None   # None = non ancora verificato
        if label:
            self.label = label

    async def stream(self, model, system, messages, tools, max_tokens=4096, system_dynamic="") -> AsyncIterator[ProviderEvent]:
        """Come OpenAI, ma se il server rifiuta i tool (es. vLLM senza --enable-auto-tool-choice) riprova senza e lo ricorda."""
        use_tools = tools if self.tools_supported is not False else []
        try:
            got_any = False
            async for ev in super().stream(model, system, messages, use_tools, max_tokens=max_tokens, system_dynamic=system_dynamic):
                got_any = True
                yield ev
            if use_tools and self.tools_supported is None:
                self.tools_supported = True
        except Exception as e:
            msg = str(e).lower()
            if use_tools and not got_any and ("tool" in msg or "function" in msg) and ("400" in msg or "invalid" in msg or "not support" in msg or "unsupported" in msg):
                log.warning("%s: il server non accetta i tool (%s). Da ora rispondo senza tool.", self.label, str(e)[:200])
                self.tools_supported = False
                yield ProviderEvent("status", text=f"⚠️ {self.label} non supporta i tool: rispondo senza strumenti")
                async for ev in super().stream(model, system, messages, [], max_tokens=max_tokens, system_dynamic=system_dynamic):
                    yield ev
            else:
                raise

    def _client(self):
        from openai import AsyncOpenAI

        base = self.base_url if self.base_url.rstrip("/").endswith("/v1") else self.base_url.rstrip("/") + "/v1"
        return AsyncOpenAI(api_key=self.custom_key, base_url=base, timeout=300)

    async def discover_models(self) -> list[dict]:
        page = await self._client().models.list()
        ids = [m.id for m in page.data]
        if not ids and self.default_model:
            ids = [self.default_model]
        ids.sort(key=lambda i: (i != self.default_model, i))
        out = [{"id": i, "label": i} for i in ids]
        if out and (not self.default_model or self.default_model not in ids):
            self.default_model = ids[0]
        return out
