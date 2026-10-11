"""Provider per modelli locali serviti da Ollama (API compatibile OpenAI su /v1).
Sul Mac: Ollama nativo (Metal) e OLLAMA_URL=http://host.docker.internal:11434. Su Linux: servizio 'ollama' nel compose."""
from __future__ import annotations

import re
from collections.abc import AsyncIterator

import httpx

from .base import ProviderEvent
from .openai_provider import OpenAIProvider

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)


class OllamaProvider(OpenAIProvider):
    id = "ollama"
    label = "Locale (Ollama)"
    fallback_models = ["qwen3:8b", "qwen3:4b", "gemma3:12b", "llama3.1:8b"]

    def __init__(self, base_url: str, default_model: str):
        super().__init__("ollama", default_model)
        self.base_url = base_url.rstrip("/")
        self.param_sizes: dict[str, float] = {}   # modello -> miliardi di parametri (da /api/tags)

    def is_small(self, model: str | None) -> bool:
        """Modelli piccoli (< 20B) reggono meglio un set ridotto di tool; i grandi (gpt-oss:120b, qwen3:235b...) li usano tutti."""
        size = self.param_sizes.get((model or self.default_model or "").lower())
        if size is None:
            import re
            m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", (model or "").lower())
            size = float(m.group(1)) if m else None
        return size is None or size < 20

    def _client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key="ollama", base_url=self.base_url + "/v1", timeout=300)

    async def discover_models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(self.base_url + "/api/tags")
            r.raise_for_status()
            data = r.json()
        out = []
        for m in data.get("models", []):
            name = m.get("name") or m.get("model")
            if not name or "embed" in name:
                continue
            size_gb = (m.get("size") or 0) / 1e9
            fam = (m.get("details") or {}).get("parameter_size", "")
            try:
                self.param_sizes[name.lower()] = float(str(fam).upper().rstrip("B").replace(",", "."))
            except (ValueError, AttributeError):
                pass
            out.append({"id": name, "label": f"{name} ({fam or f'{size_gb:.1f} GB'})"})
        out.sort(key=lambda x: (x["id"] != self.default_model, x["id"]))
        return out

    async def stream(self, model, system, messages, tools, max_tokens=4096, system_dynamic="") -> AsyncIterator[ProviderEvent]:
        model = model or self.default_model
        # Qwen3: disattiva la modalita' "thinking" (lenta) per le risposte in chat; i blocchi <think> vengono comunque filtrati.
        if model.lower().startswith("qwen3"):
            system_dynamic = (system_dynamic + "\n/no_think").strip()
        buf, in_think = "", False
        async for ev in super().stream(model, system, messages, tools, max_tokens=max_tokens, system_dynamic=system_dynamic):
            if ev.type != "text_delta":
                yield ev
                continue
            buf += ev.text
            out = ""
            while buf:
                if in_think:
                    j = buf.find("</think>")
                    if j < 0:
                        buf = buf[-8:] if len(buf) > 8 else buf   # tieni solo una coda per riconoscere il tag spezzato
                        break
                    buf, in_think = buf[j + len("</think>"):].lstrip(), False
                    continue
                i = buf.find("<think>")
                if i >= 0:
                    out += buf[:i]
                    buf, in_think = buf[i + len("<think>"):], True
                    continue
                # nessun tag: emetti tutto tranne una coda che potrebbe essere l'inizio di "<think>"
                k = buf.rfind("<")
                if k >= 0 and len(buf) - k < len("<think>") and "<think>".startswith(buf[k:]):
                    out += buf[:k]
                    buf = buf[k:]
                else:
                    out += buf
                    buf = ""
                break
            if out:
                yield ProviderEvent("text_delta", text=out)
        if buf and not in_think:
            yield ProviderEvent("text_delta", text=buf)
