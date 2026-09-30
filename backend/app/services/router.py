"""Router "Auto": un modello locale piccolo (Ollama) legge la richiesta e decide se rispondere in locale (gratis, veloce,
privato) o inoltrare al provider cloud. Tutto cio' che richiede tool, allegati o qualita' elevata va al cloud."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ..config import get_settings
from ..providers.registry import _providers, get_provider

log = logging.getLogger(__name__)
settings = get_settings()

AUTO_ID = "auto"

# segnali che richiedono tool o capacita' superiori: niente LLM, si va diretti al cloud
CLOUD_HINTS = re.compile(
    r"\b(cerca|ricerca|notizi|oggi|ieri|domani|meteo|prezz|quanto costa|ultim[ei]|aggiornat|sito|link|url|"
    r"immagin|disegn|foto|illustra|video|"
    r"codice|programm|script|funzione|bug|errore|debug|html|css|javascript|python|java|sql|api|app\b|gioco|"
    r"grafico|tabella excel|csv|pdf|documento|file|allegat|"
    r"artifact|pagina web|sito web|esegui|calcola precisamente|dimostra|analizza in dettaglio|"
    r"chiedi a (claude|gpt|gemini)|cosa ne pensa (claude|gpt|gemini))", re.I)

ROUTER_SYSTEM = """Sei un router. Decidi se una richiesta puo' essere gestita bene da un piccolo modello locale (8B) oppure
va inoltrata a un modello cloud potente. Rispondi SOLO con JSON: {"route":"local"|"cloud","confidence":1-5,"reason":"..."}.
Scegli "local" per: saluti e chiacchiere, domande semplici di cultura generale, definizioni, traduzioni brevi, riformulazioni,
riassunti di testo gia' presente, aiuto compiti elementari, storie brevi, consigli generici.
Scegli "cloud" per: programmazione o debug, matematica non banale, ragionamento a piu' passi, testi lunghi o creativi
elaborati, richieste che richiedono informazioni recenti o ricerca, immagini/video/file, analisi di documenti, richieste
ambigue o delicate (salute, legale, sicurezza), qualsiasi cosa in cui un errore costerebbe caro."""


@dataclass
class Route:
    provider_id: str
    model: str
    local: bool
    reason: str


def enabled(policy: dict | None = None) -> bool:
    if not settings.ollama_url or (settings.router_mode or "balanced").lower() == "off":
        return False
    if "ollama" not in _providers():
        return False
    return True if policy is None else (AUTO_ID in policy.get("allowed_providers", []) or "ollama" in policy.get("allowed_providers", []))


def cloud_provider(policy: dict) -> str | None:
    allowed = [p for p in policy.get("allowed_providers", []) if p in ("anthropic", "openai", "gemini")]
    pref = (settings.router_cloud_provider or "auto").lower()
    provs = _providers()
    if pref in provs and pref in allowed:
        return pref
    for k in ("anthropic", "openai", "gemini"):
        if k in provs and k in allowed:
            return k
    return None


async def decide(text: str, has_files: bool, policy: dict, history_tail: list[str]) -> Route:
    local_model = settings.ollama_default_model
    cloud = cloud_provider(policy)
    if not cloud:
        return Route("ollama", local_model, True, "nessun provider cloud disponibile")
    cloud_model = get_provider(cloud).default_model

    def to_cloud(reason: str) -> Route:
        return Route(cloud, cloud_model, False, reason)

    if has_files:
        return to_cloud("allegati presenti")
    if len(text) > 4000:
        return to_cloud("richiesta molto lunga")
    if CLOUD_HINTS.search(text):
        return to_cloud("richiede strumenti o capacita' avanzate")

    mode = (settings.router_mode or "balanced").lower()
    route, conf, reason = "local", 3, "classificazione non disponibile"
    try:
        prov = _providers()["ollama"]
        ctx = ("\n".join(history_tail[-4:]))[-1500:]
        prompt = (f"Ultimi scambi (contesto):\n{ctx}\n\n" if ctx else "") + f"Richiesta da classificare:\n{text[:2000]}"
        out = ""
        async for ev in prov.stream(settings.router_model or local_model, ROUTER_SYSTEM,
                                    [{"role": "user", "content": [{"type": "text", "text": prompt}]}], [], max_tokens=120):
            if ev.type == "text_delta":
                out += ev.text
        m = re.search(r"\{.*\}", out, re.S)
        data = json.loads(m.group(0)) if m else {}
        route = "cloud" if str(data.get("route", "")).lower().startswith("cloud") else "local"
        conf = int(data.get("confidence", 3) or 3)
        reason = str(data.get("reason", ""))[:120] or route
    except Exception as e:
        log.warning("Router locale non disponibile (%s): inoltro al cloud", e)
        return to_cloud("router locale non raggiungibile")

    if mode == "economico":
        go_local = not (route == "cloud" and conf >= 4)
    elif mode == "qualita":
        go_local = route == "local" and conf >= 4
    else:
        go_local = route == "local"
    return Route("ollama", local_model, True, reason) if go_local else to_cloud(reason)
