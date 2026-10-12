"""Documenti Word/PDF con WordCraft (word processor open source in Rust, https://github.com/rickyb82/wordcraft).

WordCraft gira nel container `wordcraft` (extras/wordcraft) ed espone il suo server MCP; il client MCP di FamilAI lo
registra come server "wordcraft" (tool mcp__wordcraft__*: open_document, type_text, execute, save_document, render_page…).
Qui sopra c'e' un tool semplice, `write_document`, che fa il lavoro piu' comune in un colpo solo: Markdown → .docx/.pdf/.odt,
oppure conversione di un allegato, e registra il risultato come file scaricabile in chat. I file passano dalla cartella
condivisa <DATA_DIR>/wordcraft (montata allo stesso percorso nei due container).
"""
from __future__ import annotations

import logging
import mimetypes
import re
import uuid
from pathlib import Path

from ..config import get_settings
from ..models import FileAsset
from .registry import ToolContext, ToolResult, register

settings = get_settings()
log = logging.getLogger(__name__)

FORMATS = ("docx", "pdf", "odt", "rtf", "html", "md", "txt")


def _wc_dir() -> Path:
    p = settings.data_dir / "wordcraft"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(name: str, ext: str) -> str:
    base = re.sub(r"[^\w.\- ]", "_", (name or "documento").strip())[:80].rstrip(". ") or "documento"
    if base.lower().endswith("." + ext):
        base = base[: -(len(ext) + 1)]
    return f"{base}.{ext}"


async def register_saved_file(ctx: ToolContext, path: str) -> dict | None:
    """Un file salvato da WordCraft dentro <DATA_DIR>/wordcraft diventa un FileAsset della chat (scaricabile)."""
    if not path:
        return None
    p = Path(path)
    try:
        if not p.is_file() or _wc_dir().resolve() not in p.resolve().parents:
            return None
    except OSError:
        return None
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    asset = FileAsset(id=uuid.uuid4().hex, family_id=ctx.user.family_id, owner_id=ctx.user.id, project_id=ctx.project_id,
                      conversation_id=ctx.conversation_id, filename=p.name, mime=mime, size=p.stat().st_size,
                      path=str(p), kind="generated")
    ctx.db.add(asset)
    await ctx.db.commit()
    if p.suffix.lower() == ".png":
        return {"type": "image", "file_id": asset.id, "url": f"/files/{asset.id}", "mime": mime}
    return {"type": "file", "file_id": asset.id, "url": f"/files/{asset.id}", "filename": p.name, "mime": mime}


async def write_document(args: dict, ctx: ToolContext) -> ToolResult:
    from .mcp_client import WORDCRAFT, mcp_manager

    if not mcp_manager.is_connected(WORDCRAFT):
        return ToolResult("WordCraft non e' attivo su questo server (./familai.sh wordcraft up).", is_error=True)
    fmt = str(args.get("format") or "docx").lower().lstrip(".")
    if fmt not in FORMATS:
        return ToolResult(f"Formato non supportato: {fmt}. Usa uno tra {', '.join(FORMATS)}.", is_error=True)
    title = str(args.get("title") or args.get("filename") or "documento")
    out = _wc_dir() / _safe_name(str(args.get("filename") or title), fmt)
    if out.exists():
        out = out.with_name(f"{out.stem}-{uuid.uuid4().hex[:6]}{out.suffix}")

    src_id = str(args.get("source_file_id") or "").strip()
    content = str(args.get("content") or "")
    tmp: Path | None = None
    try:
        if src_id:
            asset = await ctx.db.get(FileAsset, src_id)
            if not asset or asset.family_id != ctx.user.family_id:
                return ToolResult(f"Allegato {src_id} non trovato.", is_error=True)
            src = Path(asset.path)
            if not src.is_file():
                return ToolResult("Il file dell'allegato non e' piu' disponibile.", is_error=True)
            await mcp_manager.call(WORDCRAFT, "open_document", {"path": str(src)})
            if content.strip():
                # testo aggiuntivo in coda al documento aperto
                await mcp_manager.call(WORDCRAFT, "execute", {"command": "caret.docEnd", "params": {}})
                await mcp_manager.call(WORDCRAFT, "type_text", {"text": "\n" + content, "paragraphs": True})
        else:
            if not content.strip():
                return ToolResult("Serve il contenuto del documento (Markdown) oppure source_file_id.", is_error=True)
            tmp = _wc_dir() / f".tmp-{uuid.uuid4().hex}.md"
            md = content if content.lstrip().startswith("#") or not title else f"# {title}\n\n{content}"
            tmp.write_text(md, encoding="utf-8")
            await mcp_manager.call(WORDCRAFT, "open_document", {"path": str(tmp)})
        await mcp_manager.call(WORDCRAFT, "save_document", {"path": str(out)})
    except Exception as e:
        log.warning("write_document fallito: %s", e)
        return ToolResult(f"WordCraft: {type(e).__name__}: {str(e)[:400]}", is_error=True)
    finally:
        if tmp:
            try:
                tmp.unlink()
            except OSError:
                pass

    art = await register_saved_file(ctx, str(out))
    if not art:
        return ToolResult("WordCraft non ha prodotto il file.", is_error=True)
    return ToolResult(f"Documento {out.name} creato con WordCraft e mostrato all'utente come allegato scaricabile "
                      f"(id {art['file_id']}). Non inventare link: il file e' gia' in chat.",
                      artifacts=[art])


def register_tools() -> None:
    """Chiamata dal client MCP quando il server WordCraft e' connesso: il tool compare solo se WordCraft c'e'."""
    register(
        "write_document",
        "Crea un documento Word (.docx), PDF, ODT, RTF o HTML con il word processor WordCraft a partire da testo Markdown "
        "(titoli #, elenchi, grassetto, tabelle), oppure converte/estende un allegato (source_file_id) in un altro formato. "
        "Il file compare in chat pronto da scaricare. Per modifiche fini (stili, tabelle, revisioni) usa poi i tool "
        "mcp__wordcraft__* (open_document sul percorso del file, execute, save_document).",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Titolo del documento (diventa anche il nome file)"},
            "content": {"type": "string", "description": "Contenuto in Markdown"},
            "format": {"type": "string", "enum": list(FORMATS), "description": "Formato di uscita (default docx)"},
            "filename": {"type": "string", "description": "Nome file senza percorso (opzionale)"},
            "source_file_id": {"type": "string", "description": "Id di un allegato da aprire/convertire al posto di content"}},
         "required": []},
        usage_kind="tool",
    )(write_document)
