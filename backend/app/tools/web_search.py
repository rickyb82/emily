from __future__ import annotations

import httpx

from ..config import get_settings
from .registry import ToolContext, ToolResult, register

settings = get_settings()


@register(
    "web_search",
    "Cerca informazioni aggiornate sul web. Usalo per notizie, fatti recenti, prezzi, orari o qualsiasi cosa "
    "che potrebbe essere cambiata. Restituisce titoli, URL e riassunti.",
    {"type": "object", "properties": {"query": {"type": "string", "description": "La ricerca da effettuare"},
                                      "max_results": {"type": "integer", "description": "Numero risultati (1-10)"}},
     "required": ["query"]},
    usage_kind="web_search",
)
async def web_search(args: dict, ctx: ToolContext) -> ToolResult:
    query = str(args.get("query", "")).strip()
    n = max(1, min(int(args.get("max_results", 5) or 5), 10))
    safe = bool(ctx.policy.get("safe_search"))
    if not query:
        return ToolResult("Query vuota", is_error=True)
    try:
        pref = (settings.web_search_provider or "auto").lower()
        order = {"tavily": ["tavily"], "brave": ["brave"], "openai": ["openai"], "gemini": ["gemini"],
                 "anthropic": ["openai", "gemini", "tavily", "brave"],   # 'anthropic' = nativo in chat; qui il fallback
                 }.get(pref, ["tavily", "brave", "openai", "gemini"])
        for backend in order:
            if backend == "tavily" and settings.tavily_api_key:
                return await _tavily(query, n, safe)
            if backend == "brave" and settings.brave_api_key:
                return await _brave(query, n, safe)
            if backend == "openai" and settings.openai_api_key:
                return await _openai(query, n, safe)
            if backend == "gemini" and settings.gemini_api_key:
                return await _gemini(query, n, safe)
        return await _duckduckgo(query, n, safe)
    except Exception as e:
        return ToolResult(f"Ricerca fallita: {e}", is_error=True)


SAFE_HINT = ("I risultati sono per un bambino: escludi contenuti violenti, sessuali, spaventosi o inadatti ai minori "
             "e preferisci fonti affidabili e divulgative. ")


async def _openai(query: str, n: int, safe: bool) -> ToolResult:
    """Ricerca web tramite l'API Responses di OpenAI (tool web_search): nessuna chiave aggiuntiva."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    prompt = ((SAFE_HINT if safe else "") +
              f"Cerca sul web: {query}\nRiporta i {n} risultati più utili come elenco: titolo, URL e 1-2 frasi di sintesi "
              "con le informazioni chiave (date, numeri). Rispondi in italiano.")
    r = await client.responses.create(model=settings.web_search_model_openai, tools=[{"type": "web_search_preview"}],
                                      input=prompt)
    text = getattr(r, "output_text", "") or ""
    urls = []
    for item in getattr(r, "output", []) or []:
        for c in getattr(item, "content", []) or []:
            for a in getattr(c, "annotations", []) or []:
                u = getattr(a, "url", None)
                if u and u not in urls:
                    urls.append(u)
    if urls:
        text += "\n\nFonti:\n" + "\n".join(f"- {u}" for u in urls[:10])
    return ToolResult(text or "Nessun risultato")


async def _gemini(query: str, n: int, safe: bool) -> ToolResult:
    """Ricerca web tramite Gemini con grounding su Google Search."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = ((SAFE_HINT if safe else "") +
              f"Cerca sul web: {query}\nRiporta i {n} risultati più utili come elenco: titolo, URL e 1-2 frasi di sintesi "
              "con le informazioni chiave (date, numeri). Rispondi in italiano.")
    r = await client.aio.models.generate_content(
        model=settings.web_search_model_gemini, contents=prompt,
        config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]))
    text = r.text or ""
    urls = []
    try:
        gm = r.candidates[0].grounding_metadata
        for ch in gm.grounding_chunks or []:
            u = getattr(getattr(ch, "web", None), "uri", None)
            if u and u not in urls:
                urls.append(u)
    except Exception:
        pass
    if urls:
        text += "\n\nFonti:\n" + "\n".join(f"- {u}" for u in urls[:10])
    return ToolResult(text or "Nessun risultato")


async def _tavily(query: str, n: int, safe: bool) -> ToolResult:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.tavily.com/search", json={
            "api_key": settings.tavily_api_key, "query": query, "max_results": n,
            "search_depth": "basic", "include_answer": True})
        r.raise_for_status()
        data = r.json()
    lines = []
    if data.get("answer"):
        lines.append(f"Risposta sintetica: {data['answer']}\n")
    for it in data.get("results", []):
        lines.append(f"- {it.get('title')}\n  {it.get('url')}\n  {it.get('content', '')[:400]}")
    return ToolResult("\n".join(lines) or "Nessun risultato")


async def _brave(query: str, n: int, safe: bool) -> ToolResult:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get("https://api.search.brave.com/res/v1/web/search",
                        params={"q": query, "count": n, "safesearch": "strict" if safe else "moderate"},
                        headers={"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
    lines = [f"- {it.get('title')}\n  {it.get('url')}\n  {it.get('description', '')[:400]}"
             for it in data.get("web", {}).get("results", [])]
    return ToolResult("\n".join(lines) or "Nessun risultato")


async def _duckduckgo(query: str, n: int, safe: bool) -> ToolResult:
    """Fallback senza chiave API (Instant Answer API di DuckDuckGo: risultati limitati)."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": 1,
                                                                 "kp": 1 if safe else -1})
        r.raise_for_status()
        data = r.json()
    lines = []
    if data.get("AbstractText"):
        lines.append(f"{data['AbstractText']}\n  {data.get('AbstractURL', '')}")
    for it in data.get("RelatedTopics", [])[:n]:
        if isinstance(it, dict) and it.get("Text"):
            lines.append(f"- {it['Text']}\n  {it.get('FirstURL', '')}")
    return ToolResult("\n".join(lines) or "Nessun risultato (configura TAVILY_API_KEY o BRAVE_API_KEY per una ricerca completa)")
