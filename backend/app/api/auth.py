from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, Family, Role, Session, TrustedDevice, User, WebAuthnCredential
from ..policy.permissions import effective_policy
from ..schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeOut,
    PinLoginRequest,
    RecoveryLoginRequest,
    TrustDeviceRequest,
    UserOut,
    WebAuthnVerifyRequest,
)
from ..security import totp as totp_svc
from ..security import webauthn_svc
from ..security.passwords import consume_recovery_code, generate_recovery_codes, hash_secret, verify_secret
from ..security.sessions import (
    AuthContext,
    clear_session_cookie,
    client_ip,
    create_session,
    get_trusted_device,
    login_limiter,
    pin_limiter,
    require_adult,
    require_adult_for_enrollment,
    require_auth,
    require_pre_mfa,
    set_device_cookie,
    user_has_passkey,
    user_has_totp,
    user_has_second_factor,
    passkey_enrollment_needed,
)
from ..providers.registry import available_providers

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


async def audit(db: AsyncSession, event: str, request: Request, user: User | None = None, detail: str = "") -> None:
    db.add(AuditLog(family_id=user.family_id if user else None, user_id=user.id if user else None,
                    event=event, detail=detail[:500], ip=client_ip(request)))
    await db.commit()


def _locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc))


async def _register_failure(db: AsyncSession, user: User) -> None:
    user.failed_logins += 1
    if user.failed_logins >= 5:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        user.failed_logins = 0
    await db.commit()


async def user_out(db: AsyncSession, user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.has_passkey = await user_has_passkey(db, user)
    out.has_totp = user_has_totp(user)
    out.effective_policy = effective_policy(user)
    return out


# ---------------- login adulti: password -> passkey ----------------
@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    login_limiter.check(client_ip(request))
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if not user or not user.is_active or user.role == Role.child or _locked(user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenziali non valide")
    if not verify_secret(user.password_hash, body.password):
        await _register_failure(db, user)
        await audit(db, "login_failed", request, user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenziali non valide")
    user.failed_logins = 0
    has_pk = await user_has_passkey(db, user)
    has_totp = user_has_totp(user)
    has_2fa = has_pk or has_totp
    # Se ha un secondo fattore deve usarlo; se non ce l'ha entra ma dovra' attivarne uno (se REQUIRE_MFA_FOR_ADULTS).
    await create_session(db, response, user, request, mfa_verified=not has_2fa)
    await audit(db, "login_password", request, user, "mfa_required" if has_2fa else "no_second_factor")
    return {"status": "mfa_required" if has_2fa else "ok", "must_enroll_passkey": (not has_2fa) and settings.require_mfa_for_adults,
            "methods": {"passkey": has_pk, "totp": has_totp}}


@router.post("/webauthn/authenticate/options")
async def webauthn_auth_options(ctx: AuthContext = Depends(require_pre_mfa), db: AsyncSession = Depends(get_db)):
    return await webauthn_svc.authentication_options(db, ctx.user, ctx.session.id)


@router.post("/webauthn/authenticate/verify")
async def webauthn_auth_verify(body: WebAuthnVerifyRequest, request: Request,
                               ctx: AuthContext = Depends(require_pre_mfa), db: AsyncSession = Depends(get_db)):
    try:
        await webauthn_svc.authentication_verify(db, ctx.user, ctx.session.id, body.credential)
    except Exception as e:
        await audit(db, "mfa_failed", request, ctx.user, str(e))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Verifica passkey fallita: {e}")
    ctx.session.mfa_verified = True
    await db.commit()
    await audit(db, "mfa_passkey_ok", request, ctx.user)
    return {"status": "ok"}


@router.post("/recovery")
async def recovery_login(body: RecoveryLoginRequest, request: Request,
                         ctx: AuthContext = Depends(require_pre_mfa), db: AsyncSession = Depends(get_db)):
    login_limiter.check("rec:" + client_ip(request))
    remaining = consume_recovery_code(ctx.user.recovery_codes or [], body.code)
    if remaining is None:
        await audit(db, "recovery_failed", request, ctx.user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Codice di recupero non valido")
    ctx.user.recovery_codes = remaining
    ctx.session.mfa_verified = True
    await db.commit()
    await audit(db, "recovery_ok", request, ctx.user, f"rimasti {len(remaining)}")
    return {"status": "ok", "remaining_codes": len(remaining)}


# ---------------- registrazione passkey (dopo il login) ----------------
@router.post("/webauthn/register/options")
async def webauthn_reg_options(ctx: AuthContext = Depends(require_adult_for_enrollment), db: AsyncSession = Depends(get_db)):
    return await webauthn_svc.registration_options(db, ctx.user, ctx.session.id)


@router.post("/webauthn/register/verify")
async def webauthn_reg_verify(body: WebAuthnVerifyRequest, request: Request,
                              ctx: AuthContext = Depends(require_adult_for_enrollment), db: AsyncSession = Depends(get_db)):
    try:
        cred = await webauthn_svc.registration_verify(db, ctx.user, ctx.session.id, body.credential, body.name)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Registrazione passkey fallita: {e}")
    ctx.session.mfa_verified = True
    codes: list[str] = []
    if not ctx.user.recovery_codes:
        codes, hashed = generate_recovery_codes()
        ctx.user.recovery_codes = hashed
    await db.commit()
    await audit(db, "passkey_registered", request, ctx.user, cred.name)
    return {"status": "ok", "credential_id": cred.id, "recovery_codes": codes}


@router.get("/webauthn/credentials")
async def list_credentials(ctx: AuthContext = Depends(require_adult), db: AsyncSession = Depends(get_db)):
    creds = (await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.user_id == ctx.user.id))).scalars().all()
    return [{"id": c.id, "name": c.name, "created_at": c.created_at, "last_used_at": c.last_used_at} for c in creds]


@router.delete("/webauthn/credentials/{cred_id}")
async def delete_credential(cred_id: str, request: Request, ctx: AuthContext = Depends(require_adult),
                            db: AsyncSession = Depends(get_db)):
    cred = await db.get(WebAuthnCredential, cred_id)
    if not cred or cred.user_id != ctx.user.id:
        raise HTTPException(404)
    await db.delete(cred)
    await db.commit()
    await audit(db, "passkey_deleted", request, ctx.user, cred.name)
    return {"status": "ok"}


@router.post("/recovery-codes/regenerate")
async def regenerate_recovery(request: Request, ctx: AuthContext = Depends(require_adult), db: AsyncSession = Depends(get_db)):
    codes, hashed = generate_recovery_codes()
    ctx.user.recovery_codes = hashed
    await db.commit()
    await audit(db, "recovery_regenerated", request, ctx.user)
    return {"recovery_codes": codes}


@router.post("/password")
async def change_password(body: ChangePasswordRequest, request: Request, ctx: AuthContext = Depends(require_adult),
                          db: AsyncSession = Depends(get_db)):
    if not verify_secret(ctx.user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password attuale errata")
    ctx.user.password_hash = hash_secret(body.new_password)
    # invalida le altre sessioni
    await db.execute(delete(Session).where(Session.user_id == ctx.user.id, Session.id != ctx.session.id))
    await db.commit()
    await audit(db, "password_changed", request, ctx.user)
    return {"status": "ok"}


# ---------------- dispositivi fidati + login bambini con PIN ----------------
@router.get("/device")
async def device_status(request: Request, db: AsyncSession = Depends(get_db)):
    dev = await get_trusted_device(request, db)
    await db.commit()
    if not dev:
        return {"trusted": False, "children": []}
    kids = (await db.execute(select(User).where(User.family_id == dev.family_id, User.role == Role.child,
                                                 User.is_active == True))).scalars().all()  # noqa: E712
    return {"trusted": True, "device_name": dev.name,
            "children": [{"id": k.id, "display_name": k.display_name, "avatar": k.avatar} for k in kids]}


@router.post("/device/trust")
async def trust_device(body: TrustDeviceRequest, request: Request, response: Response,
                       ctx: AuthContext = Depends(require_adult), db: AsyncSession = Depends(get_db)):
    dev = TrustedDevice(family_id=ctx.user.family_id, name=body.name, approved_by=ctx.user.id)
    db.add(dev)
    await db.commit()
    set_device_cookie(response, dev.id)
    await audit(db, "device_trusted", request, ctx.user, body.name)
    return {"status": "ok", "device_id": dev.id}


@router.post("/pin-login")
async def pin_login(body: PinLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    pin_limiter.check(client_ip(request))
    dev = await get_trusted_device(request, db)
    if not dev:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Questo dispositivo non è autorizzato: chiedi a un genitore di approvarlo")
    user = await db.get(User, body.user_id)
    if not user or user.family_id != dev.family_id or user.role != Role.child or not user.is_active or _locked(user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "PIN errato")
    if not verify_secret(user.pin_hash, body.pin):
        await _register_failure(db, user)
        await audit(db, "pin_failed", request, user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "PIN errato")
    user.failed_logins = 0
    await create_session(db, response, user, request, mfa_verified=True, auth_method="pin")
    await audit(db, "login_pin", request, user, dev.name)
    return {"status": "ok"}


# ---------------- sessione ----------------
@router.get("/me", response_model=MeOut)
async def me(ctx: AuthContext = Depends(require_pre_mfa), db: AsyncSession = Depends(get_db)):
    fam = await db.get(Family, ctx.user.family_id)
    u = await user_out(db, ctx.user)
    pol = u.effective_policy
    provs = [p for p in available_providers() if p["id"] in pol["allowed_providers"] or p["id"] == "mock"]
    if ctx.user.role == Role.child and pol.get("provider"):
        provs = [p for p in provs if p["id"] == pol["provider"]] or provs
    mfa_required = ctx.user.role != Role.child and (
        not ctx.session.mfa_verified or passkey_enrollment_needed(ctx, u.has_passkey or u.has_totp)
    )
    return MeOut(user=u, family_name=fam.name if fam else "", mfa_verified=ctx.session.mfa_verified,
                 mfa_required=mfa_required, providers=provs, tools=pol["allowed_tools"])


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from ..security.sessions import SESSION_COOKIE

    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        await db.execute(delete(Session).where(Session.id == sid))
        await db.commit()
    clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/sessions")
async def my_sessions(ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Session).where(Session.user_id == ctx.user.id))).scalars().all()
    return [{"id": s.id[:8], "current": s.id == ctx.session.id, "created_at": s.created_at, "ip": s.ip,
             "user_agent": s.user_agent} for s in rows]


@router.post("/sessions/revoke-others")
async def revoke_others(ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Session).where(Session.user_id == ctx.user.id, Session.id != ctx.session.id))
    await db.commit()
    return {"status": "ok"}


# ---------------- email: password dimenticata, invito, codice come secondo fattore ----------------
from pydantic import BaseModel as _BM  # noqa: E402
from pydantic import EmailStr  # noqa: E402

from ..services import email_codes, mailer  # noqa: E402


class ForgotRequest(_BM):
    email: EmailStr


class ResetRequest(_BM):
    email: EmailStr
    code: str
    new_password: str


class CodeRequest(_BM):
    code: str


@router.get("/features")
async def features():
    """Funzioni disponibili alla schermata di login (nessuna autenticazione)."""
    from . import google_auth

    return {"email": mailer.email_enabled(),
            "email_mfa": mailer.email_enabled() and str(settings.email_mfa_fallback).lower() in ("1", "true", "yes"),
            "google": google_auth.enabled()}


@router.post("/forgot")
async def forgot_password(body: ForgotRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Invia un codice di reset. Risponde sempre OK per non rivelare quali email esistono."""
    login_limiter.check("forgot:" + client_ip(request))
    if not mailer.email_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Invio email non configurato: chiedi all'amministratore")
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user and user.is_active and user.role != Role.child:
        code = await email_codes.issue(db, user, "reset")
        try:
            await mailer.send_code(user.email, user.display_name, code, "reset")
        except Exception as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Invio email fallito: {e}")
        await audit(db, "reset_code_sent", request, user)
    return {"status": "ok"}


@router.post("/reset")
async def reset_password(body: ResetRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Imposta una nuova password con il codice ricevuto via email (reset o invito)."""
    login_limiter.check("reset:" + client_ip(request))
    if len(body.new_password) < 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La password deve avere almeno 10 caratteri")
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if not user or not await email_codes.verify(db, user, ("reset", "invite"), body.code):
        await audit(db, "reset_failed", request, user)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Codice non valido o scaduto")
    user.password_hash = hash_secret(body.new_password)
    user.failed_logins, user.locked_until = 0, None
    await db.execute(delete(Session).where(Session.user_id == user.id))
    await db.commit()
    await audit(db, "password_reset", request, user)
    return {"status": "ok"}


@router.post("/mfa/email/send")
async def mfa_email_send(request: Request, ctx: AuthContext = Depends(require_pre_mfa), db: AsyncSession = Depends(get_db)):
    """Secondo fattore alternativo alla passkey: codice via email (se abilitato)."""
    if not (mailer.email_enabled() and str(settings.email_mfa_fallback).lower() in ("1", "true", "yes")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Codice via email non abilitato")
    login_limiter.check("mfa:" + ctx.user.id)
    code = await email_codes.issue(db, ctx.user, "mfa")
    try:
        await mailer.send_code(ctx.user.email, ctx.user.display_name, code, "mfa")
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Invio email fallito: {e}")
    return {"status": "ok", "hint": mask_email(ctx.user.email)}


@router.post("/mfa/email/verify")
async def mfa_email_verify(body: CodeRequest, request: Request, ctx: AuthContext = Depends(require_pre_mfa),
                           db: AsyncSession = Depends(get_db)):
    if not await email_codes.verify(db, ctx.user, ("mfa",), body.code):
        await audit(db, "mfa_email_failed", request, ctx.user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Codice non valido o scaduto")
    ctx.session.mfa_verified = True
    await db.commit()
    await audit(db, "mfa_email_ok", request, ctx.user)
    return {"status": "ok"}


def mask_email(e: str | None) -> str:
    if not e or "@" not in e:
        return ""
    name, dom = e.split("@", 1)
    return f"{name[:2]}…@{dom}"


# ---------------- app authenticator (TOTP): alternativa alla passkey ----------------
@router.post("/totp/setup")
async def totp_setup(ctx: AuthContext = Depends(require_adult_for_enrollment), db: AsyncSession = Depends(get_db)):
    """Genera un nuovo segreto (in attesa di conferma) e restituisce QR + segreto da digitare."""
    from ..services.settings_store import encrypt
    secret = totp_svc.new_secret()
    ctx.user.totp_pending = encrypt(secret)
    await db.commit()
    account = ctx.user.email or ctx.user.username
    fam = await db.get(Family, ctx.user.family_id)
    issuer = f"FamilAI {fam.name}" if fam and fam.name else "FamilAI"
    uri = totp_svc.provisioning_uri(secret, account, issuer)
    return {"secret": secret, "uri": uri, "qr_svg": totp_svc.qr_svg(uri)}


@router.post("/totp/confirm")
async def totp_confirm(body: CodeRequest, request: Request, ctx: AuthContext = Depends(require_adult_for_enrollment),
                       db: AsyncSession = Depends(get_db)):
    """Conferma il segreto con il primo codice generato dall'app: da qui in poi e' un secondo fattore valido."""
    from ..services.settings_store import decrypt
    if not ctx.user.totp_pending:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nessuna configurazione in corso: ricomincia")
    if not totp_svc.verify(decrypt(ctx.user.totp_pending), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Codice non valido: controlla l'ora del telefono e riprova")
    ctx.user.totp_secret = ctx.user.totp_pending
    ctx.user.totp_pending = None
    ctx.session.mfa_verified = True
    codes: list[str] = []
    if not ctx.user.recovery_codes:
        codes, hashed = generate_recovery_codes()
        ctx.user.recovery_codes = hashed
    await db.commit()
    await audit(db, "totp_enabled", request, ctx.user)
    return {"status": "ok", "recovery_codes": codes}


@router.post("/totp/verify")
async def totp_verify(body: CodeRequest, request: Request, ctx: AuthContext = Depends(require_pre_mfa),
                      db: AsyncSession = Depends(get_db)):
    """Secondo fattore al login: codice a 6 cifre dell'app authenticator."""
    from ..services.settings_store import decrypt
    if not ctx.user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "App authenticator non configurata")
    login_limiter.check("totp:" + ctx.user.id)
    if not totp_svc.verify(decrypt(ctx.user.totp_secret), body.code):
        await audit(db, "mfa_totp_failed", request, ctx.user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Codice non valido")
    ctx.session.mfa_verified = True
    await db.commit()
    await audit(db, "mfa_totp_ok", request, ctx.user)
    return {"status": "ok"}


@router.delete("/totp")
async def totp_disable(request: Request, ctx: AuthContext = Depends(require_adult), db: AsyncSession = Depends(get_db)):
    """Disattiva l'app authenticator (se resta senza secondo fattore dovra' riattivarne uno)."""
    ctx.user.totp_secret = None
    ctx.user.totp_pending = None
    await db.commit()
    await audit(db, "totp_disabled", request, ctx.user)
    return {"status": "ok"}


# ---------------- memoria: cosa l'assistente sa di me (trasparenza e controllo) ----------------
@router.get("/memory/me")
async def my_memory(ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    from ..models import MemoryItem
    rows = (await db.execute(select(MemoryItem).where(MemoryItem.family_id == ctx.user.family_id,
                                                       MemoryItem.status.in_(["approved", "pending"]))
                             .order_by(MemoryItem.created_at.desc()))).scalars().all()
    mine = [r for r in rows if r.user_id == ctx.user.id or r.subject_user_id == ctx.user.id or
            (r.scope == "family" and ctx.user.role != Role.child)]
    return [{"id": r.id, "text": r.text, "category": r.category, "scope": r.scope, "status": r.status,
             "mine": r.user_id == ctx.user.id or r.subject_user_id == ctx.user.id, "created_at": r.created_at} for r in mine]


@router.delete("/memory/{mid}")
async def delete_my_memory(mid: str, request: Request, ctx: AuthContext = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    """Ognuno puo' cancellare le voci che lo riguardano (i bambini solo le proprie)."""
    from ..models import MemoryItem
    m = await db.get(MemoryItem, mid)
    if not m or m.family_id != ctx.user.family_id:
        raise HTTPException(404)
    if not (m.user_id == ctx.user.id or m.subject_user_id == ctx.user.id or ctx.user.role == Role.admin):
        raise HTTPException(403, "Puoi cancellare solo le voci che ti riguardano")
    await db.delete(m)
    await db.commit()
    await audit(db, "memory_self_deleted", request, ctx.user, m.text[:120])
    return {"status": "ok"}
