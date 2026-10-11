"""Provider per un server LLM di casa con API compatibile OpenAI (vLLM, llama.cpp server, LM Studio, TGI, LocalAI...).
Esempio: http://192.168.4.2:8000 che serve openai/gpt-oss-120b. Chiave API opzionale."""
from __future__ import annotations

from .ollama_provider import OllamaProvider


class OpenAICompatProvider(OllamaProvider):
    id = "custom"
    label = "Server LLM di casa"
    fallback_models: list[str] = []

    def __init__(self, base_url: str, default_model: str, api_key: str = "", label: str = ""):
        super().__init__(base_url, default_model)
        self.custom_key = api_key or "none"
        if label:
            self.label = label

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
