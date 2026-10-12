"""Documenti e fogli di calcolo con le app ArtCraft: WordCraft (word processor) e GridCraft (foglio di calcolo),
open source in Rust, ognuna con il proprio server MCP (https://github.com/rickyb82/wordcraft, .../gridcraft).

Le app girano nei container `wordcraft` / `gridcraft` (extras/artcraft) ed espongono il server MCP; il client MCP di
FamilAI le registra come server "wordcraft" e "gridcraft" (tool mcp__wordcraft__*, mcp__gridcraft__*). Qui ci sono i
tool "comodi" che fanno il lavoro piu' comune in un colpo solo e registrano il risultato come file scaricabile in chat:
  - write_document     Markdown -> .docx/.pdf/.odt… (o conversione di un allegato)          [WordCraft]
  - write_spreadsheet  tabelle di valori/formule -> .xlsx/.csv… con tabella, formati, grafici [GridCraft]
I file passano dalle cartelle condivise <DATA_DIR>/wordcraft e <DATA_DIR>/gridcraft (stesso percorso nei container).
"""
from __future__ import annotations

import logging
import mimetypes
import re
import uuid
from pathlib import Path

from ..config import get_settings
from ..models import FileAsset
from .registry import ToolContext, ToolResult, register, unregister_prefix

settings = get_settings()
log = logging.getLogger(__name__)

WORDCRAFT, GRIDCRAFT = "wordcraft", "gridcraft"
APPS = {
    WORDCRAFT: {"save_tool": "save_document", "native_tool": "write_document", "formats": ("docx", "pdf", "odt", "rtf", "html", "md", "txt")},
    GRIDCRAFT: {"save_tool": "save_workbook", "native_tool": "write_spreadsheet", "formats": ("xlsx", "csv", "tsv", "json", "html")},
}


def app_dir(app: str) -> Path:
    p = settings.data_dir / app
    p.mkdir(parents=True, exist_ok=True)
    return p


def host_for(app: str) -> str:
    return settings.wordcraft_host if app == WORDCRAFT else settings.gridcraft_host


def _safe_name(name: str, ext: str) -> str:
    base = re.sub(r"[^\w.\- ]", "_", (name or "documento").strip())[:80].rstrip(". ") or "documento"
    if base.lower().endswith("." + ext):
        base = base[: -(len(ext) + 1)]
    return f"{base}.{ext}"


def _unique(path: Path) -> Path:
    return path if not path.exists() else path.with_name(f"{path.stem}-{uuid.uuid4().hex[:6]}{path.suffix}")


async def register_saved_file(ctx: ToolContext, path: str) -> dict | None:
    """Un file salvato da un'app nella sua cartella <DATA_DIR>/<app> diventa un FileAsset della chat (scaricabile)."""
    if not path:
        return None
    p = Path(path)
    try:
        if not p.is_file():
            return None
        parents = p.resolve().parents
        if not any(app_dir(a).resolve() in parents for a in APPS):
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


async def _source_asset(ctx: ToolContext, src_id: str) -> FileAsset | ToolResult:
    asset = await ctx.db.get(FileAsset, src_id)
    if not asset or asset.family_id != ctx.user.family_id:
        return ToolResult(f"Allegato {src_id} non trovato.", is_error=True)
    if not asset.path or not Path(asset.path).is_file():
        return ToolResult("Il file dell'allegato non e' piu' disponibile.", is_error=True)
    return asset


def _done(out: Path, art: dict, app_label: str) -> ToolResult:
    return ToolResult(f"File {out.name} creato con {app_label} e mostrato all'utente come allegato scaricabile "
                      f"(id {art['file_id']}). Non inventare link: il file e' gia' in chat.", artifacts=[art])


# ---------------------------------------------------------------- WordCraft: write_document ----
async def write_document(args: dict, ctx: ToolContext) -> ToolResult:
    from .mcp_client import mcp_manager

    if not mcp_manager.is_connected(WORDCRAFT):
        return ToolResult("WordCraft non e' attivo su questo server (./familai.sh wordcraft up).", is_error=True)
    fmt = str(args.get("format") or "docx").lower().lstrip(".")
    if fmt not in APPS[WORDCRAFT]["formats"]:
        return ToolResult(f"Formato non supportato: {fmt}. Usa uno tra {', '.join(APPS[WORDCRAFT]['formats'])}.", is_error=True)
    title = str(args.get("title") or args.get("filename") or "documento")
    out = _unique(app_dir(WORDCRAFT) / _safe_name(str(args.get("filename") or title), fmt))
    src_id = str(args.get("source_file_id") or "").strip()
    content = str(args.get("content") or "")
    tmp: Path | None = None
    try:
        if src_id:
            asset = await _source_asset(ctx, src_id)
            if isinstance(asset, ToolResult):
                return asset
            await mcp_manager.call(WORDCRAFT, "open_document", {"path": asset.path})
            if content.strip():
                await mcp_manager.call(WORDCRAFT, "execute", {"command": "caret.docEnd", "params": {}})
                await mcp_manager.call(WORDCRAFT, "type_text", {"text": "\n" + content, "paragraphs": True})
        else:
            if not content.strip():
                return ToolResult("Serve il contenuto del documento (Markdown) oppure source_file_id.", is_error=True)
            tmp = app_dir(WORDCRAFT) / f".tmp-{uuid.uuid4().hex}.md"
            md = content if content.lstrip().startswith("#") or not title else f"# {title}\n\n{content}"
            tmp.write_text(md, encoding="utf-8")
            await mcp_manager.call(WORDCRAFT, "open_document", {"path": str(tmp)})
        await mcp_manager.call(WORDCRAFT, "save_document", {"path": str(out)})
    except Exception as e:
        log.warning("write_document fallito: %s", e)
        return ToolResult(f"WordCraft: {type(e).__name__}: {str(e)[:400]}", is_error=True)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    art = await register_saved_file(ctx, str(out))
    return _done(out, art, "WordCraft") if art else ToolResult("WordCraft non ha prodotto il file.", is_error=True)


# ---------------------------------------------------------------- GridCraft: write_spreadsheet ----
def _col(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


async def write_spreadsheet(args: dict, ctx: ToolContext) -> ToolResult:
    from .mcp_client import mcp_manager

    if not mcp_manager.is_connected(GRIDCRAFT):
        return ToolResult("GridCraft non e' attivo su questo server (./familai.sh gridcraft up).", is_error=True)
    fmt = str(args.get("format") or "xlsx").lower().lstrip(".")
    if fmt not in APPS[GRIDCRAFT]["formats"]:
        return ToolResult(f"Formato non supportato: {fmt}. Usa uno tra {', '.join(APPS[GRIDCRAFT]['formats'])}.", is_error=True)
    title = str(args.get("title") or args.get("filename") or "foglio")
    out = _unique(app_dir(GRIDCRAFT) / _safe_name(str(args.get("filename") or title), fmt))
    src_id = str(args.get("source_file_id") or "").strip()
    sheets = args.get("sheets") or []
    if args.get("values") and not sheets:
        sheets = [{"values": args["values"]}]
    notes: list[str] = []
    try:
        if src_id:
            asset = await _source_asset(ctx, src_id)
            if isinstance(asset, ToolResult):
                return asset
            await mcp_manager.call(GRIDCRAFT, "open_workbook", {"path": asset.path})
        else:
            if not sheets:
                return ToolResult("Servono i dati (values o sheets) oppure source_file_id.", is_error=True)
            await mcp_manager.call(GRIDCRAFT, "new_workbook", {})
        for i, sh in enumerate(sheets):
            if not isinstance(sh, dict):
                continue
            if i > 0 and not src_id:
                try:
                    await mcp_manager.call(GRIDCRAFT, "execute_command", {"command": "home.insertSheet", "params": {}})
                except Exception as e:
                    notes.append(f"foglio {i + 1} non aggiunto ({str(e)[:80]})")
            if sh.get("name"):
                try:
                    await mcp_manager.call(GRIDCRAFT, "execute_command", {"command": "sheet.rename", "params": {"name": str(sh["name"])}})
                except Exception:
                    notes.append(f"nome foglio '{sh['name']}' non applicato")
            values = sh.get("values") or []
            start = str(sh.get("range") or "A1")
            if values:
                await mcp_manager.call(GRIDCRAFT, "write_range", {"range": start, "values": values})
                m = re.match(r"([A-Za-z]+)(\d+)$", start.split("!")[-1])
                if m and (sh.get("table", True) or sh.get("header_bold", True)):
                    c0 = sum((ord(ch) - 64) * 26 ** k for k, ch in enumerate(reversed(m.group(1).upper())))
                    r0 = int(m.group(2))
                    width = max(len(r) for r in values if isinstance(r, list)) if values else 0
                    end = f"{_col(c0 + width - 1)}{r0 + len(values) - 1}"
                    rng = f"{start}:{end}"
                    if sh.get("table", True) and len(values) > 1:
                        try:
                            await mcp_manager.call(GRIDCRAFT, "create_table", {"range": rng, "style": str(sh.get("table_style") or "TableStyleMedium2")})
                        except Exception as e:
                            notes.append(f"tabella non creata ({str(e)[:80]})")
                            try:
                                await mcp_manager.call(GRIDCRAFT, "format_range", {"range": f"{start}:{_col(c0 + width - 1)}{r0}", "bold": True})
                            except Exception:
                                pass
            for f in sh.get("formats") or []:
                if isinstance(f, dict) and f.get("range"):
                    try:
                        await mcp_manager.call(GRIDCRAFT, "format_range", f)
                    except Exception as e:
                        notes.append(f"formato {f.get('range')} non applicato ({str(e)[:60]})")
            for ch in sh.get("charts") or []:
                if isinstance(ch, dict) and ch.get("range"):
                    try:
                        await mcp_manager.call(GRIDCRAFT, "insert_chart", {k: v for k, v in ch.items() if k in ("range", "type", "subtype", "title", "at")} | {"type": ch.get("type") or "column"})
                    except Exception as e:
                        notes.append(f"grafico {ch.get('range')} non inserito ({str(e)[:60]})")
        await mcp_manager.call(GRIDCRAFT, "save_workbook", {"path": str(out)})
    except Exception as e:
        log.warning("write_spreadsheet fallito: %s", e)
        return ToolResult(f"GridCraft: {type(e).__name__}: {str(e)[:400]}", is_error=True)
    art = await register_saved_file(ctx, str(out))
    if not art:
        return ToolResult("GridCraft non ha prodotto il file.", is_error=True)
    res = _done(out, art, "GridCraft")
    if notes:
        res.content += " Note: " + "; ".join(notes) + "."
    return res


# ---------------------------------------------------------------- registrazione ----
def register_tools(app: str) -> None:
    """Chiamata dal client MCP quando il server dell'app e' connesso: il tool compare solo se l'app c'e'."""
    if app == WORDCRAFT:
        register(
            "write_document",
            "Crea un documento Word (.docx), PDF, ODT, RTF o HTML con il word processor WordCraft a partire da testo Markdown "
            "(titoli #, elenchi, grassetto, tabelle), oppure converte/estende un allegato (source_file_id) in un altro formato. "
            "Il file compare in chat pronto da scaricare. Per modifiche fini (stili, tabelle, revisioni) usa poi i tool "
            "mcp__wordcraft__* (open_document sul percorso del file, execute, save_document).",
            {"type": "object", "properties": {
                "title": {"type": "string", "description": "Titolo del documento (diventa anche il nome file)"},
                "content": {"type": "string", "description": "Contenuto in Markdown"},
                "format": {"type": "string", "enum": list(APPS[WORDCRAFT]["formats"]), "description": "Formato di uscita (default docx)"},
                "filename": {"type": "string", "description": "Nome file senza percorso (opzionale)"},
                "source_file_id": {"type": "string", "description": "Id di un allegato da aprire/convertire al posto di content"}},
             "required": []},
        )(write_document)
    elif app == GRIDCRAFT:
        register(
            "write_spreadsheet",
            "Crea un foglio di calcolo Excel (.xlsx) o CSV con GridCraft: passa le righe di valori (numeri, testo, formule che "
            "iniziano con =, es. \"=SUM(B2:B10)\"); la prima riga e' l'intestazione e diventa una tabella con filtri. Puoi "
            "aggiungere formati (format_range) e grafici (insert_chart) per intervallo, o convertire un allegato (source_file_id). "
            "Il file compare in chat pronto da scaricare e l'utente puo' aprirlo nell'editor. Per operazioni avanzate "
            "(pivot, ordinamenti, formati condizionali) usa poi i tool mcp__gridcraft__* (open_workbook sul percorso del file).",
            {"type": "object", "properties": {
                "title": {"type": "string", "description": "Titolo (diventa anche il nome file)"},
                "values": {"type": "array", "description": "Righe di celle del primo foglio (scorciatoia per sheets=[{values}])",
                           "items": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}}},
                "sheets": {"type": "array", "description": "Piu' fogli: [{name, range (default A1), values, table (default true), "
                           "table_style, formats:[{range, bold, numberFormat, fillColor, fontColor, horizontalAlign…}], "
                           "charts:[{range, type: column|bar|line|pie|area|scatter, title, at}]}]",
                           "items": {"type": "object"}},
                "format": {"type": "string", "enum": list(APPS[GRIDCRAFT]["formats"]), "description": "Formato di uscita (default xlsx)"},
                "filename": {"type": "string", "description": "Nome file senza percorso (opzionale)"},
                "source_file_id": {"type": "string", "description": "Id di un allegato (xlsx/csv/ods) da aprire/convertire; i dati in sheets vengono scritti sopra"}},
             "required": []},
        )(write_spreadsheet)


def unregister_tools(app: str) -> None:
    unregister_prefix(APPS[app]["native_tool"])
