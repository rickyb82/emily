"""Posta elettronica (MailCraft): la pagina ✉️ Posta incornicia la web app di MailCraft con il token dell'utente."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..models import Role
from ..services import mailcraft
from ..security.sessions import AuthContext, require_auth

router = APIRouter(prefix="/mail", tags=["mail"])


@router.get("/session")
async def mail_session(ctx: AuthContext = Depends(require_auth)):
    """Token utente per la web app: la pagina apre /mailcraft/?server=<origine>/mailcraft&token=…&lang=it."""
    if ctx.user.role == Role.child:
        raise HTTPException(403, "La posta e' riservata agli adulti")
    if not mailcraft.enabled():
        raise HTTPException(503, "MailCraft non e' attivo su questo server (./familai.sh mailcraft up)")
    try:
        tok = await mailcraft.user_token(ctx.user.id)
    except Exception as e:
        raise HTTPException(502, f"MailCraft non raggiungibile: {e}")
    return {"token": tok, "path": "/mailcraft/", "lang": "it"}


@router.post("/logout")
async def mail_logout(ctx: AuthContext = Depends(require_auth)):
    """Revoca i token di posta dell'utente (web e assistente)."""
    try:
        await mailcraft.revoke(ctx.user.id)
    except Exception as e:
        raise HTTPException(502, f"MailCraft non raggiungibile: {e}")
    from ..tools.mcp_client import mcp_manager
    await mcp_manager.drop_user_connections(ctx.user.id)
    return {"ok": True}
