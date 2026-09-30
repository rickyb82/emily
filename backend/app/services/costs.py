"""Stima costi e budget per provider.

- Stima locale: usage_log (token in/out, immagini, video) x listino prezzi (modificabile dal pannello).
- Spesa reale (opzionale): Anthropic e OpenAI con chiave Admin dell'organizzazione. Gemini non la espone via API.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import UsageLog, User

log = logging.getLogger(__name__)
settings = get_settings()

# Prezzi in USD: per milione di token (input/output), per immagine, per secondo di video.
# Le chiavi sono prefissi di nome modello; vince il prefisso piu' lungo che combacia. "*" = default del provider.
DEFAULT_PRICING: dict = {
    "anthropic": {"*": {"in": 3.0, "out": 15.0}, "claude-opus": {"in": 15.0, "out": 75.0},
                  "claude-sonnet": {"in": 3.0, "out": 15.0}, "claude-haiku": {"in": 1.0, "out": 5.0}},
    "openai": {"*": {"in": 2.0, "out": 8.0}, "gpt-4.1": {"in": 2.0, "out": 8.0}, "gpt-4.1-mini": {"in": 0.4, "out": 1.6},
               "gpt-4.1-nano": {"in": 0.1, "out": 0.4}, "gpt-4o": {"in": 2.5, "out": 10.0}, "gpt-4o-mini": {"in": 0.15, "out": 0.6},
               "gpt-5": {"in": 1.25, "out": 10.0}, "gpt-5-mini": {"in": 0.25, "out": 2.0}, "o3": {"in": 2.0, "out": 8.0},
               "o4-mini": {"in": 1.1, "out": 4.4}, "image": 0.04, "embedding": 0.02},
    "gemini": {"*": {"in": 0.3, "out": 2.5}, "gemini-2.5-pro": {"in": 1.25, "out": 10.0}, "gemini-2.5-flash": {"in": 0.3, "out": 2.5},
               "gemini-2.5-flash-lite": {"in": 0.1, "out": 0.4}, "image": 0.04, "video_per_second": 0.40, "embedding": 0.0},
    "mock": {"*": {"in": 0.0, "out": 0.0}},
}


def pricing_table() -> dict:
    """Listino effettivo: default sovrascritto dal JSON salvato nel pannello (impostazione pricing_json)."""
    table = json.loads(json.dumps(DEFAULT_PRICING))
    raw = getattr(settings, "pricing_json", "") or ""
    if raw.strip():
        try:
            custom = json.loads(raw)
            for prov, entries in custom.items():
                table.setdefault(prov, {}).update(entries)
        except Exception as e:
            log.warning("pricing_json non valido: %s", e)
    return table


def _model_price(table: dict, provider: str, model: str) -> dict:
    prov = table.get(provider, {})
    best, best_len = prov.get("*", {"in": 0, "out": 0}), -1
    for prefix, price in prov.items():
        if isinstance(price, dict) and prefix != "*" and model.startswith(prefix) and len(prefix) > best_len:
            best, best_len = price, len(prefix)
    return best


def cache_factors(provider: str, model: str) -> tuple[float, float]:
    """(moltiplicatore lettura cache, moltiplicatore scrittura cache) rispetto al prezzo di input."""
    if provider == "anthropic":
        return 0.10, 1.25
    if provider == "openai":
        return (0.25 if (model or "").startswith(("gpt-4.1", "gpt-5", "o3", "o4")) else 0.50), 1.0
    if provider == "gemini":
        return 0.25, 1.0
    return 1.0, 1.0


def estimate_cost(table: dict, provider: str, model: str, kind: str, input_tokens: int, output_tokens: int, count: int = 1,
                  cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    prov = table.get(provider, {})
    if kind == "message":
        p = _model_price(table, provider, model or "")
        rf, wf = cache_factors(provider, model or "")
        pin = float(p.get("in", 0))
        return (input_tokens * pin + cache_read_tokens * pin * rf + cache_write_tokens * pin * wf
                + output_tokens * float(p.get("out", 0))) / 1_000_000
    if kind == "image":
        # immagini: generate da OpenAI o Gemini a seconda della configurazione; usiamo il prezzo del provider immagini
        img_prov = "openai" if settings.openai_api_key and settings.image_provider in ("auto", "openai") else "gemini"
        return count * float(table.get(img_prov, {}).get("image", 0.04))
    if kind == "video":
        return count * 8 * float(table.get("gemini", {}).get("video_per_second", 0.4))
    return 0.0


async def local_report(db: AsyncSession, family_id: str, since: datetime) -> dict:
    table = pricing_table()
    rows = (await db.execute(
        select(UsageLog.user_id, UsageLog.provider, UsageLog.model, UsageLog.kind, func.count(),
               func.sum(UsageLog.input_tokens), func.sum(UsageLog.output_tokens),
               func.sum(UsageLog.cache_read_tokens), func.sum(UsageLog.cache_write_tokens))
        .where(UsageLog.family_id == family_id, UsageLog.created_at >= since)
        .group_by(UsageLog.user_id, UsageLog.provider, UsageLog.model, UsageLog.kind))).all()
    users = {u.id: u.display_name for u in (await db.execute(select(User).where(User.family_id == family_id))).scalars()}
    by_provider: dict[str, dict] = {}
    by_user: dict[str, dict] = {}
    for uid, prov, model, kind, n, tin, tout, tcr, tcw in rows:
        prov = prov or "?"
        tin, tout, tcr, tcw = int(tin or 0), int(tout or 0), int(tcr or 0), int(tcw or 0)
        cost = estimate_cost(table, prov, model or "", kind, tin, tout, int(n), tcr, tcw)
        p = by_provider.setdefault(prov, {"cost": 0.0, "messages": 0, "input_tokens": 0, "output_tokens": 0, "images": 0, "videos": 0, "searches": 0,
                                          "cache_read_tokens": 0, "cache_write_tokens": 0, "cache_saved": 0.0})
        u = by_user.setdefault(uid, {"name": users.get(uid, uid), "cost": 0.0, "messages": 0, "images": 0, "videos": 0, "tokens": 0})
        p["cost"] += cost
        u["cost"] += cost
        if kind == "message":
            p["messages"] += n; u["messages"] += n
            p["input_tokens"] += tin + tcr + tcw; p["output_tokens"] += tout; u["tokens"] += tin + tcr + tcw + tout
            p["cache_read_tokens"] += tcr; p["cache_write_tokens"] += tcw
            if kind == "message" and tcr:
                # risparmio = quanto sarebbero costati i token letti dalla cache a prezzo pieno, meno quanto sono costati
                pin = float(_model_price(table, prov, model or "").get("in", 0))
                p["cache_saved"] += tcr * pin * (1 - cache_factors(prov, model or "")[0]) / 1_000_000
        elif kind == "image":
            p["images"] += n; u["images"] += n
        elif kind == "video":
            p["videos"] += n; u["videos"] += n
        elif kind == "web_search":
            p["searches"] += n
    return {"providers": by_provider, "users": sorted(by_user.values(), key=lambda x: -x["cost"])}


# ------------------------------------------------------------------ spesa reale (chiavi Admin)
async def anthropic_spend(admin_key: str, since: datetime) -> dict:
    """Cost report dell'organizzazione (richiede chiave Admin sk-ant-admin…)."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://api.anthropic.com/v1/organizations/cost_report",
                            params={"starting_at": since.strftime("%Y-%m-%dT00:00:00Z"), "bucket_width": "1d", "limit": 31},
                            headers={"x-api-key": admin_key, "anthropic-version": "2023-06-01"})
            r.raise_for_status()
            data = r.json()
        total = 0.0
        for bucket in data.get("data", []):
            for res in bucket.get("results", []):
                amt = res.get("amount")
                if isinstance(amt, dict):
                    amt = amt.get("value")
                total += float(amt or 0)
        # l'API riporta importi in centesimi di dollaro (stringa): normalizziamo se sembrano centesimi
        return {"ok": True, "usd": round(total / 100 if total > 1000 else total, 4), "raw": total, "note": "cost_report"}
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403, 404):
            return {"ok": False, "error": "la chiave non e' abilitata ai report di costo: serve una Admin key "
                                          "(console.anthropic.com → Settings → Admin keys)"}
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:160]}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


async def openai_spend(admin_key: str, since: datetime) -> dict:
    """Costi dell'organizzazione (richiede Admin API key)."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://api.openai.com/v1/organization/costs",
                            params={"start_time": int(since.timestamp()), "bucket_width": "1d", "limit": 31},
                            headers={"Authorization": f"Bearer {admin_key}"})
            r.raise_for_status()
            data = r.json()
        total = 0.0
        for bucket in data.get("data", []):
            for res in bucket.get("results", []):
                amt = res.get("amount") or {}
                total += float(amt.get("value", 0) or 0)
        return {"ok": True, "usd": round(total, 4)}
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return {"ok": False, "error": "la chiave non e' abilitata ai report di costo: serve una Admin key "
                                          "(platform.openai.com → Settings → Organization → Admin keys)"}
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:160]}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def full_report(db: AsyncSession, family_id: str) -> dict:
    since = month_start()
    local = await local_report(db, family_id, since)
    budgets = {}
    for prov in ("anthropic", "openai", "gemini"):
        try:
            budgets[prov] = float(getattr(settings, f"budget_{prov}", "") or 0)
        except ValueError:
            budgets[prov] = 0.0
    real = {}
    # usa la chiave Admin se presente, altrimenti tenta con la chiave normale (funziona solo se ha privilegi admin)
    a_key = settings.anthropic_admin_key or settings.anthropic_api_key
    o_key = settings.openai_admin_key or settings.openai_api_key
    if a_key:
        real["anthropic"] = await anthropic_spend(a_key, since)
        real["anthropic"]["via"] = "admin_key" if settings.anthropic_admin_key else "api_key"
    if o_key:
        real["openai"] = await openai_spend(o_key, since)
        real["openai"]["via"] = "admin_key" if settings.openai_admin_key else "api_key"
    out = []
    for prov in ("anthropic", "openai", "gemini"):
        est = local["providers"].get(prov, {}).get("cost", 0.0)
        spent = real.get(prov, {}).get("usd") if real.get(prov, {}).get("ok") else None
        used = spent if spent is not None else est
        b = budgets[prov]
        out.append({"provider": prov, "configured": bool(getattr(settings, f"{prov}_api_key", "")),
                    "estimated_usd": round(est, 4), "real": real.get(prov), "budget_usd": b,
                    "remaining_usd": round(b - used, 4) if b > 0 else None,
                    "percent": round(min(100.0, used / b * 100), 1) if b > 0 else None,
                    "stats": local["providers"].get(prov, {})})
    # modello locale: nessun costo, ma mostriamo quanto lavoro ha assorbito e cosa sarebbe costato nel cloud
    lo = local["providers"].get("ollama", {})
    local_tokens_in = lo.get("input_tokens", 0)
    local_tokens_out = lo.get("output_tokens", 0)
    cloud_msgs = sum(local["providers"].get(p, {}).get("messages", 0) for p in ("anthropic", "openai", "gemini"))
    ref_prov = settings.router_cloud_provider if settings.router_cloud_provider in ("anthropic", "openai", "gemini") else \
        next((p for p in ("anthropic", "openai", "gemini") if getattr(settings, f"{p}_api_key", "")), "anthropic")
    ref_model = getattr(settings, f"{ref_prov}_default_model", "")
    avoided = estimate_cost(pricing_table(), ref_prov, ref_model, "message", local_tokens_in, local_tokens_out) if lo else 0.0
    local_info = {"configured": bool(settings.ollama_url), "model": settings.ollama_default_model,
                  "messages": lo.get("messages", 0), "input_tokens": local_tokens_in, "output_tokens": local_tokens_out,
                  "cloud_messages": cloud_msgs, "avoided_usd": round(avoided, 4), "reference": f"{ref_prov} / {ref_model}"}
    return {"since": since.isoformat(), "providers": out, "users": local["users"], "pricing": pricing_table(), "local": local_info}
