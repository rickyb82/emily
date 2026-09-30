from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import AgeGroup, AuditLog, Conversation, Message, Role, Session, TrustedDevice, UsageLog, User
from ..policy.permissions import DEFAULTS, effective_policy
from ..schemas import CreateMemberRequest, UpdateMemberRequest, UserOut
from ..security.passwords import hash_secret
from ..security.sessions import AuthContext, require_admin
from ..tools.mcp_client import mcp_manager
from .auth import audit, user_out

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/policy-defaults")
async def policy_defaults(ctx: AuthContext = Depends(require_admin)):
    return DEFAULTS


@router.get("/members", response_model=list[UserOut])
async def members(ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User).where(User.family_id == ctx.user.family_id).order_by(User.created_at))).scalars().all()
    return [await user_out(db, u) for u in rows]


@router.post("/members", response_model=UserOut)
async def create_member(body: CreateMemberRequest, request: Request, ctx: AuthContext = Depends(require_admin),
                        db: AsyncSession = Depends(get_db)):
    role = Role(body.role)
    if role == Role.child:
        if not body.pin:
            raise HTTPException(400, "Per un bambino serve un PIN")
        age_group = AgeGroup(body.age_group) if body.age_group in ("young", "kid", "teen") else AgeGroup.kid
    else:
        if not body.email or not body.password:
            raise HTTPException(400, "Per un adulto servono email e password")
        age_group = AgeGroup.adult
    u = User(family_id=ctx.user.family_id, username=body.username.lower(), display_name=body.display_name,
             avatar=body.avatar, role=role, age_group=age_group, birth_year=body.birth_year,
             email=body.email.lower() if body.email else None,
             password_hash=hash_secret(body.password) if body.password else None,
             pin_hash=hash_secret(body.pin) if body.pin else None)
    db.add(u)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(400, "Username o email già in uso")
    await audit(db, "member_created", request, ctx.user, f"{u.username} ({role.value})")
    return await user_out(db, u)


@router.patch("/members/{uid}", response_model=UserOut)
async def update_member(uid: str, body: UpdateMemberRequest, request: Request,
                        ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, uid)
    if not u or u.family_id != ctx.user.family_id:
        raise HTTPException(404)
    data = body.model_dump(exclude_none=True)
    if "password" in data:
        u.password_hash = hash_secret(data.pop("password"))
        await db.execute(delete(Session).where(Session.user_id == u.id))
    if "pin" in data:
        u.pin_hash = hash_secret(data.pop("pin"))
    if "role" in data:
        if u.id == ctx.user.id and data["role"] != "admin":
            raise HTTPException(400, "Non puoi togliere a te stesso il ruolo admin")
        u.role = Role(data.pop("role"))
    if "age_group" in data:
        u.age_group = AgeGroup(data.pop("age_group"))
    if "is_active" in data and u.id == ctx.user.id and not data["is_active"]:
        raise HTTPException(400, "Non puoi disattivare te stesso")
    for k, v in data.items():
        setattr(u, k, v)
    await db.commit()
    await audit(db, "member_updated", request, ctx.user, f"{u.username}: {list(body.model_dump(exclude_none=True).keys())}")
    return await user_out(db, u)


@router.delete("/members/{uid}")
async def delete_member(uid: str, request: Request, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, uid)
    if not u or u.family_id != ctx.user.family_id or u.id == ctx.user.id:
        raise HTTPException(400)
    u.is_active = False
    await db.execute(delete(Session).where(Session.user_id == u.id))
    await db.commit()
    await audit(db, "member_disabled", request, ctx.user, u.username)
    return {"status": "ok"}


# ---- dispositivi fidati ----
@router.get("/devices")
async def devices(ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(TrustedDevice).where(TrustedDevice.family_id == ctx.user.family_id)
                             .order_by(TrustedDevice.created_at.desc()))).scalars().all()
    return [{"id": d.id[:10], "full_id": d.id, "name": d.name, "created_at": d.created_at, "last_seen_at": d.last_seen_at,
             "revoked": d.revoked} for d in rows]


@router.post("/devices/{did}/revoke")
async def revoke_device(did: str, request: Request, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    d = await db.get(TrustedDevice, did)
    if not d or d.family_id != ctx.user.family_id:
        raise HTTPException(404)
    d.revoked = True
    await db.execute(delete(Session).where(Session.device_id == d.id))
    await db.commit()
    await audit(db, "device_revoked", request, ctx.user, d.name)
    return {"status": "ok"}


# ---- supervisione ----
@router.get("/supervision/{uid}/conversations")
async def child_conversations(uid: str, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    child = await db.get(User, uid)
    if not child or child.family_id != ctx.user.family_id or child.role != Role.child:
        raise HTTPException(404)
    if not effective_policy(child).get("parent_can_view", True):
        raise HTTPException(403, "Supervisione disattivata per questo utente")
    convs = (await db.execute(select(Conversation).where(Conversation.owner_id == uid).order_by(Conversation.updated_at.desc()))).scalars().all()
    out = []
    for c in convs:
        flagged = (await db.execute(select(func.count()).select_from(Message).where(
            Message.conversation_id == c.id, Message.flagged == True))).scalar_one()  # noqa: E712
        out.append({"id": c.id, "title": c.title, "updated_at": c.updated_at, "provider": c.provider, "flagged": flagged})
    return out


@router.get("/supervision/flagged")
async def flagged_messages(days: int = 7, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(Message, Conversation, User).join(Conversation, Message.conversation_id == Conversation.id)
        .join(User, Conversation.owner_id == User.id)
        .where(Conversation.family_id == ctx.user.family_id, Message.flagged == True, Message.created_at >= since)  # noqa: E712
        .order_by(Message.created_at.desc()).limit(200))).all()
    return [{"message_id": m.id, "conversation_id": c.id, "conversation_title": c.title, "user": u.display_name,
             "role": m.role, "reason": m.flag_reason, "created_at": m.created_at,
             "text": "".join(b.get("text", "") for b in m.content if b.get("type") == "text")[:500]} for m, c, u in rows]


# ---- utilizzo ----
@router.get("/usage")
async def usage(days: int = 30, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(UsageLog.user_id, UsageLog.kind, UsageLog.provider, func.count(), func.sum(UsageLog.input_tokens),
               func.sum(UsageLog.output_tokens))
        .where(UsageLog.family_id == ctx.user.family_id, UsageLog.created_at >= since)
        .group_by(UsageLog.user_id, UsageLog.kind, UsageLog.provider))).all()
    users = {u.id: u.display_name for u in (await db.execute(select(User).where(User.family_id == ctx.user.family_id))).scalars()}
    return [{"user": users.get(uid, uid), "user_id": uid, "kind": kind, "provider": prov, "count": n,
             "input_tokens": int(i or 0), "output_tokens": int(o or 0)} for uid, kind, prov, n, i, o in rows]


@router.get("/audit")
async def audit_log(limit: int = 100, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AuditLog).where(AuditLog.family_id == ctx.user.family_id)
                             .order_by(AuditLog.created_at.desc()).limit(min(limit, 500)))).scalars().all()
    return [{"id": a.id, "event": a.event, "detail": a.detail, "user_id": a.user_id, "ip": a.ip, "created_at": a.created_at} for a in rows]


@router.get("/mcp")
async def mcp_status(ctx: AuthContext = Depends(require_admin)):
    return mcp_manager.status


# ---- provider AI e chiavi (gestite dal pannello, cifrate nel DB) ----
from pydantic import BaseModel  # noqa: E402

from ..providers.registry import available_providers  # noqa: E402
from ..services import settings_store  # noqa: E402

PROVIDER_CARDS = [
    {"id": "anthropic", "label": "Claude (Anthropic)", "key": "anthropic_api_key", "model_key": "anthropic_default_model",
     "hint": "console.anthropic.com → API Keys", "testable": True},
    {"id": "openai", "label": "ChatGPT (OpenAI)", "key": "openai_api_key", "model_key": "openai_default_model",
     "hint": "platform.openai.com/api-keys — usata anche per immagini, moderazione ed embedding", "testable": True},
    {"id": "gemini", "label": "Gemini (Google)", "key": "gemini_api_key", "model_key": "gemini_default_model",
     "hint": "aistudio.google.com/apikey — usata anche per video Veo ed embedding", "testable": True},
    {"id": "tavily", "label": "Tavily (ricerca web)", "key": "tavily_api_key", "model_key": None,
     "hint": "app.tavily.com", "testable": True},
    {"id": "brave", "label": "Brave Search (ricerca web)", "key": "brave_api_key", "model_key": None,
     "hint": "api-dashboard.search.brave.com", "testable": True},
]
OTHER_SETTINGS = ["web_search_provider", "image_provider", "image_model", "gemini_image_model", "video_model", "embedding_provider", "embedding_model"]


class SettingsUpdate(BaseModel):
    values: dict[str, str]  # chiave impostazione -> nuovo valore ("" = rimuovi override)


@router.get("/providers")
async def providers_status(ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    st = await settings_store.describe(db)
    active = {p["id"]: p for p in available_providers()}
    cards = []
    for c in PROVIDER_CARDS:
        cards.append({**c, "key_state": st[c["key"]], "model_state": st[c["model_key"]] if c["model_key"] else None,
                      "active": c["id"] in active, "models": active.get(c["id"], {}).get("models", [])})
    return {"providers": cards, "settings": {k: st[k] for k in OTHER_SETTINGS},
            "mock_active": "mock" in active}


@router.put("/providers")
async def providers_update(body: SettingsUpdate, request: Request, ctx: AuthContext = Depends(require_admin),
                           db: AsyncSession = Depends(get_db)):
    changed = []
    for k, v in body.values.items():
        if k not in settings_store.MANAGED_KEYS:
            raise HTTPException(400, f"Impostazione sconosciuta: {k}")
        await settings_store.set_value(db, k, v, ctx.user.id)
        changed.append(k)
    await settings_store.apply(db)
    await audit(db, "settings_changed", request, ctx.user, ", ".join(changed))
    return await providers_status(ctx, db)


@router.post("/providers/{pid}/test")
async def providers_test(pid: str, ctx: AuthContext = Depends(require_admin)):
    if pid not in {c["id"] for c in PROVIDER_CARDS}:
        raise HTTPException(404)
    return await settings_store.test_provider(pid)
