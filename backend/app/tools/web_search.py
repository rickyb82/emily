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
        if settings.web_search_provider == "brave" and settings.brave_api_key:
            return await _brave(query, n, safe)
        if settings.tavily_api_key:
            return await _tavily(query, n, safe)
        if settings.brave_api_key:
            return await _brave(query, n, safe)
        return await _duckduckgo(query, n, safe)
    except Exception as e:
        return ToolResult(f"Ricerca fallita: {e}", is_error=True)


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
