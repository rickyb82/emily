"""QuoteCraft (https://github.com/rickyb82/quotecraft): preventivatore con listino per il reparto commerciale.

Come CoverCraft: un solo token di servizio, l'utente viaggia negli header. In piu' il server distingue chi puo' cambiare
listino, carta intestata, azienda e impostazioni (`X-Quotecraft-Role: admin`): per Emily sono il super amministratore e gli
amministratori dell'app "quotecraft". La spedizione passa da MailCraft a nome dell'utente: QuoteCraft chiama MailCraft con
l'identita' che riceve in `X-Quotecraft-Mail-User`, cioe' lo slug con cui Emily registra l'utente in MailCraft.
La "prima riga" del ponte MCP e' `nome<TAB>ruolo<TAB>identita-mail`.
"""
from __future__ import annotations

import logging

import httpx

from ..config import get_settings
from ..models import User
from .covercraft import user_label

log = logging.getLogger(__name__)
settings = get_settings()


def identity(user: User) -> tuple[str, str, str]:
    """(nome mostrato, ruolo per QuoteCraft, identita' MailCraft) di un utente Emily."""
    from .apps import is_app_admin
    from .mailcraft import slug
    role = "admin" if is_app_admin(user, "quotecraft") else "user"
    return user_label(user.display_name, user.username), role, slug(user.id)


class QuoteService:
    name = "QuoteCraft"

    def __init__(self):
        self._ids: dict[str, tuple[str, str, str]] = {}

    @property
    def url(self) -> str:
        return (settings.quotecraft_url or "").rstrip("/")

    @property
    def token(self) -> str:
        return settings.quotecraft_token or ""

    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def remember(self, user: User) -> tuple[str, str, str]:
        ident = identity(user)
        self._ids[user.id] = ident
        return ident

    async def user_token(self, user_id: str, fresh: bool = False) -> str:
        """Per il ponte MCP: prima riga `nome<TAB>ruolo<TAB>identita-mail`."""
        if not self.enabled():
            raise RuntimeError("QuoteCraft non e' attivo (./familai.sh quotecraft up)")
        if user_id == "familai-system":
            if not await self.health():
                raise RuntimeError("il server QuoteCraft non risponde")
            return "Emily\tuser\t"
        ident = self._ids.get(user_id)
        if not ident:
            from ..db import SessionLocal
            async with SessionLocal() as db:
                u = await db.get(User, user_id)
            ident = self.remember(u) if u else ("utente", "user", "")
        return "\t".join(ident)

    async def revoke(self, user_id: str) -> None:
        self._ids.pop(user_id, None)

    async def health(self) -> bool:
        if not self.enabled():
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as cli:
                return (await cli.get(f"{self.url}/api/health")).status_code == 200
        except Exception:
            return False


svc = QuoteService()
enabled = svc.enabled
health = svc.health
