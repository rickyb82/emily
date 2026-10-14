"""Verifica copertura (CoverCraft): la pagina 📡 Copertura incornicia la web app; le sue chiamate API passano da qui.

Caddy gira /covercraft/api/<x> su /api/covercraft/p/<x>: questo proxy verifica la sessione Emily (cookie), aggiunge il token
di servizio e X-Covercraft-User con il nome dell'utente e inoltra al container. Il token non raggiunge mai il browser e
nessuno puo' spacciarsi per un altro utente.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import Role, Session, User
from ..security.sessions import AuthContext, _load_session, require_auth, user_has_second_factor
from ..services import covercraft

router = APIRouter(prefix="/covercraft", tags=["covercraft"])
settings = get_settings()

HOP = {"host", "content-length", "connection", "transfer-encoding", "cookie", "authorization", "x-covercraft-user", "accept-encoding"}
FRAME_TOKEN_S = 12 * 3600


def _sign(payload: str) -> str:
    return hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:40]


def mint_frame_token(session_id: str) -> str:
    """Token per la web app nell'iframe: la web app (ehttp) non manda i cookie, quindi le diamo un token firmato da noi che
    identifica la SUA sessione Emily (non il token di servizio). Il proxy lo verifica e ricarica la sessione a ogni chiamata."""
    exp = int(time.time()) + FRAME_TOKEN_S
    payload = f"{session_id}.{exp}"
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + _sign(payload)


async def _session_from_frame_token(tok: str, db: AsyncSession) -> AuthContext | None:
    try:
        b64, sig = tok.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode()
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        sid, exp = payload.rsplit(".", 1)
        if int(exp) < time.time():
            return None
    except Exception:
        return None
    sess = await db.get(Session, sid)
    if not sess or sess.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    user = await db.get(User, sess.user_id)
    if not user or not user.is_active:
        return None
    return AuthContext(user, sess)


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
    return {"path": "/covercraft/", "user": label, "lang": "it", "token": mint_frame_token(ctx.session.id)}


@router.post("/logout")
async def cover_logout(ctx: AuthContext = Depends(require_auth)):
    await covercraft.svc.revoke(ctx.user.id)
    from ..tools.mcp_client import mcp_manager
    await mcp_manager.drop_user_connections(ctx.user.id)
    return {"ok": True}


async def _frame_auth(request: Request, db: AsyncSession) -> AuthContext:
    """Come require_auth, ma per le chiamate fatte dalla web app nell'iframe: ehttp non manda i cookie, quindi la web app
    presenta il token di frame (Authorization: Bearer) coniato da /covercraft/session; in mancanza vale il cookie.
    Difesa CSRF: il token non e' nel cookie jar, e in piu' controlliamo l'origine (Sec-Fetch-Site / Origin / Referer)."""
    ctx = None
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        ctx = await _session_from_frame_token(auth[7:].strip(), db)
    if not ctx:
        ctx = await _load_session(request, db)
    if not ctx:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non autenticato (sessione Emily scaduta: ricarica la pagina Copertura)")
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
