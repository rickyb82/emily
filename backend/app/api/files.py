from __future__ import annotations

import logging
import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import Chunk, FileAsset, Role, Share
from ..policy.permissions import effective_policy
from ..schemas import FileOut
from ..security.sessions import AuthContext, require_auth
from ..services import rag
from ..services.access import require_access
from ..tools.documents import extract_text

settings = get_settings()
log = logging.getLogger(__name__)
router = APIRouter(tags=["files"])

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt", ".md", ".csv", ".tsv", ".json", ".docx", ".xlsx",
               ".xlsm", ".xls", ".xlsb", ".ods", ".mp4", ".mp3", ".wav", ".m4a", ".py", ".js", ".ts", ".html", ".odt", ".rtf", ".doc", ".tex",
               ".pptx", ".potx", ".ppsx", ".deckcraft", ".mm", ".opml", ".xmind", ".mmd", ".drawio"}
# formati che gli editor nel browser (WordCraft / GridCraft) possono aprire e salvare
WORDCRAFT_EXT = {".docx", ".docm", ".dotx", ".doc", ".odt", ".rtf", ".txt", ".md", ".html", ".htm", ".tex", ".json", ".pdf", ".png"}
GRIDCRAFT_EXT = {".xlsx", ".xlsm", ".xls", ".xlsb", ".ods", ".csv", ".tsv", ".txt", ".json", ".html", ".pdf", ".png"}
DECKCRAFT_EXT = {".pptx", ".potx", ".ppsx", ".deckcraft", ".pdf", ".png", ".jpg", ".jpeg", ".txt"}
IDEACRAFT_EXT = {".json", ".mm", ".opml", ".md", ".txt", ".mmd", ".xmind", ".drawio"}
EDITOR_EXT = WORDCRAFT_EXT | GRIDCRAFT_EXT | DECKCRAFT_EXT | IDEACRAFT_EXT


def _out(f: FileAsset) -> FileOut:
    o = FileOut.model_validate(f)
    o.url = f"/files/{f.id}"
    return o


@router.post("/files", response_model=FileOut)
async def upload(background: BackgroundTasks, file: UploadFile = File(...), project_id: str | None = Form(None),
                 conversation_id: str | None = Form(None),
                 ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    pol = effective_policy(ctx.user)
    name = re.sub(r"[^\w.\- ]", "_", file.filename or "file")[:200]
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Tipo di file non consentito ({ext})")
    if project_id:
        await require_access(db, "project", project_id, ctx.user, write=True)
    if conversation_id:
        conv, _ = await require_access(db, "conversation", conversation_id, ctx.user, write=True)
        # allegato in una chat di progetto: appartiene anche al progetto (visibile ai membri, usato nel RAG di progetto)
        if not project_id and conv.project_id:
            project_id = conv.project_id
    data = await file.read()
    max_bytes = int(pol.get("max_upload_mb", 20)) * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(413, f"File troppo grande (max {pol.get('max_upload_mb')} MB)")
    fid = uuid.uuid4().hex
    path = settings.uploads_dir / f"{fid}{ext}"
    path.write_bytes(data)
    mime = file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    asset = FileAsset(id=fid, family_id=ctx.user.family_id, owner_id=ctx.user.id, project_id=project_id,
                      conversation_id=conversation_id, filename=name, mime=mime, size=len(data), path=str(path))
    if not mime.startswith(("image/", "video/", "audio/")):
        asset.extracted_text = extract_text(path, mime) or ""
    asset.index_status = "pending" if rag.is_indexable(asset) else "none"
    db.add(asset)
    await db.commit()
    if asset.index_status == "pending":
        _schedule_reindex(asset.id)
    return _out(asset)


_reindex_gen: dict[str, int] = {}


def _schedule_reindex(file_id: str, delay: float = 20.0) -> None:
    """L'AutoSave degli editor salva ogni pochi secondi: reindicizza per il RAG solo quando il file e' fermo da un po',
    cosi' un documento in scrittura non tiene occupato il modello di embedding a ogni battuta."""
    import asyncio

    gen = _reindex_gen.get(file_id, 0) + 1
    _reindex_gen[file_id] = gen

    async def later():
        await asyncio.sleep(delay)
        if _reindex_gen.get(file_id) == gen:   # nessun salvataggio piu' recente nel frattempo
            _reindex_gen.pop(file_id, None)
            await rag.index_file_background(file_id)

    asyncio.get_running_loop().create_task(later())


@router.post("/files/{fid}/reindex", response_model=FileOut)
async def reindex(fid: str, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    asset, _ = await require_access(db, "file", fid, ctx.user)
    await rag.index_file(asset.id, db)
    await db.refresh(asset)
    return _out(asset)


@router.post("/files/wordcraft-save", response_model=FileOut)
async def wordcraft_save(request: Request, background: BackgroundTasks, file_id: str, conversation_id: str | None = None,
                         project_id: str | None = None, filename: str | None = None, ctx: AuthContext = Depends(require_auth),
                         db: AsyncSession = Depends(get_db)):
    """Salvataggio dagli editor nel browser, WordCraft e GridCraft (File > Salva / Esporta): il corpo e' il file, il nome arriva
    nell'header X-Filename. `file_id` e' il documento aperto: se esiste e l'estensione coincide viene sovrascritto
    (e reindicizzato); se non esiste (documento nuovo: id generato dal client) viene creato con quell'id; se
    l'estensione e' diversa (es. esportazione in PDF) nasce un nuovo file accanto all'originale."""
    from urllib.parse import unquote

    if ctx.user.role == Role.child:
        raise HTTPException(403, "Editor riservato agli adulti")
    if not re.fullmatch(r"[0-9a-f]{32}", file_id or ""):
        raise HTTPException(400, "file_id non valido")
    name = re.sub(r"[^\w.\- ]", "_", unquote(request.headers.get("X-Filename", "") or "documento.docx"))[:200]
    ext = Path(name).suffix.lower()
    existing = await db.get(FileAsset, file_id)
    if not ext:
        # nome senza estensione (PdfCraft lo ricava dall'URL): eredita quella del file aperto, altrimenti .docx
        ext = Path(existing.filename).suffix.lower() if existing else ".docx"
        name = f"{name}{ext}"
    if existing is not None and Path(existing.filename).suffix.lower() == ext:
        # il nome lo decide FamilAI (titolo dell'editor / elenco Documenti), non il nome interno dell'app
        name = existing.filename
    elif existing is None and filename:
        # documento nuovo: il nome scelto nella pagina Editor (l'estensione resta quella del contenuto salvato)
        stem = Path(re.sub(r"[^\w.\- ]", "_", filename)).stem.strip() or Path(name).stem
        name = f"{stem}{ext}"[:200]
    if ext not in EDITOR_EXT:
        raise HTTPException(400, f"Formato non consentito ({ext})")
    data = await request.body()
    log.info("editor-save: %s da %s (%d byte, file_id=%s)", name, ctx.user.username, len(data), file_id)
    max_bytes = int(effective_policy(ctx.user).get("max_upload_mb", 20)) * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(413, "File troppo grande")
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

    asset = existing
    if asset is not None:
        await require_access(db, "file", file_id, ctx.user, write=True)
        if Path(asset.filename).suffix.lower() != ext:
            # esportazione in un altro formato: nuovo file nella stessa chat/progetto
            nid = uuid.uuid4().hex
            path = settings.generated_dir / f"{nid}{ext}"
            path.write_bytes(data)
            new = FileAsset(id=nid, family_id=ctx.user.family_id, owner_id=ctx.user.id, project_id=asset.project_id,
                            conversation_id=asset.conversation_id, filename=name, mime=mime, size=len(data),
                            path=str(path), kind="generated")
            db.add(new)
            await db.commit()
            return _out(new)
        if not asset.path:
            raise HTTPException(400, "Questo file non e' modificabile")
        Path(asset.path).write_bytes(data)
        asset.filename, asset.mime, asset.size = name, mime, len(data)
    else:
        if conversation_id:
            conv, _ = await require_access(db, "conversation", conversation_id, ctx.user, write=True)
            project_id = project_id or conv.project_id
        if project_id:
            await require_access(db, "project", project_id, ctx.user, write=True)
        path = settings.generated_dir / f"{file_id}{ext}"
        path.write_bytes(data)
        asset = FileAsset(id=file_id, family_id=ctx.user.family_id, owner_id=ctx.user.id, project_id=project_id,
                          conversation_id=conversation_id, filename=name, mime=mime, size=len(data), path=str(path),
                          kind="generated")
        db.add(asset)
    if not mime.startswith(("image/", "video/", "audio/")):
        asset.extracted_text = extract_text(Path(asset.path), mime) or ""
        asset.index_status = "pending"
        await db.execute(delete(Chunk).where(Chunk.file_id == asset.id))
    await db.commit()
    if asset.index_status == "pending":
        background.add_task(rag.index_file_background, asset.id)
    return _out(asset)


class FileRename(BaseModel):
    filename: str


@router.patch("/files/{fid}", response_model=FileOut)
async def rename_file(fid: str, body: FileRename, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    """Rinomina un file (proprietario o permesso di scrittura). L'estensione resta quella originale."""
    asset, _ = await require_access(db, "file", fid, ctx.user, write=True)
    low = asset.filename.lower()
    old_ext = ".ideacraft.json" if low.endswith(".ideacraft.json") else Path(asset.filename).suffix
    clean = re.sub(r"[^\w.\- ]", "_", body.filename.strip())
    stem = re.sub(r"(\.ideacraft)?\.[A-Za-z0-9]{1,8}$", "", clean).strip(". ") if "." in clean else clean.strip(". ")
    if not stem:
        raise HTTPException(400, "Nome non valido")
    asset.filename = f"{stem}{old_ext}"[:200]
    await db.commit()
    return _out(asset)


@router.get("/files/rag-status")
async def rag_status(ctx: AuthContext = Depends(require_auth)):
    return {"embeddings": rag.embeddings_available(), "provider": settings.embedding_provider,
            "mode": "ibrida (semantica + parole chiave)" if rag.embeddings_available() else "solo parole chiave (BM25)"}


@router.get("/files", response_model=list[FileOut])
async def list_files(project_id: str | None = None, ctx: AuthContext = Depends(require_auth),
                     db: AsyncSession = Depends(get_db)):
    if project_id:
        await require_access(db, "project", project_id, ctx.user)
        rows = (await db.execute(select(FileAsset).where(FileAsset.project_id == project_id)
                                 .order_by(FileAsset.created_at.desc()))).scalars().all()
        return [_out(f) for f in rows]
    shared_ids = (await db.execute(select(Share.resource_id).where(
        Share.resource_type == "file", Share.family_id == ctx.user.family_id,
        or_(Share.target_user_id == ctx.user.id, Share.target_user_id.is_(None))))).scalars().all()
    rows = (await db.execute(select(FileAsset).where(
        FileAsset.family_id == ctx.user.family_id,
        or_(FileAsset.owner_id == ctx.user.id, FileAsset.id.in_(shared_ids or ["-"]))
    ).order_by(FileAsset.created_at.desc()).limit(200))).scalars().all()
    return [_out(f) for f in rows]


@router.get("/files/{fid}")
async def download(fid: str, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    asset, _ = await require_access(db, "file", fid, ctx.user)
    if not asset.path:   # file virtuale (es. archivio cronologia chat): serviamo il testo
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(asset.extracted_text or "", headers={"Content-Disposition": f'inline; filename="{asset.id}.txt"'})
    # file generati in una conversazione: accessibili a chi vede la conversazione.
    # no-store: i documenti vengono riscritti dagli editor, il browser non deve riproporre una copia vecchia.
    return FileResponse(asset.path, media_type=asset.mime, filename=asset.filename,
                        content_disposition_type="inline", headers={"Cache-Control": "no-store, private"})


@router.delete("/files/{fid}")
async def delete_file(fid: str, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    asset, level = await require_access(db, "file", fid, ctx.user)
    if level not in ("owner", "parent"):
        raise HTTPException(403)
    if asset.path:
        Path(asset.path).unlink(missing_ok=True)
    await db.execute(delete(Chunk).where(Chunk.file_id == asset.id))
    await db.delete(asset)
    await db.commit()
    return {"status": "ok"}
