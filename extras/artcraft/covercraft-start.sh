#!/bin/sh
# Avvia il server CoverCraft (API + web app su :7979, configurazione del database in /data) e il ponte MCP per utente (socat su :$MCP_PORT).
set -eu
if [ "$(id -u)" = 0 ]; then
  chown -R covercraft:covercraft /data 2>/dev/null || true
  exec setpriv --reuid=covercraft --regid=covercraft --init-groups "$0" "$@"
fi
[ -n "${COVERCRAFT_TOKEN:-}" ] || { echo "!! COVERCRAFT_TOKEN vuoto: ./familai.sh covercraft up lo genera nel .env"; exit 1; }
echo ">> covercraft-cli mcp per utente in ascolto su :${MCP_PORT:-7999}"
socat -d "TCP-LISTEN:${MCP_PORT:-7999},fork,reuseaddr" "EXEC:/usr/local/bin/covercraft-mcp-user" &
echo ">> covercraft-cli serve su :7979 (web app + API, configurazione in /data)"
exec covercraft-cli serve --bind 0.0.0.0:7979 --static /app/web --home /data --token "$COVERCRAFT_TOKEN" --lang "${COVERCRAFT_LANG:-it}"
