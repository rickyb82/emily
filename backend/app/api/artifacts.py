from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import Artifact
from ..security.sessions import AuthContext, require_auth
from ..services.access import require_access
from ..tools.artifacts import artifact_out

settings = get_settings()
router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class ArtifactUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


@router.get("")
async def list_artifacts(conversation_id: str, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    await require_access(db, "conversation", conversation_id, ctx.user)
    rows = (await db.execute(select(Artifact).where(Artifact.conversation_id == conversation_id)
                             .order_by(Artifact.created_at))).scalars().all()
    return [artifact_out(a) for a in rows]


@router.get("/{aid}")
async def get_artifact(aid: str, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    a = await db.get(Artifact, aid)
    if not a:
        raise HTTPException(404)
    await require_access(db, "conversation", a.conversation_id, ctx.user)
    return {**artifact_out(a), "history": [{"version": h["version"], "created_at": h["created_at"]} for h in (a.history or [])]}


@router.get("/{aid}/versions/{version}")
async def get_version(aid: str, version: int, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    a = await db.get(Artifact, aid)
    if not a:
        raise HTTPException(404)
    await require_access(db, "conversation", a.conversation_id, ctx.user)
    if version == a.version:
        return artifact_out(a)
    for h in a.history or []:
        if h["version"] == version:
            return {**artifact_out(a), "version": version, "content": h["content"]}
    raise HTTPException(404, "Versione non trovata")


@router.patch("/{aid}")
async def update_artifact(aid: str, body: ArtifactUpdate, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    """Modifica manuale dall'editor: crea una nuova versione."""
    a = await db.get(Artifact, aid)
    if not a:
        raise HTTPException(404)
    await require_access(db, "conversation", a.conversation_id, ctx.user, write=True)
    if body.content is not None and body.content != a.content:
        hist = list(a.history or [])
        hist.append({"version": a.version, "content": a.content, "created_at": datetime.now(timezone.utc).isoformat()})
        a.history = hist[-settings.artifact_max_history:]
        a.content = body.content
        a.version += 1
    if body.title:
        a.title = body.title[:200]
    await db.commit()
    return artifact_out(a)


@router.get("/{aid}/raw")
async def raw(aid: str, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    """Contenuto grezzo per download / apertura in nuova scheda. Servito con CSP sandbox: niente cookie né API."""
    a = await db.get(Artifact, aid)
    if not a:
        raise HTTPException(404)
    await require_access(db, "conversation", a.conversation_id, ctx.user)
    mime = {"html": "text/html", "svg": "image/svg+xml", "markdown": "text/markdown", "mermaid": "text/plain"}.get(a.kind, "text/plain")
    ext = {"html": "html", "svg": "svg", "markdown": "md", "mermaid": "mmd"}.get(a.kind, {"python": "py", "javascript": "js",
           "typescript": "ts", "java": "java", "bash": "sh"}.get(a.language, "txt"))
    return Response(a.content, media_type=f"{mime}; charset=utf-8", headers={
        "Content-Security-Policy": "sandbox allow-scripts allow-modals allow-forms allow-popups; default-src 'none'; "
                                   "script-src 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; "
                                   "style-src 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
                                   "font-src https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; img-src * data: blob:; "
                                   "media-src * data: blob:; connect-src 'none'",
        "Content-Disposition": f'inline; filename="{a.title[:60].replace(chr(34), "")}.{ext}"',
        "X-Content-Type-Options": "nosniff",
    })
