#!/bin/sh
# MODE=mcp  (default): espone il server MCP stdio dell'app ($APP-cli mcp ...) sulla porta TCP $MCP_PORT, una sessione per connessione.
# MODE=http: per le app senza MCP (IdeaCraft): piccolo servizio HTTP che esegue la CLI (cli-server.py) su $HTTP_PORT.
set -eu
if [ "${MODE:-mcp}" = http ]; then
  exec python3 /usr/local/bin/cli-server.py
fi
echo ">> ${APP}-cli mcp ${MCP_ARGS} in ascolto su :${MCP_PORT}"
exec socat -d "TCP-LISTEN:${MCP_PORT},fork,reuseaddr" "EXEC:${APP}-cli mcp ${MCP_ARGS}"
