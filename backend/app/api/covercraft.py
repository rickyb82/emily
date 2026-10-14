"""Verifica copertura (CoverCraft): la pagina 📡 Copertura incornicia la web app; le sue chiamate API passano da qui.

Caddy gira /covercraft/api/<x> su /api/covercraft/p/<x>: questo proxy verifica la sessione Emily (cookie), aggiunge il token
di servizio e X-Covercraft-User con il nome dell'utente e inoltra al container. Il token non raggiunge mai il browser e
nessuno puo' spacciarsi per un altro utente.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import Role
from ..security.sessions import AuthContext, _load_session, require_auth, user_has_second_factor
from ..services import covercraft

router = APIRouter(prefix="/covercraft", tags=["covercraft"])
settings = get_settings()

HOP = {"host", "content-length", "connection", "transfer-encoding", "cookie", "authorization", "x-covercraft-user", "accept-encoding"}


@router.get("/session")
async def cover_session(ctx: AuthContext = Depends(require_auth)):
    """Dati per aprire la web app: /covercraft/?server=<origine>/covercraft&user=<nome>&lang=it (nessun token: lo mette il proxy)."""
    if ctx.user.role == Role.child:
        raise HTTPException(403, "La verifica copertura e' riservata agli adulti")
    if not covercraft.enabled():
        raise HTTPException(503, "CoverCraft non e' attivo su questo server (./familai.sh covercraft up)")
    if not await covercraft.health():
        raise HTTPException(502, "Il server CoverCraft non risponde (./familai.sh covercraft logs)")
    label = covercraft.svc.remember(ctx.user.id, ctx.user.display_name, ctx.user.username)
    return {"path": "/covercraft/", "user": label, "lang": "it"}


@router.post("/logout")
async def cover_logout(ctx: AuthContext = Depends(require_auth)):
    await covercraft.svc.revoke(ctx.user.id)
    from ..tools.mcp_client import mcp_manager
    await mcp_manager.drop_user_connections(ctx.user.id)
    return {"ok": True}


async def _frame_auth(request: Request, db: AsyncSession) -> AuthContext:
    """Come require_auth, ma per le chiamate fatte dalla web app nell'iframe (che non manda X-Requested-With):
    la difesa CSRF e' il controllo dell'origine (Sec-Fetch-Site / Origin / Referer devono essere i nostri)."""
    ctx = await _load_session(request, db)
    if not ctx:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non autenticato")
    if ctx.user.role == Role.child:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Riservato agli adulti")
    if not ctx.session.mfa_verified:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Verifica a due fattori richiesta", headers={"X-MFA": "required"})
    if settings.require_mfa_for_adults and ctx.session.auth_method != "google":
        from ..config import mfa_optional_on
        if not (mfa_optional_on() and (ctx.user.mfa_choice or "") == "skip") and not await user_has_second_factor(db, ctx.user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Attiva un secondo fattore prima di continuare", headers={"X-MFA": "enroll"})
    sfs = request.headers.get("sec-fetch-site", "")
    if sfs and sfs not in ("same-origin", "none"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origine non consentita")
    src = request.headers.get("origin") or request.headers.get("referer") or ""
    ours = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if src and ours and urlparse(src).netloc.lower() != ours.lower():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origine non consentita")
    return ctx


@router.api_route("/p/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def cover_proxy(path: str, request: Request, db: AsyncSession = Depends(get_db)):
    if request.method == "OPTIONS":
        return Response(status_code=204)
    if not covercraft.enabled():
        raise HTTPException(503, "CoverCraft non e' attivo")
    if path.startswith("users/") or path.startswith("admin"):
        raise HTTPException(404, "endpoint non disponibile")
    ctx = await _frame_auth(request, db)
    label = covercraft.svc._names.get(ctx.user.id) or covercraft.svc.remember(ctx.user.id, ctx.user.display_name, ctx.user.username)
    url = f"{covercraft.svc.url}/api/{path}"
    if request.url.query:
        # il token in query non e' ammesso dal browser: lo mettiamo noi nell'header
        q = "&".join(p for p in request.url.query.split("&") if not p.startswith("token=") and not p.startswith("user="))
        if q:
            url += "?" + q
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers["Authorization"] = f"Bearer {covercraft.svc.token}"
    headers["X-Covercraft-User"] = label
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as cli:
            r = await cli.request(request.method, url, headers=headers, content=body)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"CoverCraft non raggiungibile: {e}")
    out = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "cache-control")}
    out["Cache-Control"] = "no-store"
    return Response(content=r.content, status_code=r.status_code, headers=out)
