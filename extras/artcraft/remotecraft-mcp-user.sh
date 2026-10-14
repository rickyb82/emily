#!/bin/sh
# Una sessione MCP per un tecnico: prima riga = token utente (coniato dal server con il token di servizio), poi il flusso MCP.
IFS= read -r tok || exit 1
case "$tok" in ""|*[!0-9a-fA-F]*) echo "token non valido" >&2; exit 1;; esac
exec remotecraft-cli mcp --server "${REMOTECRAFT_SERVER:-http://remotecraft:7979}" --token "$tok"
