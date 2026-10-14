"""RemoteCraft (https://github.com/rickyb82/remotecraft): assistenza remota (server RustDesk + gestionale) per tecnico.
Stesso schema di MailCraft: token di servizio per il backend, token utente per la web app e per la sessione MCP."""
from __future__ import annotations

from .mailcraft import PerUserService

svc = PerUserService("RemoteCraft", "remotecraft_url", "remotecraft_token")
enabled = svc.enabled
user_token = svc.user_token
revoke = svc.revoke
health = svc.health
