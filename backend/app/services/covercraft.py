"""CoverCraft (https://github.com/rickyb82/covercraft): verifica di copertura della connettivita' a un indirizzo dal database dell'operatore.

A differenza di MailCraft/RemoteCraft il server non conia token per utente: c'e' un solo token di servizio e l'utente viaggia
nell'header X-Covercraft-User. Il token quindi NON va mai nel browser: la web app (iframe su /covercraft/) chiama /covercraft/api/*,
che Caddy gira al proxy di questo backend (api/covercraft.py), il quale verifica la sessione Emily e aggiunge token e nome utente.
Per la sessione MCP in chat il "token utente" che il ponte riceve come prima riga e' semplicemente il nome dell'utente
(il token di servizio lo ha gia' il container).
"""
from __future__ import annotations

import logging
import unicodedata

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


def user_label(display_name: str, username: str) -> str:
    """Nome con cui CoverCraft registra le verifiche dell'utente (ASCII, come lo accetta il ponte MCP)."""
    raw = display_name or username or "utente"
    ascii_ = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    clean = "".join(c if (c.isalnum() or c in " ._@+-") else "_" for c in ascii_).strip()
    return (clean or username or "utente")[:80]


class CoverService:
    """Stessa interfaccia di PerUserService (enabled/user_token/revoke/health) cosi' mcp_client la tratta come le altre app per utente."""

    name = "CoverCraft"

    def __init__(self):
        self._names: dict[str, str] = {}   # user_id -> etichetta utente (riempita da api/covercraft o letta dal database)

    @property
    def url(self) -> str:
        return (settings.covercraft_url or "").rstrip("/")

    @property
    def token(self) -> str:
        return settings.covercraft_token or ""

    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def remember(self, user_id: str, display_name: str, username: str) -> str:
        lab = user_label(display_name, username)
        self._names[user_id] = lab
        return lab

    async def user_token(self, user_id: str, fresh: bool = False) -> str:
        """Per il ponte MCP: la 'prima riga' e' il nome dell'utente. Verifica anche che il server risponda (come fanno le altre app)."""
        if not self.enabled():
            raise RuntimeError("CoverCraft non e' attivo (./familai.sh covercraft up)")
        if user_id == "familai-system":
            if not await self.health():
                raise RuntimeError("il server CoverCraft non risponde")
            return "Emily"
        lab = self._names.get(user_id)
        if not lab:
            from ..db import SessionLocal
            from ..models import User
            async with SessionLocal() as db:
                u = await db.get(User, user_id)
            lab = self.remember(user_id, u.display_name if u else "", u.username if u else "") if u else "utente"
        return lab

    async def revoke(self, user_id: str) -> None:
        self._names.pop(user_id, None)

    async def health(self) -> bool:
        if not self.enabled():
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as cli:
                return (await cli.get(f"{self.url}/api/health")).status_code == 200
        except Exception:
            return False


svc = CoverService()
enabled = svc.enabled
health = svc.health
