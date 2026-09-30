"""Client MCP: collega i server definiti in mcp_servers.json e registra i loro tool come `mcp__<server>__<tool>`."""
from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack

from ..config import get_settings
from ..models import Role
from ..providers.base import ToolSpec
from .registry import Tool, ToolContext, ToolResult, register_tool, unregister_prefix

log = logging.getLogger(__name__)
settings = get_settings()

ROLE_RANK = {Role.child: 0, Role.adult: 1, Role.admin: 2}
MIN_ROLE_RANK = {"child": 0, "adult": 1, "admin": 2}


class MCPManager:
    def __init__(self):
        self.stack = AsyncExitStack()
        self.sessions: dict[str, object] = {}
        self.status: dict[str, dict] = {}
        self.min_role: dict[str, int] = {}

    async def start(self) -> None:
        path = settings.mcp_config_path
        if not path.exists():
            log.info("Nessun mcp_servers.json, MCP disabilitato")
            return
        cfg = json.loads(path.read_text())
        for name, sc in cfg.get("servers", {}).items():
            if not sc.get("enabled", False):
                self.status[name] = {"enabled": False, "connected": False, "tools": []}
                continue
            try:
                await self._connect(name, sc)
            except Exception as e:
                log.error("MCP %s: connessione fallita: %s", name, e)
                self.status[name] = {"enabled": True, "connected": False, "error": str(e), "tools": []}

    async def _connect(self, name: str, sc: dict) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if sc.get("type") == "http":
            from mcp.client.streamable_http import streamablehttp_client

            read, write, _ = await self.stack.enter_async_context(
                streamablehttp_client(sc["url"], headers=sc.get("headers") or {}))
        else:
            params = StdioServerParameters(command=sc["command"], args=sc.get("args", []), env=sc.get("env"))
            read, write = await self.stack.enter_async_context(stdio_client(params))
        session = await self.stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[name] = session
        self.min_role[name] = MIN_ROLE_RANK.get(sc.get("min_role", "adult"), 1)
        tools = await session.list_tools()
        names = []
        unregister_prefix(f"mcp__{name}__")
        for t in tools.tools:
            full = f"mcp__{name}__{t.name}"
            names.append(t.name)
            register_tool(Tool(
                spec=ToolSpec(full, f"[MCP {name}] {t.description or t.name}",
                              t.inputSchema or {"type": "object", "properties": {}}),
                fn=self._make_caller(name, t.name),
            ))
        self.status[name] = {"enabled": True, "connected": True, "tools": names, "min_role": sc.get("min_role", "adult")}
        log.info("MCP %s: %d tool", name, len(names))

    def _make_caller(self, server: str, tool: str):
        async def call(args: dict, ctx: ToolContext) -> ToolResult:
            if ROLE_RANK.get(ctx.user.role, 0) < self.min_role.get(server, 1):
                return ToolResult("Non hai il permesso di usare questo strumento", is_error=True)
            session = self.sessions.get(server)
            if not session:
                return ToolResult(f"Server MCP {server} non connesso", is_error=True)
            try:
                res = await session.call_tool(tool, arguments=args)
            except Exception as e:
                return ToolResult(f"Errore MCP: {e}", is_error=True)
            parts = []
            for c in res.content:
                if getattr(c, "type", "") == "text":
                    parts.append(c.text)
                else:
                    parts.append(f"[{getattr(c, 'type', 'contenuto')} non testuale]")
            return ToolResult("\n".join(parts) or "(vuoto)", is_error=bool(res.isError))
        return call

    def allowed_for(self, role: Role, tool_name: str) -> bool:
        if not tool_name.startswith("mcp__"):
            return True
        server = tool_name.split("__")[1]
        return ROLE_RANK.get(role, 0) >= self.min_role.get(server, 1)

    async def stop(self) -> None:
        try:
            await self.stack.aclose()
        except Exception as e:
            log.warning("Chiusura MCP: %s", e)


mcp_manager = MCPManager()
