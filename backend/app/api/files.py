from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import Chunk, FileAsset, Share
from ..policy.permissions import effective_policy
from ..schemas import FileOut
from ..security.sessions import AuthContext, require_auth
from ..services import rag
from ..services.access import require_access
from ..tools.documents import extract_text

settings = get_settings()
router = APIRouter(tags=["files"])

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt", ".md", ".csv", ".json", ".docx", ".xlsx",
               ".xlsm", ".mp4", ".mp3", ".wav", ".m4a", ".py", ".js", ".ts", ".html"}


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
        await require_access(db, "conversation", conversation_id, ctx.user, write=True)
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
        background.add_task(rag.index_file_background, asset.id)
    return _out(asset)


@router.post("/files/{fid}/reindex", response_model=FileOut)
async def reindex(fid: str, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    asset, _ = await require_access(db, "file", fid, ctx.user)
    await rag.index_file(asset.id, db)
    await db.refresh(asset)
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
    # file generati in una conversazione: accessibili a chi vede la conversazione
    return FileResponse(asset.path, media_type=asset.mime, filename=asset.filename,
                        content_disposition_type="inline")


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
