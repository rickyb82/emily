from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Share, User
from ..policy.permissions import effective_policy
from ..schemas import ShareOut, ShareRequest
from ..security.sessions import AuthContext, require_auth
from ..services.access import RESOURCE_MODEL, require_access

router = APIRouter(prefix="/shares", tags=["shares"])


@router.get("/members")
async def family_members(ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User).where(User.family_id == ctx.user.family_id, User.is_active == True))).scalars().all()  # noqa: E712
    return [{"id": u.id, "display_name": u.display_name, "avatar": u.avatar, "role": u.role.value} for u in rows if u.id != ctx.user.id]


@router.get("", response_model=list[ShareOut])
async def list_shares(resource_type: str, resource_id: str, ctx: AuthContext = Depends(require_auth),
                      db: AsyncSession = Depends(get_db)):
    await require_access(db, resource_type, resource_id, ctx.user)
    rows = (await db.execute(select(Share).where(Share.resource_type == resource_type, Share.resource_id == resource_id))).scalars().all()
    return [ShareOut.model_validate(s) for s in rows]


@router.post("", response_model=ShareOut)
async def share(body: ShareRequest, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    if body.resource_type not in RESOURCE_MODEL:
        raise HTTPException(400, "Tipo risorsa non valido")
    if not effective_policy(ctx.user).get("can_share", True):
        raise HTTPException(403, "Non puoi condividere")
    resource, level = await require_access(db, body.resource_type, body.resource_id, ctx.user)
    if level != "owner":
        raise HTTPException(403, "Solo il proprietario può condividere")
    if body.target_user_id:
        target = await db.get(User, body.target_user_id)
        if not target or target.family_id != ctx.user.family_id:
            raise HTTPException(404, "Utente non trovato")
    perm = "write" if body.permission == "write" else "read"
    existing = (await db.execute(select(Share).where(
        Share.resource_type == body.resource_type, Share.resource_id == body.resource_id,
        Share.target_user_id == body.target_user_id))).scalar_one_or_none()
    if existing:
        existing.permission = perm
        await db.commit()
        return ShareOut.model_validate(existing)
    s = Share(family_id=ctx.user.family_id, resource_type=body.resource_type, resource_id=body.resource_id,
              owner_id=ctx.user.id, target_user_id=body.target_user_id, permission=perm)
    db.add(s)
    await db.commit()
    return ShareOut.model_validate(s)


@router.delete("/{share_id}")
async def unshare(share_id: str, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    s = await db.get(Share, share_id)
    if not s or (s.owner_id != ctx.user.id and ctx.user.role.value != "admin"):
        raise HTTPException(404)
    await db.delete(s)
    await db.commit()
    return {"status": "ok"}
