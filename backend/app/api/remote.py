"""Assistenza remota (RemoteCraft): la pagina 🛟 Assistenza incornicia la web app con il token del tecnico."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..models import Role
from ..security.sessions import AuthContext, require_auth
from ..services import remotecraft

router = APIRouter(prefix="/remote", tags=["remote"])


@router.get("/session")
async def remote_session(ctx: AuthContext = Depends(require_auth)):
    """Token del tecnico per la web app: la pagina apre /remotecraft/?server=<origine>/remotecraft&lang=it#token=…"""
    from ..services.apps import app_enabled
    if ctx.user.role == Role.child or not app_enabled(ctx.user, "remotecraft"):
        raise HTTPException(403, "L'assistenza remota non e' abilitata per il tuo account: chiedi all'amministratore")
    if not remotecraft.enabled():
        raise HTTPException(503, "RemoteCraft non e' attivo su questo server (./familai.sh remotecraft up)")
    try:
        tok = await remotecraft.user_token(ctx.user.id)
    except Exception as e:
        raise HTTPException(502, f"RemoteCraft non raggiungibile: {e}")
    return {"token": tok, "path": "/remotecraft/", "lang": "it"}


@router.post("/logout")
async def remote_logout(ctx: AuthContext = Depends(require_auth)):
    try:
        await remotecraft.revoke(ctx.user.id)
    except Exception as e:
        raise HTTPException(502, f"RemoteCraft non raggiungibile: {e}")
    from ..tools.mcp_client import mcp_manager
    await mcp_manager.drop_user_connections(ctx.user.id)
    return {"ok": True}
