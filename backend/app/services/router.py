"""Router "Auto": un modello locale piccolo (Ollama) legge la richiesta e decide se rispondere in locale (gratis, veloce,
privato) o inoltrare al provider cloud. Tutto cio' che richiede tool, allegati o qualita' elevata va al cloud."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ..config import get_settings
from ..providers.registry import LOCAL_IDS, _providers, get_provider, local_provider_id

log = logging.getLogger(__name__)
settings = get_settings()

AUTO_ID = "auto"

# segnali che richiedono tool o capacita' superiori: niente LLM, si va diretti al cloud
CLOUD_HINTS = re.compile(
    r"(cerca(mi|lo|la)?\s+(su|in|nel|sul)\s+(web|internet|google|rete)|notizie|meteo|quanto costa|prezzo attuale|"
    r"(genera|crea|fai|disegna|fammi|realizza)\w*\s+(un'?|una|la|le|delle?)?\s*(immagin|foto|illustrazion|disegn|video|logo)|"
    r"\b(codice|script|programma\w*|html|css|javascript|typescript|python|bug|debug|refactor|compila|eseguil?o)\b|"
    r"\b(pdf|documento allegato|allegat[oi]|questo file|analizza il file)\b|"
    r"\b(artifact|pagina web|app web|webapp|gioco|videogioco|dashboard)\b|"
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
    if (settings.router_mode or "balanced").lower() == "off" or not local_provider_id():
        return False
    allowed = set(policy.get("allowed_providers", [])) if policy is not None else None
    return True if allowed is None else bool({AUTO_ID, *LOCAL_IDS} & allowed)


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
    local_id = local_provider_id() or "ollama"
    local_model = get_provider(local_id).default_model
    cloud = cloud_provider(policy)
    if not cloud:
        return Route(local_id, local_model, True, "nessun provider cloud disponibile")
    cloud_model = get_provider(cloud).default_model

    def to_cloud(reason: str) -> Route:
        return Route(cloud, cloud_model, False, reason)

    if has_files:
        return to_cloud("allegati presenti")
    if len(text) > 4000:
        return to_cloud("richiesta molto lunga")
    m = CLOUD_HINTS.search(text)
    if m:
        hit = m.group(0).lower()
        # con SearXNG la ricerca web la fa anche il modello locale: non e' piu' un motivo per andare al cloud
        is_search = any(w in hit for w in ("cerca", "notizie", "meteo", "quanto costa", "prezzo"))
        if not (is_search and settings.searxng_url):
            return to_cloud(f"richiede strumenti/capacita' avanzate ('{m.group(0)[:30]}')")

    mode = (settings.router_mode or "balanced").lower()
    route, conf, reason = "local", 3, "classificazione non disponibile"
    try:
        # il classificatore gira su Ollama (modello piccolo, veloce) se c'e', altrimenti sul server locale stesso
        prov = _providers().get("ollama") or _providers()[local_id]
        router_model = settings.router_model if prov.id == "ollama" else local_model
        ctx = ("\n".join(history_tail[-4:]))[-1500:]
        prompt = (f"Ultimi scambi (contesto):\n{ctx}\n\n" if ctx else "") + f"Richiesta da classificare:\n{text[:2000]}"
        out = ""
        async for ev in prov.stream(router_model, ROUTER_SYSTEM,
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
    return Route(local_id, local_model, True, reason) if go_local else to_cloud(reason)
