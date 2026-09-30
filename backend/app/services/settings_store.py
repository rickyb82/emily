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
    "anthropic_api_key": ("Chiave API Anthropic", True),
    "anthropic_default_model": ("Modello di default Claude", False),
    "openai_api_key": ("Chiave API OpenAI", True),
    "openai_default_model": ("Modello di default OpenAI", False),
    "gemini_api_key": ("Chiave API Gemini", True),
    "gemini_default_model": ("Modello di default Gemini", False),
    "tavily_api_key": ("Chiave API Tavily", True),
    "brave_api_key": ("Chiave API Brave Search", True),
    "web_search_provider": ("Motore di ricerca web", False),
    "image_provider": ("Provider immagini (auto/openai/gemini)", False),
    "image_model": ("Modello immagini OpenAI", False),
    "gemini_image_model": ("Modello immagini Gemini (Imagen)", False),
    "video_model": ("Modello video", False),
    "embedding_provider": ("Provider embedding (RAG)", False),
    "embedding_model": ("Modello embedding", False),
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
        setattr(settings, k, overrides.get(k) or _env_defaults[k])
    from ..providers.registry import refresh_models, reload_providers

    reload_providers()
    await refresh_models()


async def set_value(db: AsyncSession, key: str, value: str, user_id: str | None) -> None:
    if key not in MANAGED_KEYS:
        raise ValueError("Impostazione non gestibile")
    _, secret = MANAGED_KEYS[key]
    row = await db.get(AppSetting, key)
    value = (value or "").strip()
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
            r = await c.chat.completions.create(model=settings.openai_default_model, max_tokens=5,
                                                messages=[{"role": "user", "content": "Rispondi solo: OK"}])
            detail = f"{r.model}: {r.choices[0].message.content!r}"
        elif pid == "gemini":
            from google import genai

            c = genai.Client(api_key=settings.gemini_api_key)
            r = await c.aio.models.generate_content(model=settings.gemini_default_model, contents="Rispondi solo: OK")
            detail = f"{settings.gemini_default_model}: {(r.text or '')[:40]!r}"
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
