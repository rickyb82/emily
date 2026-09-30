"""Gestione sessioni via cookie HttpOnly + dispositivi fidati + rate limiting."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import Role, Session, TrustedDevice, User

settings = get_settings()
SESSION_COOKIE = "familai_session"
DEVICE_COOKIE = "familai_device"


# ---------- rate limiting (in memoria, sufficiente per uso domestico) ----------
class RateLimiter:
    def __init__(self, max_hits: int, window_s: int):
        self.max_hits = max_hits
        self.window_s = window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and q[0] < now - self.window_s:
            q.popleft()
        if len(q) >= self.max_hits:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Troppi tentativi, riprova tra qualche minuto")
        q.append(now)


login_limiter = RateLimiter(max_hits=10, window_s=300)
pin_limiter = RateLimiter(max_hits=8, window_s=300)


def client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "")


# ---------- cookie helpers ----------
def _set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


async def create_session(
    db: AsyncSession, response: Response, user: User, request: Request, mfa_verified: bool
) -> Session:
    hours = settings.session_hours_child if user.role == Role.child else settings.session_hours_adult
    sess = Session(
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=hours),
        mfa_verified=mfa_verified,
        user_agent=request.headers.get("user-agent", "")[:300],
        ip=client_ip(request),
        device_id=request.cookies.get(DEVICE_COOKIE),
    )
    db.add(sess)
    await db.commit()
    _set_cookie(response, SESSION_COOKIE, sess.id, hours * 3600)
    return sess


def set_device_cookie(response: Response, device_id: str) -> None:
    _set_cookie(response, DEVICE_COOKIE, device_id, 365 * 24 * 3600)


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


async def get_trusted_device(request: Request, db: AsyncSession) -> TrustedDevice | None:
    dev_id = request.cookies.get(DEVICE_COOKIE)
    if not dev_id:
        return None
    dev = await db.get(TrustedDevice, dev_id)
    if not dev or dev.revoked:
        return None
    dev.last_seen_at = datetime.now(timezone.utc)
    return dev


# ---------- dipendenze FastAPI ----------
class AuthContext:
    def __init__(self, user: User, session: Session):
        self.user = user
        self.session = session


async def _load_session(request: Request, db: AsyncSession) -> AuthContext | None:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    sess = await db.get(Session, sid)
    if not sess:
        return None
    if sess.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        await db.delete(sess)
        await db.commit()
        return None
    user = await db.get(User, sess.user_id)
    if not user or not user.is_active:
        return None
    return AuthContext(user, sess)


async def optional_auth(request: Request, db: AsyncSession = Depends(get_db)) -> AuthContext | None:
    return await _load_session(request, db)


def _csrf_check(request: Request) -> None:
    # Difesa in profondità oltre a SameSite=Strict: le richieste mutanti devono avere l'header custom.
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.headers.get("x-requested-with") != "FamilAI":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF check fallito")


async def require_auth(request: Request, db: AsyncSession = Depends(get_db)) -> AuthContext:
    """Utente autenticato, con MFA completata (se richiesta)."""
    ctx = await _load_session(request, db)
    if not ctx:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non autenticato")
    _csrf_check(request)
    if ctx.user.role != Role.child and not ctx.session.mfa_verified:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Verifica a due fattori richiesta", headers={"X-MFA": "required"})
    return ctx


async def require_pre_mfa(request: Request, db: AsyncSession = Depends(get_db)) -> AuthContext:
    """Sessione creata dopo la password ma prima della passkey (solo per completare la MFA)."""
    ctx = await _load_session(request, db)
    if not ctx:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non autenticato")
    _csrf_check(request)
    return ctx


async def require_adult(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    if ctx.user.role == Role.child:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Funzione riservata agli adulti")
    return ctx


async def require_admin(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    if ctx.user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Funzione riservata all'amministratore")
    return ctx


async def user_has_passkey(db: AsyncSession, user: User) -> bool:
    from ..models import WebAuthnCredential

    r = await db.execute(select(WebAuthnCredential.id).where(WebAuthnCredential.user_id == user.id).limit(1))
    return r.scalar_one_or_none() is not None
