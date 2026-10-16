#!/bin/sh
# Avvia il server QuoteCraft (API + web app su :7878, dati in /qc) e il ponte MCP per utente (socat su :$MCP_PORT).
set -eu
if [ "$(id -u)" = 0 ]; then
  chown -R quotecraft:quotecraft /qc 2>/dev/null || true
  exec setpriv --reuid=quotecraft --regid=quotecraft --init-groups "$0" "$@"
fi
[ -n "${QUOTECRAFT_TOKEN:-}" ] || { echo "!! QUOTECRAFT_TOKEN vuoto: ./familai.sh quotecraft up lo genera nel .env"; exit 1; }
echo ">> quotecraft-cli mcp per utente in ascolto su :${MCP_PORT:-7899}"
socat -d "TCP-LISTEN:${MCP_PORT:-7899},fork,reuseaddr" "EXEC:/usr/local/bin/quotecraft-mcp-user" &
echo ">> quotecraft-cli serve su :7878 (web app + API, dati in /qc)"
exec quotecraft-cli serve --bind 0.0.0.0:7878 --static /app/web --home /qc --token "$QUOTECRAFT_TOKEN" --lang "${QUOTECRAFT_LANG:-it}"
