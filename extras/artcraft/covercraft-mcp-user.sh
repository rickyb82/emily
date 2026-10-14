#!/bin/sh
# Una sessione MCP per un utente: prima riga = nome dell'utente (lo manda il backend di Emily, che lo ha autenticato), poi il flusso MCP.
# Il token di servizio resta qui dentro: covercraft-cli mcp parla con il server locale a nome di quell'utente (storico e log con il suo nome).
IFS= read -r who || exit 1
who=$(printf '%s' "$who" | tr -d '\r' | tr -c 'A-Za-z0-9 ._@+-' '_' | cut -c1-80)
[ -n "$who" ] || { echo "utente vuoto" >&2; exit 1; }
exec covercraft-cli mcp --server "${COVERCRAFT_SERVER:-http://127.0.0.1:7979}" --token "$COVERCRAFT_TOKEN" --user "$who"
