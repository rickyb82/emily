"""Client MCP con connessioni gestibili a caldo dal pannello admin.

Ogni server gira in un task dedicato che apre la sessione (stdio o Streamable HTTP), registra i tool come
`mcp__<server>__<tool>` e resta in attesa finche' non viene chiesta la disconnessione: cosi' l'apertura e la
chiusura dei context manager avvengono nello stesso task (requisito di anyio/mcp).

Configurazione: tabella `mcp_servers` (pannello Famiglia → MCP). Al primo avvio, se la tabella e' vuota,
vengono importati i server di `mcp_servers.json`.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import json
import logging
from dataclasses import dataclass, field

from ..config import get_settings
from ..models import McpServer, Role
from ..providers.base import ToolSpec
from .registry import Tool, ToolContext, ToolResult, register_tool, unregister_prefix

log = logging.getLogger(__name__)
settings = get_settings()

ROLE_RANK = {Role.child: 0, Role.adult: 1, Role.admin: 2}
MIN_ROLE_RANK = {"child": 0, "adult": 1, "admin": 2}
CONNECT_TIMEOUT = 45


@dataclass
class ServerConfig:
    name: str
    type: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict = field(default_factory=dict)
    env: dict = field(default_factory=dict)
    min_role: str = "adult"
    enabled: bool = True


@dataclass
class Connection:
    cfg: ServerConfig
    task: asyncio.Task | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    session: object | None = None
    tools: list[dict] = field(default_factory=list)
    error: str = ""
    connected: bool = False


def _attr(obj, *names, default=None):
    """Campo di un oggetto della libreria mcp: camelCase (mcp 1.x: inputSchema, isError, mimeType) o snake_case (versioni
    successive: input_schema, is_error, mime_type). Cosi' un aggiornamento della libreria non spegne i server MCP."""
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return default


_READ_ONLY_PREFIXES = ("list_", "get_", "inspect", "render", "read_", "describe", "search", "find", "validate", "export",
                       "select_", "help", "info", "preview", "snapshot")


def _mutating(tool: str) -> bool:
    """I tool che cambiano il documento (execute, batch, insert_*, add_*, update_*, delete_*…) fanno scattare il salvataggio
    automatico; quelli di sola lettura o selezione no."""
    return not tool.startswith(_READ_ONLY_PREFIXES) and not tool.startswith(("open_", "new_", "save", "close"))


def _describe(e: BaseException) -> str:
    """Errore leggibile: un ExceptionGroup (anyio/mcp) viene aperto fino alle eccezioni vere."""
    group = getattr(e, "exceptions", None)
    if group:
        return "; ".join(_describe(x) for x in group[:3])
    return f"{type(e).__name__}: {str(e)[:300]}"


class MCPManager:
    def __init__(self):
        self._open: dict[tuple[str, str], str] = {}   # (server, conversazione) -> file aperto con i tool MCP
        self.conns: dict[str, Connection] = {}

    # ---------------- ciclo di vita ----------------
    async def start(self) -> None:
        """All'avvio: importa il JSON se il DB e' vuoto, poi connette i server abilitati."""
        from sqlalchemy import select

        from ..db import SessionLocal
        from ..services import settings_store

        async with SessionLocal() as db:
            rows = (await db.execute(select(McpServer))).scalars().all()
            if not rows and settings.mcp_config_path.exists():
                try:
                    cfg = json.loads(settings.mcp_config_path.read_text())
                    for name, sc in cfg.get("servers", {}).items():
                        db.add(McpServer(name=name, type=sc.get("type", "stdio"), command=sc.get("command", ""),
                                         args=sc.get("args", []), url=sc.get("url", ""),
                                         headers_enc=settings_store.encrypt(json.dumps(sc.get("headers") or {})),
                                         env_enc=settings_store.encrypt(json.dumps(sc.get("env") or {})),
                                         min_role=sc.get("min_role", "adult"), enabled=bool(sc.get("enabled", False)),
                                         description="importato da mcp_servers.json"))
                    await db.commit()
                    rows = (await db.execute(select(McpServer))).scalars().all()
                    log.info("MCP: importati %d server da mcp_servers.json", len(rows))
                except Exception as e:
                    log.error("MCP: import di mcp_servers.json fallito: %s", e)
            for row in rows:
                if row.enabled:
                    asyncio.create_task(self.connect(self.config_from_row(row)))
            # app ArtCraft (extras/artcraft): MCP stdio esposto via socat sulla rete Docker
            from .artcraft import APPS, HTTP_APPS, host_for, register_tools as _ac_reg
            for app in APPS:
                if app in HTTP_APPS:
                    if host_for(app):
                        _ac_reg(app)   # CLI via HTTP (IdeaCraft): nessuna sessione MCP, il tool c'e' se l'host e' configurato
                    continue
                if host_for(app) and not any(r.name == app for r in rows):
                    asyncio.create_task(self.connect(ServerConfig(
                        name=app, type="stdio", command="socat", args=["-", f"TCP:{host_for(app)}"],
                        min_role="adult", enabled=True)))

    async def stop(self) -> None:
        for name in list(self.conns):
            await self.disconnect(name)

    @staticmethod
    def config_from_row(row: McpServer) -> ServerConfig:
        from ..services import settings_store

        def dec(v: str) -> dict:
            try:
                return json.loads(settings_store.decrypt(v)) if v else {}
            except Exception:
                return {}

        return ServerConfig(name=row.name, type=row.type, command=row.command, args=list(row.args or []), url=row.url,
                            headers=dec(row.headers_enc), env=dec(row.env_enc), min_role=row.min_role, enabled=row.enabled)

    # ---------------- connessione / disconnessione a caldo ----------------
    async def connect(self, cfg: ServerConfig) -> Connection:
        if cfg.name in self.conns:
            await self.disconnect(cfg.name)
        conn = Connection(cfg=cfg)
        self.conns[cfg.name] = conn
        conn.task = asyncio.create_task(self._run(conn), name=f"mcp-{cfg.name}")
        try:
            await asyncio.wait_for(conn.ready.wait(), timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            conn.error = f"timeout di connessione ({CONNECT_TIMEOUT}s)"
            await self.disconnect(cfg.name, keep_entry=True)
        return conn

    async def disconnect(self, name: str, keep_entry: bool = False) -> None:
        conn = self.conns.get(name)
        if not conn:
            return
        conn.stop.set()
        if conn.task:
            try:
                await asyncio.wait_for(conn.task, timeout=15)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                conn.task.cancel()
            except Exception as e:
                log.debug("MCP %s: chiusura con errore %s", name, e)
        unregister_prefix(f"mcp__{name}__")
        conn.connected = False
        conn.session = None
        if not keep_entry:
            self.conns.pop(name, None)

    async def _run(self, conn: Connection) -> None:
        """Task dedicato: apre la sessione, registra i tool, attende lo stop, chiude tutto nello stesso task."""
        cfg = conn.cfg
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            if cfg.type == "http":
                from mcp.client.streamable_http import streamablehttp_client

                transport = streamablehttp_client(cfg.url, headers=cfg.headers or None)
            else:
                import os

                env = {**os.environ, **(cfg.env or {})} if cfg.env else None
                transport = stdio_client(StdioServerParameters(command=cfg.command, args=cfg.args, env=env))

            async with transport as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    unregister_prefix(f"mcp__{cfg.name}__")
                    conn.tools = []
                    for t in listed.tools:
                        full = f"mcp__{cfg.name}__{t.name}"
                        conn.tools.append({"name": t.name, "description": t.description or ""})
                        register_tool(Tool(
                            spec=ToolSpec(full, f"[MCP {cfg.name}] {t.description or t.name}",
                                          _attr(t, "inputSchema", "input_schema") or {"type": "object", "properties": {}}),
                            fn=self._make_caller(cfg.name, t.name),
                        ))
                    conn.session = session
                    conn.connected = True
                    conn.error = ""
                    from .artcraft import APPS as _ARTCRAFT, register_tools as _ac_register
                    if cfg.name in _ARTCRAFT:
                        _ac_register(cfg.name)
                    conn.ready.set()
                    log.info("MCP %s: connesso, %d tool", cfg.name, len(conn.tools))
                    await conn.stop.wait()
        except Exception as e:
            conn.error = _describe(e)
            log.error("MCP %s: %s", cfg.name, conn.error, exc_info=True)
        finally:
            conn.connected = False
            conn.session = None
            conn.ready.set()
            unregister_prefix(f"mcp__{cfg.name}__")
            from .artcraft import APPS as _ARTCRAFT, unregister_tools as _ac_unregister
            if cfg.name in _ARTCRAFT:
                _ac_unregister(cfg.name)

    def _make_caller(self, server: str, tool: str):
        async def call(args: dict, ctx: ToolContext) -> ToolResult:
            conn = self.conns.get(server)
            if not conn or not conn.connected or not conn.session:
                return ToolResult(f"Server MCP {server} non connesso", is_error=True)
            if ROLE_RANK.get(ctx.user.role, 0) < MIN_ROLE_RANK.get(conn.cfg.min_role, 1):
                return ToolResult("Non hai il permesso di usare questo strumento", is_error=True)
            try:
                res = await asyncio.wait_for(conn.session.call_tool(tool, arguments=args), timeout=180)
            except Exception as e:
                return ToolResult(f"Errore MCP: {type(e).__name__}: {e}", is_error=True)
            parts, artifacts = await self._collect(res, ctx)
            from .artcraft import APPS as _ARTCRAFT, harvest_paths, register_saved_file, sidecar_files
            if server in _ARTCRAFT and not _attr(res, "isError", "is_error", default=False):
                app = _ARTCRAFT[server]
                key = (server, ctx.conversation_id or "")
                paths: list[str] = []
                cmd = str(args.get("command") or args.get("id") or "")
                if tool in app["save_tools"]:
                    paths = [str(args.get("path") or self._open.get(key) or "")]
                elif tool in ("execute", "run_command", "run") and cmd.startswith("file.save"):
                    # Salva/Salva con nome passati come comando generico: il percorso sta nei parametri
                    prm = args.get("params") or args.get("args") or {}
                    paths = [str((prm.get("path") if isinstance(prm, dict) else "") or self._open.get(key) or "")]
                elif not app["save_tools"]:   # PdfCraft: i percorsi scritti stanno nel risultato
                    paths = harvest_paths("\n".join(parts))
                if tool.startswith("open_") and args.get("path"):
                    self._open[key] = str(args["path"])
                elif tool.startswith("new_"):
                    self._open.pop(key, None)
                for pth in paths:
                    if pth:
                        self._open[key] = pth
                    for extra in [pth] + sidecar_files(pth):
                        art = await register_saved_file(ctx, extra)
                        if art:
                            artifacts.append(art)
                            parts.append(f"File {art.get('filename', '')} salvato e mostrato all'utente come allegato scaricabile (id {art['file_id']}).")
                # Salvataggio automatico: ogni modifica fatta con i tool MCP finisce subito sul file aperto, cosi' l'utente
                # trova il documento aggiornato (il modello spesso mostra l'anteprima e dimentica save_*).
                if not paths and app["save_tools"] and self._open.get(key) and _mutating(tool):
                    try:
                        sv = await asyncio.wait_for(conn.session.call_tool(app["save_tools"][0], arguments={"path": self._open[key]}), timeout=60)
                        if not _attr(sv, "isError", "is_error", default=False):
                            art = await register_saved_file(ctx, self._open[key], only_new=True)
                            if art:
                                artifacts.append(art)
                            parts.append(f"(file salvato automaticamente: {Path(self._open[key]).name})")
                    except Exception as e:  # il salvataggio automatico non deve far fallire la modifica
                        log.warning("MCP %s: salvataggio automatico di %s fallito: %s", server, self._open.get(key), e)
            return ToolResult("\n".join(parts) or "(vuoto)", is_error=bool(_attr(res, "isError", "is_error", default=False)), artifacts=artifacts or None)
        return call

    async def _collect(self, res, ctx: ToolContext) -> tuple[list[str], list[dict]]:
        """Testo per il modello + allegati per la chat: le immagini restituite da un tool MCP (es. render_page di
        WordCraft) vengono salvate come file generati e mostrate all'utente."""
        parts: list[str] = []
        artifacts: list[dict] = []
        for c in res.content:
            ctype = getattr(c, "type", "")
            if ctype == "text":
                parts.append(c.text)
            elif ctype == "image" and getattr(c, "data", None):
                try:
                    import base64

                    from .media import _save_generated
                    mime = _attr(c, "mimeType", "mime_type", default="") or "image/png"
                    ext = "jpg" if "jpeg" in mime else mime.split("/")[-1] or "png"
                    asset = await _save_generated(ctx, base64.b64decode(c.data), ext, mime, "anteprima")
                    artifacts.append({"type": "image", "file_id": asset.id, "url": f"/files/{asset.id}", "mime": mime})
                    parts.append(f"[immagine mostrata all'utente (id {asset.id})]")
                except Exception as e:
                    parts.append(f"[immagine non salvata: {e}]")
            else:
                parts.append(f"[{ctype or 'contenuto'} non testuale]")
        return parts, artifacts

    async def call(self, server: str, tool: str, args: dict, timeout: int = 180):
        """Chiamata diretta a un tool MCP dal codice (usata dai tool nativi che orchestrano WordCraft)."""
        conn = self.conns.get(server)
        if not conn or not conn.connected or not conn.session:
            raise RuntimeError(f"server MCP {server} non connesso")
        res = await asyncio.wait_for(conn.session.call_tool(tool, arguments=args), timeout=timeout)
        text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
        if _attr(res, "isError", "is_error", default=False):
            raise RuntimeError(text[:500] or f"{tool} fallito")
        return text

    async def call_raw(self, server: str, tool: str, args: dict, timeout: int = 180):
        """Come call() ma restituisce il risultato MCP grezzo (per contenuti non testuali, es. immagini)."""
        conn = self.conns.get(server)
        if not conn or not conn.connected or not conn.session:
            raise RuntimeError(f"server MCP {server} non connesso")
        res = await asyncio.wait_for(conn.session.call_tool(tool, arguments=args), timeout=timeout)
        if _attr(res, "isError", "is_error", default=False):
            raise RuntimeError("\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")[:500] or f"{tool} fallito")
        return res

    def is_connected(self, server: str) -> bool:
        c = self.conns.get(server)
        return bool(c and c.connected)

    # ---------------- stato / permessi ----------------
    def allowed_for(self, role: Role, tool_name: str) -> bool:
        if not tool_name.startswith("mcp__"):
            return True
        server = tool_name.split("__")[1]
        conn = self.conns.get(server)
        if not conn:
            return False
        return ROLE_RANK.get(role, 0) >= MIN_ROLE_RANK.get(conn.cfg.min_role, 1)

    @property
    def status(self) -> dict[str, dict]:
        return {name: {"enabled": c.cfg.enabled, "connected": c.connected, "error": c.error,
                       "tools": [t["name"] for t in c.tools], "min_role": c.cfg.min_role}
                for name, c in self.conns.items()}


mcp_manager = MCPManager()
