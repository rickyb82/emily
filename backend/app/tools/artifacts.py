"""Tool per creare/aggiornare artifact (pagine HTML, SVG, codice, markdown) mostrati nel pannello laterale."""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import get_settings
from ..models import Artifact
from .registry import ToolContext, ToolResult, register

settings = get_settings()
KINDS = ["html", "svg", "markdown", "code", "mermaid"]


def artifact_out(a: Artifact) -> dict:
    return {"id": a.id, "title": a.title, "kind": a.kind, "language": a.language, "version": a.version,
            "content": a.content, "conversation_id": a.conversation_id,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None}


@register(
    "create_artifact",
    "Crea un artifact: un contenuto autonomo e sostanzioso che l'utente vede in un pannello dedicato accanto alla chat, "
    "con anteprima live. Usalo per: pagine web/giochi/app HTML+CSS+JS (kind=html, tutto in un unico file, librerie solo "
    "da cdnjs.cloudflare.com), grafica SVG (kind=svg), diagrammi Mermaid (kind=mermaid), documenti lunghi in markdown "
    "(kind=markdown), programmi completi in un linguaggio (kind=code, con language). NON usarlo per frammenti brevi o "
    "spiegazioni: quelli vanno nel messaggio. Dopo la creazione non ripetere il contenuto nel messaggio: descrivilo in 1-2 frasi.",
    {"type": "object", "properties": {
        "title": {"type": "string", "description": "Titolo breve"},
        "kind": {"type": "string", "enum": KINDS},
        "language": {"type": "string", "description": "Per kind=code: python, javascript, typescript, java, bash…"},
        "content": {"type": "string", "description": "Contenuto completo"}},
     "required": ["title", "kind", "content"]},
    usage_kind="tool",
)
async def create_artifact(args: dict, ctx: ToolContext) -> ToolResult:
    kind = str(args.get("kind", "code"))
    if kind not in KINDS:
        return ToolResult(f"kind non valido, usa uno tra {KINDS}", is_error=True)
    if not ctx.conversation_id:
        return ToolResult("Artifact disponibili solo dentro una conversazione", is_error=True)
    a = Artifact(family_id=ctx.user.family_id, owner_id=ctx.user.id, conversation_id=ctx.conversation_id,
                 project_id=ctx.project_id, title=str(args.get("title", "Artifact"))[:200], kind=kind,
                 language=str(args.get("language", "") or "")[:40], content=str(args.get("content", "")))
    ctx.db.add(a)
    await ctx.db.commit()
    return ToolResult(f"Artifact creato (id {a.id}, versione 1). L'utente lo vede già nel pannello: non ricopiarne il contenuto.",
                      artifacts=[{"type": "artifact", **artifact_out(a)}])


@register(
    "update_artifact",
    "Aggiorna un artifact esistente (nuova versione). Passa il contenuto COMPLETO aggiornato, oppure una lista di "
    "sostituzioni testuali esatte (old -> new) per modifiche mirate senza riscrivere tutto.",
    {"type": "object", "properties": {
        "artifact_id": {"type": "string"},
        "title": {"type": "string"},
        "content": {"type": "string", "description": "Contenuto completo (alternativo a replacements)"},
        "replacements": {"type": "array", "items": {"type": "object", "properties": {
            "old": {"type": "string"}, "new": {"type": "string"}}, "required": ["old", "new"]}}},
     "required": ["artifact_id"]},
    usage_kind="tool",
)
async def update_artifact(args: dict, ctx: ToolContext) -> ToolResult:
    a = await ctx.db.get(Artifact, str(args.get("artifact_id", "")))
    if not a or a.conversation_id != ctx.conversation_id:
        return ToolResult("Artifact non trovato in questa conversazione", is_error=True)
    new_content = a.content
    if args.get("content") is not None:
        new_content = str(args["content"])
    for r in args.get("replacements") or []:
        old = str(r.get("old", ""))
        if not old or old not in new_content:
            return ToolResult(f"Testo da sostituire non trovato: {old[:80]!r}", is_error=True)
        new_content = new_content.replace(old, str(r.get("new", "")), 1)
    hist = list(a.history or [])
    hist.append({"version": a.version, "content": a.content, "created_at": datetime.now(timezone.utc).isoformat()})
    a.history = hist[-settings.artifact_max_history:]
    a.content = new_content
    a.version += 1
    if args.get("title"):
        a.title = str(args["title"])[:200]
    await ctx.db.commit()
    return ToolResult(f"Artifact aggiornato alla versione {a.version}.", artifacts=[{"type": "artifact", **artifact_out(a)}])
