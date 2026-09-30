"""Modelli dati di FamilAI."""
from __future__ import annotations

import enum
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Role(str, enum.Enum):
    admin = "admin"    # genitore amministratore
    adult = "adult"    # adulto
    child = "child"    # bambino/a


class AgeGroup(str, enum.Enum):
    young = "young"    # ~5-8 anni
    kid = "kid"        # ~9-12 anni
    teen = "teen"      # 13+
    adult = "adult"


class Family(Base):
    __tablename__ = "families"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # impostazioni globali della famiglia (provider abilitati, modelli, ecc.)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    members: Mapped[list[User]] = relationship(back_populates="family")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    family_id: Mapped[str] = mapped_column(ForeignKey("families.id"))
    email: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    username: Mapped[str] = mapped_column(String(60))
    display_name: Mapped[str] = mapped_column(String(120))
    avatar: Mapped[str] = mapped_column(String(16), default="🙂")
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.child)
    age_group: Mapped[AgeGroup] = mapped_column(Enum(AgeGroup), default=AgeGroup.kid)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)  # adulti
    pin_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)       # bambini
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # policy specifica dell'utente (sovrascrive i default del gruppo di età)
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    recovery_codes: Mapped[list] = mapped_column(JSON, default=list)  # hash dei codici
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    family: Mapped[Family] = relationship(back_populates="members")
    credentials: Mapped[list[WebAuthnCredential]] = relationship(back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("family_id", "username"),)

    @property
    def is_child(self) -> bool:
        return self.role == Role.child

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin


class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[list] = mapped_column(JSON, default=list)
    name: Mapped[str] = mapped_column(String(120), default="Passkey")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="credentials")


class Session(Base):
    """Sessione di login (cookie opaco HttpOnly)."""
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: secrets.token_urlsafe(48))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TrustedDevice(Base):
    """Dispositivo approvato da un genitore: solo da qui i bambini possono accedere con il PIN."""
    __tablename__ = "trusted_devices"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: secrets.token_urlsafe(32))
    family_id: Mapped[str] = mapped_column(ForeignKey("families.id"))
    name: Mapped[str] = mapped_column(String(120))
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    family_id: Mapped[str] = mapped_column(ForeignKey("families.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")  # istruzioni di sistema del progetto
    icon: Mapped[str] = mapped_column(String(16), default="📁")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    family_id: Mapped[str] = mapped_column(ForeignKey("families.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="Nuova chat")
    provider: Mapped[str] = mapped_column(String(40), default="anthropic")
    model: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # None = assistente
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | tool
    # contenuto "ricco": lista di blocchi {type: text|image|file|tool_use|tool_result, ...}
    content: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)   # segnalato dal filtro contenuti
    flag_reason: Mapped[str] = mapped_column(String(300), default="")
    usage: Mapped[dict] = mapped_column(JSON, default=dict)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class FileAsset(Base):
    """File caricato o generato (immagine, video, documento)."""
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    family_id: Mapped[str] = mapped_column(ForeignKey("families.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20), default="upload")  # upload | generated
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # RAG: none (non indicizzabile) | pending | indexed | failed
    index_status: Mapped[str] = mapped_column(String(12), default="none")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)


class Chunk(Base):
    """Frammento di testo di un file, con embedding opzionale, per la ricerca semantica (RAG)."""
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[str] = mapped_column(ForeignKey("families.id"))
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    idx: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(80), default="")


class Share(Base):
    """Condivisione di una risorsa con un membro (target_user_id) o con tutta la famiglia (None)."""
    __tablename__ = "shares"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    family_id: Mapped[str] = mapped_column(ForeignKey("families.id"))
    resource_type: Mapped[str] = mapped_column(String(20))  # conversation | project | file
    resource_id: Mapped[str] = mapped_column(String(32))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    target_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    permission: Mapped[str] = mapped_column(String(10), default="read")  # read | write
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (UniqueConstraint("resource_type", "resource_id", "target_user_id"),)


class UsageLog(Base):
    __tablename__ = "usage_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[str] = mapped_column(ForeignKey("families.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    kind: Mapped[str] = mapped_column(String(30))  # message | image | video | web_search | tool
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(String(300), default="")


class AuditLog(Base):
    """Eventi di sicurezza (login, passkey, cambi policy, dispositivi)."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    event: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(String(500), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class AppSetting(Base):
    """Impostazioni modificabili dal pannello admin (chiavi API cifrate, modelli di default).
    Sovrascrivono i valori del file .env."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    secret: Mapped[bool] = mapped_column(Boolean, default=False)  # True = valore cifrato con SECRET_KEY
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    updated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Artifact(Base):
    """Contenuto autonomo creato dall'assistente (pagina HTML, SVG, codice, markdown) con anteprima e versioni."""
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    family_id: Mapped[str] = mapped_column(ForeignKey("families.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))       # html | svg | markdown | code | mermaid
    language: Mapped[str] = mapped_column(String(40), default="")  # per kind=code: python, javascript, java...
    content: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    history: Mapped[list] = mapped_column(JSON, default=list)  # versioni precedenti [{version, content, created_at}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class McpServer(Base):
    """Server MCP configurato dal pannello (sostituisce mcp_servers.json, che resta come import iniziale)."""
    __tablename__ = "mcp_servers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    type: Mapped[str] = mapped_column(String(10), default="stdio")      # stdio | http
    command: Mapped[str] = mapped_column(String(300), default="")
    args: Mapped[list] = mapped_column(JSON, default=list)
    url: Mapped[str] = mapped_column(String(500), default="")
    headers_enc: Mapped[str] = mapped_column(Text, default="")           # JSON cifrato (token/API key)
    env_enc: Mapped[str] = mapped_column(Text, default="")               # JSON cifrato
    min_role: Mapped[str] = mapped_column(String(10), default="adult")   # child | adult | admin
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
