#!/bin/sh
# Una sessione MCP per un utente: prima riga = `nome<TAB>ruolo<TAB>identita-mail` (la manda il backend di Emily, che ha autenticato
# l'utente), poi il flusso MCP. Il token di servizio resta qui dentro.
IFS= read -r line || exit 1
tab=$(printf '\t')
who=${line%%"$tab"*}; rest=${line#*"$tab"}; [ "$rest" = "$line" ] && rest=""
role=${rest%%"$tab"*}; mailuser=${rest#*"$tab"}; [ "$mailuser" = "$rest" ] && mailuser=""
clean() { printf '%s' "$1" | tr -d '\r' | tr -c 'A-Za-z0-9 ._@+-' '_' | cut -c1-80; }
who=$(clean "$who"); role=$(clean "$role"); mailuser=$(clean "$mailuser")
[ -n "$who" ] || { echo "utente vuoto" >&2; exit 1; }
set -- mcp --server "${QUOTECRAFT_SERVER:-http://127.0.0.1:7878}" --token "$QUOTECRAFT_TOKEN" --user "$who"
# --role / --mail-user esistono solo nelle versioni di quotecraft-cli che li supportano
if quotecraft-cli --help 2>&1 | grep -q -- '--mail-user'; then
  [ "$role" = admin ] && set -- "$@" --role admin
  [ -n "$mailuser" ] && set -- "$@" --mail-user "$mailuser"
fi
exec quotecraft-cli "$@"
