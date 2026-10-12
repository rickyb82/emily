#!/bin/sh
# Espone il server MCP stdio dell'app ($APP-cli mcp ...) sulla porta TCP $MCP_PORT: una sessione per connessione.
set -eu
echo ">> ${APP}-cli mcp ${MCP_ARGS} in ascolto su :${MCP_PORT}"
exec socat -d "TCP-LISTEN:${MCP_PORT},fork,reuseaddr" "EXEC:${APP}-cli mcp ${MCP_ARGS}"
