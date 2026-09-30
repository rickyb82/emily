#!/usr/bin/env bash
# Gestione FamilAI: stesso script sul Mac (anteprima) e sulla macchina Ubuntu (produzione).
#   ./familai.sh dev        avvia in locale su http://localhost:8080 (senza certificati)
#   ./familai.sh prod       avvia in produzione (HTTPS con il dominio del .env)
#   ./familai.sh update     aggiorna: git pull + rebuild + riavvio (solo i servizi cambiati) + backup automatico
#   ./familai.sh stop|logs|status|backup|restore <file>|shell
set -euo pipefail
cd "$(dirname "$0")"

MODE_FILE=".familai-mode"
compose() {
  local mode
  mode=$(cat "$MODE_FILE" 2>/dev/null || echo prod)
  if [ "$mode" = "dev" ]; then
    docker compose -f docker-compose.yml -f docker-compose.dev.yml "$@"
  else
    docker compose -f docker-compose.yml "$@"
  fi
}

need_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    # SECRET_KEY casuale al primo avvio
    local key
    key=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    sed -i.bak "s/^SECRET_KEY=.*/SECRET_KEY=$key/" .env && rm -f .env.bak
    echo ">> Creato .env con SECRET_KEY casuale. Controlla ADMIN_EMAIL/ADMIN_PASSWORD (e PUBLIC_HOST per la produzione)."
  fi
  mkdir -p data backups
}

backup() {
  mkdir -p backups
  local out="backups/familai-$(date +%Y%m%d-%H%M%S).tar.gz"
  tar czf "$out" data .env 2>/dev/null || tar czf "$out" data
  ls -t backups/familai-*.tar.gz | tail -n +15 | xargs -r rm -f   # tieni gli ultimi 14
  echo ">> Backup: $out"
}

case "${1:-}" in
  dev)
    need_env; echo dev > "$MODE_FILE"
    compose up -d --build
    echo ">> FamilAI in anteprima su http://localhost:8080  (log: ./familai.sh logs)";;
  prod)
    need_env; echo prod > "$MODE_FILE"
    grep -q "PUBLIC_HOST=familai.example.com" .env && { echo "!! Imposta PUBLIC_HOST, ACME_EMAIL e WEBAUTHN_* nel .env prima della produzione"; exit 1; }
    compose up -d --build
    echo ">> FamilAI in produzione su https://$(grep ^PUBLIC_HOST= .env | cut -d= -f2)";;
  update)
    need_env
    if [ -d .git ]; then
      echo ">> git pull"; git pull --ff-only
    else
      echo ">> (nessun repository git: aggiorno solo i container con i file presenti)"
    fi
    backup
    compose build --pull
    compose up -d --remove-orphans      # riavvia solo i servizi la cui immagine e' cambiata
    docker image prune -f >/dev/null
    echo ">> Aggiornato alla versione $(cat VERSION 2>/dev/null || echo ?). Stato:"; compose ps;;
  stop)    compose down;;
  logs)    compose logs -f --tail=200 "${2:-}";;
  status)  compose ps; echo; echo "Versione: $(cat VERSION 2>/dev/null)"; echo "Modalita': $(cat $MODE_FILE 2>/dev/null || echo prod)";;
  backup)  backup;;
  restore)
    [ -f "${2:-}" ] || { echo "uso: ./familai.sh restore backups/<file>.tar.gz"; exit 1; }
    compose down; tar xzf "$2"; compose up -d; echo ">> Ripristinato $2";;
  shell)   compose exec backend bash;;
  *) sed -n '2,7p' "$0";;
esac
