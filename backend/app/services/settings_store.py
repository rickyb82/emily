"""Impostazioni runtime modificabili dal pannello admin.

I valori salvati in `app_settings` (chiavi API cifrate con SECRET_KEY, modelli di default, provider di ricerca…)
sovrascrivono quelli del file .env. All'avvio e dopo ogni modifica vengono applicati all'oggetto Settings
condiviso, e il registro dei provider viene ricaricato a caldo.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import time

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import AppSetting

log = logging.getLogger(__name__)
settings = get_settings()

# chiave -> (etichetta, è segreto)
MANAGED_KEYS: dict[str, tuple[str, bool]] = {
    "org_mode": ("Modalita' azienda (1 = nessun bambino, etichette organizzazione)", False),
    "passkeys": ("Passkey abilitate (0 = solo app authenticator per il 2FA)", False),
    "anthropic_api_key": ("Chiave API Anthropic", True),
    "anthropic_default_model": ("Modello di default Claude", False),
    "openai_api_key": ("Chiave API OpenAI", True),
    "openai_default_model": ("Modello di default OpenAI", False),
    "openai_reasoning_effort": ("Sforzo di ragionamento OpenAI (auto/none/low/medium/high)", False),
    "gemini_api_key": ("Chiave API Gemini", True),
    "gemini_default_model": ("Modello di default Gemini", False),
    "ollama_url": ("Indirizzo Ollama (modello locale)", False),
    "ollama_default_model": ("Modello locale di default", False),
    "custom_llm_url": ("Indirizzo server LLM di casa (API OpenAI)", False),
    "custom_llm_key": ("Chiave API server LLM di casa", True),
    "custom_llm_model": ("Modello server LLM di casa", False),
    "custom_llm_label": ("Nome del server LLM di casa", False),
    "router_local_provider": ("Provider locale del router Auto", False),
    "router_model": ("Modello locale per il router Auto", False),
    "router_cloud_provider": ("Provider cloud del router Auto", False),
    "router_mode": ("Modalita' router Auto", False),
    "tavily_api_key": ("Chiave API Tavily", True),
    "brave_api_key": ("Chiave API Brave Search", True),
    "web_search_provider": ("Motore di ricerca web", False),
    "searxng_url": ("Indirizzo SearXNG (ricerca web in casa)", False),
    "web_search_summarize": ("Ricerca web: riassunto pagine con modello locale (auto/none)", False),
    "anthropic_native_search": ("Ricerca nativa Anthropic con Claude", False),
    "image_provider": ("Provider immagini (auto/comfyui/openai/gemini)", False),
    "comfyui_url": ("Indirizzo ComfyUI (immagini in casa)", False),
    "comfyui_model": ("Modello ComfyUI (flux-dev/flux-schnell/sdxl/sd35/checkpoint)", False),
    "image_model": ("Modello immagini OpenAI", False),
    "gemini_image_model": ("Modello immagini Gemini (Imagen)", False),
    "video_model": ("Modello video (Veo)", False),
    "video_provider": ("Provider video (auto/comfyui/gemini)", False),
    "comfyui_video_model": ("Modello video ComfyUI", False),
    "comfyui_video_size": ("Video ComfyUI: risoluzione", False),
    "comfyui_video_frames": ("Video ComfyUI: frame (4n+1)", False),
    "tts_provider": ("Provider voce (auto/openai/gemini/none)", False),
    "tts_model_openai": ("Modello voce OpenAI", False),
    "tts_voice_openai": ("Voce OpenAI", False),
    "tts_model_gemini": ("Modello voce Gemini", False),
    "tts_voice_gemini": ("Voce Gemini", False),
    "tts_style": ("Stile della voce (istruzioni)", False),
    "compaction_enabled": ("Compattazione chat lunghe (riassunto + archivio RAG)", False),
    "auto_continue": ("Continuazione automatica delle risposte troncate", False),
    "thinking_mode": ("Ragionamento visibile (off/cloud/all)", False),
    "memory_enabled": ("Memoria di famiglia attiva", False),
    "memory_auto_approve": ("Memoria: approvazione automatica voci sicure", False),
    "memory_model": ("Memoria: modello per l'estrazione", False),
    "embedding_provider": ("Provider embedding (RAG)", False),
    "embedding_model": ("Modello embedding", False),
    "smtp_host": ("Server SMTP", False),
    "smtp_port": ("Porta SMTP", False),
    "smtp_user": ("Utente SMTP", False),
    "smtp_password": ("Password SMTP", True),
    "smtp_from": ("Mittente", False),
    "smtp_from_name": ("Nome mittente", False),
    "smtp_security": ("Sicurezza SMTP (starttls/ssl/none)", False),
    "email_mfa_fallback": ("Codice email al posto della passkey", False),
    "mail_transport": ("Canale email (auto/gmail_oauth/smtp)", False),
    "gmail_oauth_refresh_token": ("Token Gmail OAuth", True),
    "gmail_oauth_email": ("Account Gmail collegato", False),
    "google_client_id": ("Google OAuth Client ID", False),
    "google_client_secret": ("Google OAuth Client secret", True),
    "pricing_json": ("Listino prezzi (JSON)", False),
    "budget_anthropic": ("Budget mensile Anthropic (USD)", False),
    "budget_openai": ("Budget mensile OpenAI (USD)", False),
    "budget_gemini": ("Budget mensile Gemini (USD)", False),
    "anthropic_admin_key": ("Chiave Admin Anthropic (spesa reale)", True),
    "openai_admin_key": ("Chiave Admin OpenAI (spesa reale)", True),
}

_env_defaults: dict[str, str] = {k: getattr(settings, k) for k in MANAGED_KEYS}


def _fernet() -> Fernet:
    digest = hashlib.sha256(("familai:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        log.error("Impossibile decifrare un'impostazione: SECRET_KEY cambiata? Il valore verrà ignorato.")
        return ""


def mask(value: str) -> str:
    if not value:
        return ""
    return value[:4] + "…" + value[-4:] if len(value) > 10 else "•" * len(value)


async def load_overrides(db: AsyncSession) -> dict[str, str]:
    rows = (await db.execute(select(AppSetting))).scalars().all()
    out = {}
    for r in rows:
        if r.key in MANAGED_KEYS:
            out[r.key] = decrypt(r.value) if r.secret else r.value
    return out


async def apply(db: AsyncSession) -> None:
    """Applica env + override DB all'oggetto Settings e ricarica i provider."""
    overrides = await load_overrides(db)
    for k in MANAGED_KEYS:
        val = overrides.get(k) or _env_defaults[k]
        # campi numerici del Settings: i valori dal pannello arrivano come stringa
        if isinstance(_env_defaults[k], int) and not isinstance(_env_defaults[k], bool):
            try:
                val = int(str(val).strip() or _env_defaults[k])
            except ValueError:
                val = _env_defaults[k]
        setattr(settings, k, val)
    from ..providers.registry import refresh_models, reload_providers

    reload_providers()
    await refresh_models()


async def set_value(db: AsyncSession, key: str, value: str, user_id: str | None) -> None:
    if key not in MANAGED_KEYS:
        raise ValueError("Impostazione non gestibile")
    _, secret = MANAGED_KEYS[key]
    row = await db.get(AppSetting, key)
    value = (value or "").strip()
    if key.endswith(("_model", "_default_model", "_provider")) or key in ("image_model", "video_model"):
        value = value.lower().replace(" ", "")   # gli id dei modelli sono minuscoli senza spazi
    if not value:
        if row:
            await db.delete(row)
    else:
        stored = encrypt(value) if secret else value
        if row:
            row.value, row.secret, row.updated_by = stored, secret, user_id
        else:
            db.add(AppSetting(key=key, value=stored, secret=secret, updated_by=user_id))
    await db.commit()


async def describe(db: AsyncSession) -> dict[str, dict]:
    """Stato di ogni impostazione: valore effettivo (mascherato se segreto) e provenienza."""
    overrides = await load_overrides(db)
    out = {}
    for k, (label, secret) in MANAGED_KEYS.items():
        env_v = _env_defaults[k]
        db_v = overrides.get(k, "")
        eff = db_v or env_v
        out[k] = {"label": label, "secret": secret, "configured": bool(eff),
                  "source": "admin" if db_v else ("env" if env_v else "none"),
                  "value": mask(eff) if secret else eff}
    return out


# ------------------------------------------------------------------ test connessioni
async def test_provider(pid: str) -> dict:
    """Esegue una chiamata minima per verificare la chiave. Ritorna {ok, detail, latency_ms}."""
    t0 = time.perf_counter()
    try:
        if pid == "anthropic":
            from anthropic import AsyncAnthropic

            c = AsyncAnthropic(api_key=settings.anthropic_api_key)
            r = await c.messages.create(model=settings.anthropic_default_model, max_tokens=5,
                                        messages=[{"role": "user", "content": "Rispondi solo: OK"}])
            detail = f"{r.model}: {''.join(b.text for b in r.content if b.type == 'text')!r}"
        elif pid == "openai":
            from openai import AsyncOpenAI

            c = AsyncOpenAI(api_key=settings.openai_api_key)
            r = await c.chat.completions.create(model=settings.openai_default_model, max_completion_tokens=16,
                                                messages=[{"role": "user", "content": "Rispondi solo: OK"}])
            detail = f"{r.model}: {r.choices[0].message.content!r}"
        elif pid == "gemini":
            from google import genai

            c = genai.Client(api_key=settings.gemini_api_key)
            r = await c.aio.models.generate_content(model=settings.gemini_default_model, contents="Rispondi solo: OK")
            detail = f"{settings.gemini_default_model}: {(r.text or '')[:40]!r}"
        elif pid == "ollama":
            import httpx

            async with httpx.AsyncClient(timeout=15) as h:
                from .neturl import host_url
                r = await h.get(host_url(settings.ollama_url).rstrip("/") + "/api/tags")
                r.raise_for_status()
                names = [m.get("name") for m in r.json().get("models", [])]
            emb = settings.embedding_model or "bge-m3"
            if settings.embedding_provider in ("auto", "ollama") and not any(n == emb or n.startswith(emb + ":") for n in names):
                names_hint = f" — per il RAG locale manca '{emb}': ollama pull {emb}"
            else:
                names_hint = ""
            if not names:
                return {"ok": False, "detail": "Ollama risponde ma non ha modelli scaricati: esegui `ollama pull qwen3:8b` e `ollama pull qwen3:4b`",
                        "latency_ms": int((time.perf_counter() - t0) * 1000)}
            missing = [m for m in (settings.ollama_default_model, settings.router_model) if m not in names]
            detail = f"{len(names)} modelli: {', '.join(names[:8])}" + (f" — mancano: {', '.join(missing)} (ollama pull …)" if missing else "") + names_hint
        elif pid == "custom":
            import httpx
            from openai import AsyncOpenAI
            from ..providers.openai_compat_provider import OpenAICompatProvider

            from .neturl import host_url
            base = OpenAICompatProvider.normalize_base(host_url(settings.custom_llm_url))
            # prima un GET "nudo" per distinguere problemi di rete da problemi di API
            try:
                async with httpx.AsyncClient(timeout=8) as h:
                    r = await h.get(base + "/models", headers={"Authorization": f"Bearer {settings.custom_llm_key}"} if settings.custom_llm_key else {})
            except httpx.ConnectError as e:
                return {"ok": False, "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "detail": f"Il backend (nel container Docker) non raggiunge {base}: {e}. Verifica che dall'host 'curl {base}/models' "
                                  "funzioni, che il server LLM ascolti su 0.0.0.0 (non solo 127.0.0.1) e che il firewall lasci passare la porta."}
            except httpx.TimeoutException:
                return {"ok": False, "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "detail": f"Timeout verso {base}: indirizzo/porta errati, server fermo o rete non instradata dal container Docker."}
            if r.status_code in (401, 403):
                return {"ok": False, "detail": f"Il server richiede una chiave API valida (HTTP {r.status_code}): impostala in 'Altre impostazioni'.",
                        "latency_ms": int((time.perf_counter() - t0) * 1000)}
            if r.status_code >= 400:
                return {"ok": False, "detail": f"HTTP {r.status_code} da {base}/models: {r.text[:200]}", "latency_ms": int((time.perf_counter() - t0) * 1000)}
            c = AsyncOpenAI(api_key=settings.custom_llm_key or "none", base_url=base, timeout=60)
            page = await c.models.list()
            names = [m.id for m in page.data]
            model = settings.custom_llm_model or (names[0] if names else "")
            r = await c.chat.completions.create(model=model, max_tokens=16, messages=[{"role": "user", "content": "Rispondi solo: OK"}])
            detail = f"{len(names)} modelli ({', '.join(names[:5])}); {model}: {r.choices[0].message.content!r}"
        elif pid == "comfyui":
            import httpx
            from ..services import comfyui

            try:
                info = await comfyui.models_available()
            except httpx.ConnectError as e:
                return {"ok": False, "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "detail": f"Il backend (in Docker) non raggiunge ComfyUI a {settings.comfyui_url}: {e}. Se ComfyUI gira sul Mac usa "
                                  "http://host.docker.internal:8188 (non localhost) e avvialo con --listen 0.0.0.0; se e' su un altro server controlla IP/porta/firewall."}
            dev = ""
            try:
                d = info["stats"]["devices"][0]
                dev = f" — GPU {d.get('name', '')} ({round(d.get('vram_total', 0) / 1e9)} GB)"
            except Exception:
                pass
            want = settings.comfyui_model
            have = info["checkpoints"] + info["unets"]
            from ..services.comfyui import PRESETS
            need = PRESETS.get(want, {}).get("unet") or PRESETS.get(want, {}).get("ckpt") or want
            missing = "" if any(need in h for h in have) else f" — ATTENZIONE: '{need}' non trovato (./download-models.sh {want})"
            detail = f"{len(info['checkpoints'])} checkpoint, {len(info['unets'])} unet{dev}{missing}"
        elif pid == "tavily":
            import httpx

            async with httpx.AsyncClient(timeout=20) as h:
                r = await h.post("https://api.tavily.com/search",
                                 json={"api_key": settings.tavily_api_key, "query": "test", "max_results": 1})
                r.raise_for_status()
            detail = "ricerca eseguita"
        elif pid == "brave":
            import httpx

            async with httpx.AsyncClient(timeout=20) as h:
                r = await h.get("https://api.search.brave.com/res/v1/web/search", params={"q": "test", "count": 1},
                                headers={"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"})
                r.raise_for_status()
            detail = "ricerca eseguita"
        else:
            return {"ok": False, "detail": "provider sconosciuto"}
        return {"ok": True, "detail": detail, "latency_ms": int((time.perf_counter() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:300]}", "latency_ms": int((time.perf_counter() - t0) * 1000)}
