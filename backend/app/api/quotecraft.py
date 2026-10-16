"""Preventivi (QuoteCraft): la pagina 💶 Preventivi incornicia la web app; le sue chiamate API passano da qui.

Caddy gira /quotecraft/api/<x> su /api/quotecraft/p/<x>: il proxy verifica la sessione Emily (token di frame o cookie),
aggiunge il token di servizio, X-Quotecraft-User (nome), X-Quotecraft-Role (admin per super admin e amministratori
dell'app) e X-Quotecraft-Mail-User (identita' MailCraft), e scarta qualunque `role`/`user`/`token` arrivi dal browser.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import Role
from ..security.sessions import AuthContext, require_auth
from ..services import quotecraft
from .covercraft import _frame_auth, mint_frame_token

router = APIRouter(prefix="/quotecraft", tags=["quotecraft"])
settings = get_settings()

HOP = {"host", "content-length", "connection", "transfer-encoding", "cookie", "authorization", "accept-encoding",
       "x-quotecraft-user", "x-quotecraft-role", "x-quotecraft-mail-user"}
STRIP_QS = ("token=", "user=", "role=", "mail_user=")


def _check(ctx: AuthContext) -> None:
    from ..services.apps import app_enabled
    if ctx.user.role == Role.child or not app_enabled(ctx.user, "quotecraft"):
        raise HTTPException(403, "I preventivi non sono abilitati per il tuo account: chiedi all'amministratore")
    if not quotecraft.enabled():
        raise HTTPException(503, "QuoteCraft non e' attivo su questo server (./familai.sh quotecraft up)")


@router.get("/session")
async def quote_session(ctx: AuthContext = Depends(require_auth)):
    """Dati per aprire la web app: /quotecraft/?server=<origine>/quotecraft&user=<nome>&lang=it&token=<frame>[&settings=off]."""
    _check(ctx)
    if not await quotecraft.health():
        raise HTTPException(502, "Il server QuoteCraft non risponde (./familai.sh quotecraft logs)")
    name, role, _ = quotecraft.svc.remember(ctx.user)
    return {"path": "/quotecraft/", "user": name, "lang": "it", "token": mint_frame_token(ctx.session.id), "admin": role == "admin"}


@router.post("/logout")
async def quote_logout(ctx: AuthContext = Depends(require_auth)):
    await quotecraft.svc.revoke(ctx.user.id)
    from ..tools.mcp_client import mcp_manager
    await mcp_manager.drop_user_connections(ctx.user.id)
    return {"ok": True}


@router.api_route("/p/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def quote_proxy(path: str, request: Request, db: AsyncSession = Depends(get_db)):
    if request.method == "OPTIONS":
        return Response(status_code=204)
    if not quotecraft.enabled():
        raise HTTPException(503, "QuoteCraft non e' attivo")
    ctx = await _frame_auth(request, db, app="quotecraft")
    name, role, mail_user = quotecraft.svc._ids.get(ctx.user.id) or quotecraft.svc.remember(ctx.user)
    url = f"{quotecraft.svc.url}/api/{path}"
    if request.url.query:
        q = "&".join(p for p in request.url.query.split("&") if not p.startswith(STRIP_QS))
        if q:
            url += "?" + q
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers["Authorization"] = f"Bearer {quotecraft.svc.token}"
    headers["X-Quotecraft-User"] = name
    headers["X-Quotecraft-Mail-User"] = mail_user
    if role == "admin":
        headers["X-Quotecraft-Role"] = "admin"
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)) as cli:
            r = await cli.request(request.method, url, headers=headers, content=body)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"QuoteCraft non raggiungibile: {e}")
    out = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "content-disposition")}
    out["Cache-Control"] = "no-store"
    return Response(content=r.content, status_code=r.status_code, headers=out)
