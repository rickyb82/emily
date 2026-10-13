"""Cartelle di Documenti (stile Finder): create dall'utente, annidabili; i file si spostano dentro con folder_id."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import FileAsset, Folder
from ..security.sessions import AuthContext, require_auth

router = APIRouter(prefix="/folders", tags=["folders"])


class FolderIn(BaseModel):
    name: str
    parent_id: str | None = None
    color: str = ""


class FolderPatch(BaseModel):
    name: str | None = None
    parent_id: str | None = None   # "" = radice
    color: str | None = None


def _clean(name: str) -> str:
    n = re.sub(r"[\x00-\x1f/\\]", " ", name or "").strip()[:120]
    if not n:
        raise HTTPException(400, "Nome cartella non valido")
    return n


def _out(f: Folder, files: int = 0, subfolders: int = 0) -> dict:
    return {"id": f.id, "name": f.name, "parent_id": f.parent_id, "color": f.color or "", "created_at": f.created_at,
            "files": files, "subfolders": subfolders}


async def _own(db: AsyncSession, fid: str, ctx: AuthContext) -> Folder:
    f = await db.get(Folder, fid)
    if not f or f.owner_id != ctx.user.id:
        raise HTTPException(404, "Cartella non trovata")
    return f


@router.get("")
async def list_folders(ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    """Tutte le cartelle dell'utente (l'albero lo ricostruisce il client) con il numero di file e sottocartelle."""
    rows = (await db.execute(select(Folder).where(Folder.owner_id == ctx.user.id).order_by(Folder.name))).scalars().all()
    nfiles = dict((await db.execute(select(FileAsset.folder_id, func.count()).where(FileAsset.owner_id == ctx.user.id, FileAsset.folder_id.isnot(None))
                                    .group_by(FileAsset.folder_id))).all())
    nsub = dict((await db.execute(select(Folder.parent_id, func.count()).where(Folder.owner_id == ctx.user.id, Folder.parent_id.isnot(None))
                                  .group_by(Folder.parent_id))).all())
    return [_out(f, nfiles.get(f.id, 0), nsub.get(f.id, 0)) for f in rows]


@router.post("")
async def create_folder(body: FolderIn, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    if body.parent_id:
        await _own(db, body.parent_id, ctx)
    f = Folder(family_id=ctx.user.family_id, owner_id=ctx.user.id, parent_id=body.parent_id or None, name=_clean(body.name), color=body.color[:20])
    db.add(f)
    await db.commit()
    return _out(f)


async def _descendants(db: AsyncSession, fid: str, owner: str) -> set[str]:
    rows = (await db.execute(select(Folder.id, Folder.parent_id).where(Folder.owner_id == owner))).all()
    kids: dict[str | None, list[str]] = {}
    for i, p in rows:
        kids.setdefault(p, []).append(i)
    out, stack = set(), [fid]
    while stack:
        cur = stack.pop()
        for k in kids.get(cur, []):
            if k not in out:
                out.add(k)
                stack.append(k)
    return out


@router.patch("/{fid}")
async def patch_folder(fid: str, body: FolderPatch, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    f = await _own(db, fid, ctx)
    if body.name is not None:
        f.name = _clean(body.name)
    if body.color is not None:
        f.color = body.color[:20]
    if body.parent_id is not None:
        new_parent = body.parent_id or None
        if new_parent:
            await _own(db, new_parent, ctx)
            if new_parent == fid or new_parent in await _descendants(db, fid, ctx.user.id):
                raise HTTPException(400, "Non puoi spostare una cartella dentro se stessa")
        f.parent_id = new_parent
    await db.commit()
    return _out(f)


@router.delete("/{fid}")
async def delete_folder(fid: str, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    """Elimina la cartella: i file e le sottocartelle risalgono nella cartella superiore (niente cancellazioni a cascata)."""
    f = await _own(db, fid, ctx)
    await db.execute(update(FileAsset).where(FileAsset.folder_id == fid).values(folder_id=f.parent_id))
    await db.execute(update(Folder).where(Folder.parent_id == fid, Folder.owner_id == ctx.user.id).values(parent_id=f.parent_id))
    await db.delete(f)
    await db.commit()
    return {"ok": True}
