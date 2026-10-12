#!/usr/bin/env bash
# Gestione FamilAI: stesso script sul Mac (anteprima) e sulla macchina Ubuntu (produzione).
#   ./familai.sh dev        avvia in locale su http://localhost:8080 (senza certificati)
#   ./familai.sh prod       avvia in produzione (HTTPS con il dominio del .env)
#   ./familai.sh update     aggiorna: git pull + rebuild + riavvio (solo i servizi cambiati) + backup automatico
#   ./familai.sh stop|logs|status|backup|restore <file>|shell
#   ./familai.sh reset-passkey EMAIL     emergenza: rimuove le passkey di un utente (rientri con la password)
#   ./familai.sh set-password EMAIL PASS emergenza: nuova password per un utente
#   ./familai.sh users                   elenca gli utenti
#   ./familai.sh deploy [user@host]      dal Mac: git push + "update" sulla macchina Ubuntu via SSH (host anche in .deploy)
#   ./familai.sh portainer up|down|logs  pannello web Docker (Portainer) su https://<ip>:9443 per gestire altri container
#   ./familai.sh wordcraft up|down|logs|upgrade  word processor WordCraft: documenti Word/PDF dalla chat (MCP) + editor nel browser
#   ./familai.sh gridcraft up|down|logs|upgrade  foglio di calcolo GridCraft: file Excel dalla chat (MCP) + editor nel browser
#   ./familai.sh pdfcraft up|down|logs|upgrade   PdfCraft: unire/dividere/modificare PDF dalla chat (MCP) + editor PDF nel browser
#   ./familai.sh deckcraft up|down|logs|upgrade  DeckCraft: presentazioni PowerPoint dalla chat (MCP) + editor nel browser
#   ./familai.sh ideacraft up|down|logs|upgrade  IdeaCraft: mappe mentali dalla chat (immagine + .mm/.opml) + editor nel browser
set -euo pipefail
cd "$(dirname "$0")"

MODE_FILE=".familai-mode"

# --- individua Docker e Compose e spiega chiaramente cosa manca ---
if ! command -v docker >/dev/null 2>&1; then
  echo "!! 'docker' non trovato. Installa Docker Desktop (Mac) o Docker Engine (Ubuntu) e riapri il terminale."; exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "!! Docker non e' in esecuzione. Su Mac apri Docker Desktop dalle Applicazioni e attendi che la balena nella barra dei menu sia ferma; su Ubuntu: sudo systemctl start docker (e aggiungi il tuo utente al gruppo docker)."; exit 1
fi
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "!! Il plugin Docker Compose manca. Su Mac di solito significa che nel PATH c'e' un altro 'docker' (es. Homebrew) prima di quello di Docker Desktop:"
  echo "   which -a docker     -> dovrebbe comparire /usr/local/bin/docker o /Applications/Docker.app/Contents/Resources/bin/docker"
  echo "   Rimedio rapido: brew uninstall docker  (oppure usa il percorso completo di Docker Desktop)."
  echo "   Su Ubuntu: sudo apt install docker-compose-v2"; exit 1
fi

compose() {
  local mode
  mode=$(cat "$MODE_FILE" 2>/dev/null || echo prod)
  if [ "$mode" = "dev" ]; then
    $DC -f docker-compose.yml -f docker-compose.dev.yml "$@"
  else
    $DC -f docker-compose.yml "$@"
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
    if [ -d .git ] && git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
      echo ">> git pull"; git pull --ff-only
    elif [ -d .git ]; then
      echo ">> (nessun remote configurato: uso i file gia' presenti nella cartella)"
    else
      echo ">> (nessun repository git: aggiorno solo i container con i file presenti)"
    fi
    backup
    compose build --pull
    compose up -d --remove-orphans      # riavvia solo i servizi la cui immagine e' cambiata
    compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true   # il Caddyfile e' montato: ricaricalo
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
  reset-passkey) compose exec backend python -m app.cli reset-passkey "${2:?email}";;
  set-password)  compose exec backend python -m app.cli set-password "${2:?email}" "${3:?password}";;
  unlock)        compose exec backend python -m app.cli unlock "${2:?email}";;
  users)         compose exec backend python -m app.cli list-users;;
  portainer)
    case "${2:-up}" in
      up)   $DC -f extras/portainer.yml up -d; echo ">> Portainer: https://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):9443  (crea l'amministratore entro 5 minuti dal primo avvio)";;
      down) $DC -f extras/portainer.yml down;;
      logs) $DC -f extras/portainer.yml logs -f --tail=100;;
      update) $DC -f extras/portainer.yml pull && $DC -f extras/portainer.yml up -d;;
      *) echo "uso: ./familai.sh portainer up|down|logs|update"; exit 1;;
    esac;;
  wordcraft|gridcraft|pdfcraft|deckcraft|ideacraft)
    # App ArtCraft: CLI+MCP per il modello e editor web (extras/artcraft). Stessa logica per entrambe.
    need_env
    app="$1"; APPU=$(echo "$app" | tr a-z A-Z)
    port=7982; [ "$app" = gridcraft ] && port=7983; [ "$app" = pdfcraft ] && port=7984; [ "$app" = deckcraft ] && port=7985; [ "$app" = ideacraft ] && port=7986
    web=1   # tutte le app hanno l'editor web (per le app future senza: web=0)
    svcs="$app"; [ "$web" = 1 ] && svcs="$app $app-web"
    set_env() { # set_env CHIAVE valore (idempotente)
      if grep -q "^$1=" .env; then sed -i.bak "s#^$1=.*#$1=$2#" .env && rm -f .env.bak; else echo "$1=$2" >> .env; fi
    }
    case "${2:-up}" in
      up|build)
        mkdir -p "data/$app"
        if grep -q '^COMPOSE_PROFILES=' .env; then
          grep -q "^COMPOSE_PROFILES=.*$app" .env || { sed -i.bak "s/^COMPOSE_PROFILES=\(.*\)\$/COMPOSE_PROFILES=\1,$app/" .env && rm -f .env.bak; }
        else
          echo "COMPOSE_PROFILES=$app" >> .env
        fi
        set_env "${APPU}_HOST" "$app:$port"
        [ "$web" = 1 ] && set_env "${APPU}_WEB" 1
        echo ">> Build di $app (compila Rust: la prima volta anche 30-60 minuti)…"
        # shellcheck disable=SC2086
        DOCKER_BUILDKIT=1 compose --profile "$app" build $svcs
        # shellcheck disable=SC2086
        compose --profile "$app" up -d $svcs
        compose up -d --build backend
        compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true
        case "$app" in
          wordcraft) echo ">> WordCraft attivo. In chat: 'scrivimi una lettera in Word'; nel menu: 📝 Documenti per l'editor completo.";;
          gridcraft) echo ">> GridCraft attivo. In chat: 'fammi il bilancio in Excel'; nel menu: 📝 Documenti per l'editor completo.";;
          pdfcraft)  echo ">> PdfCraft attivo. In chat: 'unisci questi PDF', 'estrai le pagine 2-4'; ✏️ accanto ai PDF apre l'editor.";;
          deckcraft) echo ">> DeckCraft attivo. In chat: 'fammi una presentazione di 6 slide su…'; ✏️ accanto ai .pptx apre l'editor.";;
          ideacraft) echo ">> IdeaCraft attivo. In chat: 'fammi una mappa mentale su…'; ✏️ accanto alle mappe apre l'editor.";;
        esac;;
      down)
        # shellcheck disable=SC2086
        compose --profile "$app" stop $svcs
        set_env "${APPU}_HOST" ""
        [ "$web" = 1 ] && set_env "${APPU}_WEB" ""
        compose up -d backend;;
      logs) compose --profile "$app" logs -f --tail=100 $svcs;;
      upgrade)
        # prende l'ultimo commit del repository dell'app e ricompila (incrementale grazie alla cache di cargo)
        repo="https://github.com/rickyb82/$app"
        sha=$(git ls-remote "$repo" HEAD 2>/dev/null | cut -f1)
        [ -n "$sha" ] || { echo "!! non riesco a leggere $repo (rete?)"; exit 1; }
        if grep -q "^${APPU}_SHA=$sha" .env; then echo ">> $app e' gia' all'ultimo commit (${sha:0:10})"; exit 0; fi
        echo ">> $app: aggiorno al commit ${sha:0:10} e ricompilo…"
        set_env "${APPU}_SHA" "$sha"
        # shellcheck disable=SC2086
        DOCKER_BUILDKIT=1 compose --profile "$app" build $svcs || { echo "!! Build fallita: se l'errore viene da familai-web-patch.py il sorgente upstream e' cambiato e la patch va aggiornata."; exit 1; }
        # shellcheck disable=SC2086
        compose --profile "$app" up -d $svcs
        docker image prune -f >/dev/null
        echo ">> $app aggiornato.";;
      *) echo "uso: ./familai.sh $app up|down|logs|upgrade"; exit 1;;
    esac;;
  deploy)
    # Aggiorna la macchina di produzione da qui: push del repo e "update" remoto.
    # Destinazione: argomento (user@host[:dir]) oppure file .deploy con una riga  user@host[:dir]
    target="${2:-$(cat .deploy 2>/dev/null || true)}"
    [ -n "$target" ] || { echo "uso: ./familai.sh deploy user@host[:/percorso/FamilAI]   (oppure scrivi la destinazione nel file .deploy)"; exit 1; }
    rhost="${target%%:*}"; rdir="${target#*:}"; [ "$rdir" = "$target" ] && rdir="FamilAI"
    if [ -d .git ] && git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
      echo ">> git push"; git push
    else
      echo ">> (nessun remote git: copio i file via rsync)"
      rsync -az --delete --exclude data --exclude backups --exclude .env --exclude .familai-mode --exclude node_modules --exclude .git ./ "$rhost:$rdir/"
    fi
    echo ">> update su $rhost:$rdir"
    ssh -t "$rhost" "cd '$rdir' && ./familai.sh update";;
  *) sed -n '2,10p' "$0";;
esac
