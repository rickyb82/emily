"""Invio email via SMTP (configurato dal pannello: smtp_*). Usa la libreria standard in un thread."""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from ..config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


def email_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def _send_sync(to: str, subject: str, text: str, html: str | None) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.smtp_from_name or "FamilAI", settings.smtp_from))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    security = (settings.smtp_security or "starttls").lower()
    port = int(settings.smtp_port or (465 if security == "ssl" else 587))
    # coerenza porta/sicurezza: 465 = SSL implicito, 587/25 = STARTTLS (evita "Connection unexpectedly closed")
    if port == 465 and security != "ssl":
        security = "ssl"
    elif port in (587, 25) and security == "ssl":
        security = "starttls"
    ctx = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(settings.smtp_host, port, timeout=20, context=ctx)
    else:
        server = smtplib.SMTP(settings.smtp_host, port, timeout=20)
    with server:
        server.ehlo()
        if security == "starttls":
            server.starttls(context=ctx)
            server.ehlo()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


async def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    if not email_enabled():
        raise RuntimeError("Email non configurata: imposta il server SMTP in Famiglia → Provider AI → Email")
    await asyncio.to_thread(_send_sync, to, subject, text, html)
    log.info("Email inviata a %s: %s", to, subject)


def _wrap(title: str, body_html: str) -> str:
    return f"""<div style="font-family:system-ui,sans-serif;max-width:560px;margin:auto;padding:24px;color:#1c1f26">
<h2 style="margin:0 0 16px">🏠 {settings.webauthn_rp_name}</h2>
<h3 style="margin:0 0 12px">{title}</h3>
{body_html}
<p style="color:#6b7280;font-size:12px;margin-top:24px">Se non ti aspettavi questa email puoi ignorarla.</p></div>"""


def base_url() -> str:
    return settings.webauthn_origin.rstrip("/")


async def send_invite(to: str, display_name: str, code: str, invited_by: str) -> None:
    link = f"{base_url()}/reset?email={to}&code={code}"
    text = (f"Ciao {display_name},\n{invited_by} ti ha aggiunto a {settings.webauthn_rp_name}.\n"
            f"Imposta la tua password aprendo questo link (valido 48 ore):\n{link}\n\n"
            f"Dopo il primo accesso ti verra' chiesto di registrare una passkey (Face ID / Touch ID / Windows Hello).")
    html = _wrap(f"Benvenuto/a, {display_name}!",
                 f"<p>{invited_by} ti ha aggiunto all'assistente di famiglia.</p>"
                 f"<p><a href=\"{link}\" style=\"background:#1f6feb;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none\">Imposta la password</a></p>"
                 f"<p style=\"color:#6b7280\">Il link vale 48 ore. Dopo il primo accesso ti verrà chiesto di registrare una passkey.</p>")
    await send_email(to, f"Il tuo accesso a {settings.webauthn_rp_name}", text, html)


async def send_code(to: str, display_name: str, code: str, purpose: str) -> None:
    what = {"reset": "reimpostare la password", "mfa": "completare l'accesso"}.get(purpose, "continuare")
    text = f"Ciao {display_name},\nil tuo codice per {what} e': {code}\nVale 10 minuti. Non condividerlo con nessuno."
    html = _wrap(f"Codice per {what}",
                 f"<p style=\"font-size:32px;letter-spacing:6px;font-weight:700\">{code}</p><p>Vale 10 minuti. Non condividerlo con nessuno.</p>")
    await send_email(to, f"{code} è il tuo codice {settings.webauthn_rp_name}", text, html)
