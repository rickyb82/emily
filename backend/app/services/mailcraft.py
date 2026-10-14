"""MailCraft (https://github.com/rickyb82/mailcraft): posta elettronica per utente.

Il server MailCraft gira in un container (`mailcraft-cli serve` multi-utente). Il backend lo chiama con il token di servizio
e indica l'utente con X-Mailcraft-User; per la web app (iframe su /mailcraft/) e per la sessione MCP in chat conia un token
*utente*, che vale solo per le caselle di quell'utente. I token coniati vengono tenuti in memoria (per processo) e riconiati
quando servono: chi apre la Posta vede sempre e solo la propria.
"""
from __future__ import annotations

import logging
import time

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

_tokens: dict[str, tuple[str, float]] = {}   # user_id -> (token, scadenza cache)
TOKEN_CACHE_S = 12 * 3600


class PerUserService:
    """Server "craft" multi-utente (MailCraft, RemoteCraft): token di servizio per il backend, token utente coniati con
    POST /api/users/<utente>/token, revoca con /revoke. Una istanza per app."""

    def __init__(self, name: str, url_attr: str, token_attr: str):
        self.name, self.url_attr, self.token_attr = name, url_attr, token_attr
        self._tokens: dict[str, tuple[str, float]] = {}

    @property
    def url(self) -> str:
        return str(getattr(settings, self.url_attr, "") or "").rstrip("/")

    @property
    def token(self) -> str:
        return str(getattr(settings, self.token_attr, "") or "")

    def enabled(self) -> bool:
        return bool(self.url and self.token)

    async def user_token(self, user_id: str, fresh: bool = False) -> str:
        if not self.enabled():
            raise RuntimeError(f"{self.name} non e' attivo (./familai.sh {self.name.lower()} up)")
        now = time.time()
        cached = self._tokens.get(user_id)
        if cached and not fresh and cached[1] > now:
            return cached[0]
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"{self.url}/api/users/{slug(user_id)}/token", headers={"Authorization": f"Bearer {self.token}"})
            r.raise_for_status()
            tok = str(r.json().get("token") or "")
        if not tok:
            raise RuntimeError(f"{self.name} non ha restituito un token")
        self._tokens[user_id] = (tok, now + TOKEN_CACHE_S)
        return tok

    async def revoke(self, user_id: str) -> None:
        self._tokens.pop(user_id, None)
        if not self.enabled():
            return
        async with httpx.AsyncClient(timeout=15) as cli:
            await cli.post(f"{self.url}/api/users/{slug(user_id)}/revoke", headers={"Authorization": f"Bearer {self.token}"})

    async def health(self) -> bool:
        if not self.enabled():
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as cli:
                return (await cli.get(f"{self.url}/api/health")).status_code == 200
        except Exception:
            return False


svc = PerUserService("MailCraft", "mailcraft_url", "mailcraft_token")


def enabled() -> bool:
    return bool(settings.mailcraft_url and settings.mailcraft_token)


def slug(user_id: str) -> str:
    """Id utente stabile per MailCraft (il server fa a sua volta lo slug: solo [a-z0-9-])."""
    return "u-" + "".join(c for c in user_id.lower() if c.isalnum() or c == "-")[:48]


async def user_token(user_id: str, fresh: bool = False) -> str:
    """Token utente per la web app e per il processo MCP dell'utente (coniato dal server con il token di servizio)."""
    if not enabled():
        raise RuntimeError("MailCraft non e' attivo (./familai.sh mailcraft up)")
    now = time.time()
    cached = _tokens.get(user_id)
    if cached and not fresh and cached[1] > now:
        return cached[0]
    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.post(f"{settings.mailcraft_url.rstrip('/')}/api/users/{slug(user_id)}/token",
                           headers={"Authorization": f"Bearer {settings.mailcraft_token}"})
        r.raise_for_status()
        tok = str(r.json().get("token") or "")
    if not tok:
        raise RuntimeError("MailCraft non ha restituito un token")
    _tokens[user_id] = (tok, now + TOKEN_CACHE_S)
    return tok


async def revoke(user_id: str) -> None:
    """Logout dalla posta: revoca tutti i token dell'utente (web e MCP)."""
    _tokens.pop(user_id, None)
    if not enabled():
        return
    async with httpx.AsyncClient(timeout=15) as cli:
        await cli.post(f"{settings.mailcraft_url.rstrip('/')}/api/users/{slug(user_id)}/revoke",
                       headers={"Authorization": f"Bearer {settings.mailcraft_token}"})


async def health() -> bool:
    if not enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as cli:
            r = await cli.get(f"{settings.mailcraft_url.rstrip('/')}/api/health")
            return r.status_code == 200
    except Exception:
        return False
