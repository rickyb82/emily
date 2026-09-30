"""Passkey / WebAuthn (libreria py_webauthn) usata come secondo fattore per gli adulti."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..config import get_settings
from ..models import User, WebAuthnCredential

settings = get_settings()

# challenge pendenti: chiave -> (challenge, scadenza)
_challenges: dict[str, tuple[bytes, float]] = {}
CHALLENGE_TTL = 300


def _store(key: str, challenge: bytes) -> None:
    now = time.time()
    for k in [k for k, (_, exp) in _challenges.items() if exp < now]:
        _challenges.pop(k, None)
    _challenges[key] = (challenge, now + CHALLENGE_TTL)


def _pop(key: str) -> bytes | None:
    item = _challenges.pop(key, None)
    if not item or item[1] < time.time():
        return None
    return item[0]


async def registration_options(db: AsyncSession, user: User, session_key: str) -> dict:
    existing = (await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id))).scalars().all()
    opts = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=user.id.encode(),
        user_name=user.email or user.username,
        user_display_name=user.display_name,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id) for c in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    _store(f"reg:{session_key}", opts.challenge)
    return json.loads(options_to_json(opts))


async def registration_verify(db: AsyncSession, user: User, session_key: str, credential: dict, name: str) -> WebAuthnCredential:
    challenge = _pop(f"reg:{session_key}")
    if not challenge:
        raise ValueError("Challenge scaduta, riprova")
    verification = verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=settings.webauthn_origin,
        require_user_verification=False,
    )
    cred = WebAuthnCredential(
        user_id=user.id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        transports=credential.get("response", {}).get("transports", []) or [],
        name=name or "Passkey",
    )
    db.add(cred)
    await db.commit()
    return cred


async def authentication_options(db: AsyncSession, user: User, session_key: str) -> dict:
    creds = (await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id))).scalars().all()
    opts = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id) for c in creds],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    _store(f"auth:{session_key}", opts.challenge)
    return json.loads(options_to_json(opts))


async def authentication_verify(db: AsyncSession, user: User, session_key: str, credential: dict) -> WebAuthnCredential:
    challenge = _pop(f"auth:{session_key}")
    if not challenge:
        raise ValueError("Challenge scaduta, riprova")
    from webauthn.helpers import base64url_to_bytes

    raw_id = base64url_to_bytes(credential["rawId"])
    cred = (
        await db.execute(
            select(WebAuthnCredential).where(
                WebAuthnCredential.user_id == user.id, WebAuthnCredential.credential_id == raw_id
            )
        )
    ).scalar_one_or_none()
    if not cred:
        raise ValueError("Passkey sconosciuta")
    verification = verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=settings.webauthn_origin,
        credential_public_key=cred.public_key,
        credential_current_sign_count=cred.sign_count,
        require_user_verification=False,
    )
    cred.sign_count = verification.new_sign_count
    cred.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return cred
