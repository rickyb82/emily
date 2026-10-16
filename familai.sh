#!/usr/bin/env bash
# Gestione FamilAI: stesso script sul Mac (anteprima) e sulla macchina Ubuntu (produzione).
#   ./familai.sh dev        avvia in locale su http://localhost:8080 (senza certificati)
#   ./familai.sh prod       avvia in produzione (HTTPS: certificato pubblico, o CA interna con TLS_MODE=internal per la rete locale)
#   ./familai.sh ca-cert    esporta la CA interna (data/emily-ca.crt) da installare sui PC quando TLS_MODE=internal
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
#   ./familai.sh ideacraft up|down|logs|upgrade  IdeaCraft: mappe mentali e diagrammi dalla chat (SVG + file nativo) + editor nel browser
#   ./familai.sh mailcraft up|down|logs|upgrade  MailCraft: posta elettronica (IMAP/SMTP) per utente, web app + tool in chat
#   ./familai.sh remotecraft up|down|logs|upgrade RemoteCraft: assistenza remota (server RustDesk + gestionale) per tecnico
#   ./familai.sh quotecraft up|down|logs|upgrade QuoteCraft: preventivi con listino per il commerciale (documenti via WordCraft, invio via MailCraft)
#   ./familai.sh covercraft up|down|logs|upgrade|db|geo CoverCraft: verifica copertura connettivita' (TIM, Open Fiber, Fastweb, ponti radio) dal database dell'operatore; geo = Nominatim
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
  tar czf "$out" data .env $( [ -d private ] && echo private ) 2>/dev/null || tar czf "$out" data
  ls -t backups/familai-*.tar.gz | tail -n +15 | xargs -r rm -f   # tieni gli ultimi 14
  echo ">> Backup: $out"
}

case "${1:-}" in
  dev)
    need_env; echo dev > "$MODE_FILE"
    compose up -d --build
    ip=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
    echo ">> Emily in anteprima su http://localhost:8080${ip:+  (dagli altri PC della rete: http://$ip:8080)}  (log: ./familai.sh logs)";;
  prod)
    need_env; echo prod > "$MODE_FILE"
    grep -q "PUBLIC_HOST=familai.example.com" .env && { echo "!! Imposta PUBLIC_HOST (nome DNS o IP del server), ACME_EMAIL e WEBAUTHN_* nel .env prima della produzione"; exit 1; }
    compose up -d --build
    host=$(grep ^PUBLIC_HOST= .env | cut -d= -f2)
    hp=$(grep ^HTTPS_PORT= .env | cut -d= -f2 || true); [ -n "$hp" ] && [ "$hp" != 443 ] && host="$host:$hp"
    echo ">> Emily in produzione su https://$host"
    if grep -q '^TLS_MODE=internal' .env; then
      echo ">> TLS con CA interna: sui PC va installata la CA (./familai.sh ca-cert → data/emily-ca.crt)"
    else
      echo ">> Certificato pubblico automatico: $host deve risolvere su questo server e le porte 80/443 devono essere raggiungibili da internet"
    fi;;
  ca-cert)
    # Esporta la CA interna di Caddy (TLS_MODE=internal) da installare come autorita' attendibile su PC, Mac e telefoni
    need_env
    mkdir -p data
    compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > data/emily-ca.crt 2>/dev/null \
      && echo ">> CA salvata in data/emily-ca.crt. Installala come 'autorita' di certificazione radice attendibile':" \
      && echo "   macOS: doppio clic → Accesso Portachiavi → Sistema → fidati sempre;  Windows: certmgr → Autorita' radice attendibili;" \
      && echo "   iPhone/iPad: invia il file, Impostazioni → Profilo scaricato → installa, poi Generali → Info → Impostazioni certificati → abilita;" \
      && echo "   Android: Impostazioni → Sicurezza → Credenziali → installa certificato CA." \
      || echo "!! Caddy non e' in esecuzione in modalita' prod con TLS_MODE=internal";;
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
  mailcraft)
    # MailCraft (extras/artcraft/Dockerfile.mailcraft): posta elettronica per utente (IMAP/SMTP), web app su /mailcraft/,
    # tool MCP per utente in chat. Un solo container; dati in ./private/mailcraft (fuori da ./data).
    need_env
    set_env() { if grep -q "^$1=" .env; then sed -i.bak "s#^$1=.*#$1=$2#" .env && rm -f .env.bak; else echo "$1=$2" >> .env; fi; }
    case "${2:-up}" in
      up|build|upgrade)
        mkdir -p private/mailcraft data/mailcraft
        if grep -q '^COMPOSE_PROFILES=' .env; then
          grep -q "^COMPOSE_PROFILES=.*mailcraft" .env || { sed -i.bak "s/^COMPOSE_PROFILES=\(.*\)\$/COMPOSE_PROFILES=\1,mailcraft/" .env && rm -f .env.bak; }
        else
          echo "COMPOSE_PROFILES=mailcraft" >> .env
        fi
        # token di servizio (backend <-> server MailCraft): generato una volta, mai mostrato agli utenti
        grep -q '^MAILCRAFT_TOKEN=.\+' .env || set_env MAILCRAFT_TOKEN "$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
        set_env MAILCRAFT_URL "http://mailcraft:7878"
        set_env MAILCRAFT_MCP_HOST "mailcraft:7889"
        if [ "$2" = upgrade ]; then
          sha=$(git ls-remote https://github.com/rickyb82/mailcraft HEAD 2>/dev/null | cut -f1)
          [ -n "$sha" ] || { echo "!! non riesco a leggere il repository mailcraft (rete?)"; exit 1; }
          if grep -q "^MAILCRAFT_SHA=$sha" .env; then echo ">> mailcraft e' gia' all'ultimo commit (${sha:0:10})"; exit 0; fi
          echo ">> mailcraft: aggiorno al commit ${sha:0:10} e ricompilo…"
          set_env MAILCRAFT_SHA "$sha"
        fi
        echo ">> Build di MailCraft (compila Rust + WebAssembly: la prima volta anche 20-40 minuti)…"
        DOCKER_BUILDKIT=1 compose --profile mailcraft build mailcraft
        compose --profile mailcraft up -d mailcraft
        compose up -d --build backend
        compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true
        echo ">> MailCraft attivo. Menu 🧰 Produttivita' > ✉️ Posta: ogni adulto configura le sue caselle (anche piu' di una)."
        echo "   In chat: 'leggi le mail non lette', 'rispondi a Luca…', 'configura la mia casella Aruba…'.";;
      down)
        compose --profile mailcraft stop mailcraft
        set_env MAILCRAFT_URL ""
        set_env MAILCRAFT_MCP_HOST ""
        compose up -d backend;;
      logs) compose --profile mailcraft logs -f --tail=100 mailcraft;;
      *) echo "uso: ./familai.sh mailcraft up|build|down|logs|upgrade"; exit 1;;
    esac;;
  remotecraft)
    # RemoteCraft: server RustDesk + gestionale assistenza (clienti, PC, interventi, GDPR); web app su /remotecraft/, tool MCP per tecnico.
    need_env
    set_env() { if grep -q "^$1=" .env; then sed -i.bak "s#^$1=.*#$1=$2#" .env && rm -f .env.bak; else echo "$1=$2" >> .env; fi; }
    case "${2:-up}" in
      up|build|upgrade)
        mkdir -p private/remotecraft/rustdesk private/remotecraft/desk
        if grep -q '^COMPOSE_PROFILES=' .env; then
          grep -q "^COMPOSE_PROFILES=.*remotecraft" .env || { sed -i.bak "s/^COMPOSE_PROFILES=\(.*\)\$/COMPOSE_PROFILES=\1,remotecraft/" .env && rm -f .env.bak; }
        else
          echo "COMPOSE_PROFILES=remotecraft" >> .env
        fi
        # token di servizio (>= 32 caratteri, lo pretende RemoteCraft)
        tok=$(grep '^REMOTECRAFT_TOKEN=' .env | cut -d= -f2- || true); [ ${#tok} -ge 32 ] || set_env REMOTECRAFT_TOKEN "$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
        set_env REMOTECRAFT_URL "http://remotecraft:7979"
        set_env REMOTECRAFT_MCP_HOST "remotecraft-mcp:7989"
        grep -q '^RUSTDESK_HOST=.\+' .env || echo "!! Imposta RUSTDESK_HOST=<nome pubblico del server RustDesk> nel .env (i client lo usano come relay)"
        if [ "$2" = upgrade ]; then
          sha=$(git ls-remote https://github.com/rickyb82/remotecraft HEAD 2>/dev/null | cut -f1)
          [ -n "$sha" ] || { echo "!! non riesco a leggere il repository remotecraft (rete?)"; exit 1; }
          if grep -q "^REMOTECRAFT_REF=$sha" .env; then echo ">> remotecraft e' gia' all'ultimo commit (${sha:0:10})"; exit 0; fi
          echo ">> remotecraft: aggiorno al commit ${sha:0:10} e ricompilo…"
          set_env REMOTECRAFT_REF "$sha"
        fi
        echo ">> Build di RemoteCraft dal repository (compila Rust + WebAssembly: la prima volta anche 20-40 minuti)…"
        DOCKER_BUILDKIT=1 compose --profile remotecraft build remotecraft remotecraft-mcp
        compose --profile remotecraft up -d remotecraft remotecraft-mcp
        compose up -d --build backend
        compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true
        echo ">> RemoteCraft attivo: menu 🧰 Produttivita' > 🛟 Assistenza. Porte RustDesk pubbliche 21115-21117 (tcp, 21116 anche udp)."
        echo "   Chiave e configurazione client: docker compose exec -u remotecraft remotecraft remotecraft-cli rustdesk";;
      down)
        compose --profile remotecraft stop remotecraft remotecraft-mcp
        set_env REMOTECRAFT_URL ""
        set_env REMOTECRAFT_MCP_HOST ""
        compose up -d backend;;
      logs) compose --profile remotecraft logs -f --tail=100 remotecraft remotecraft-mcp;;
      *) echo "uso: ./familai.sh remotecraft up|build|down|logs|upgrade"; exit 1;;
    esac;;
  quotecraft)
    # QuoteCraft: preventivatore con listino; web app su /quotecraft/ (API via backend), tool MCP per utente, documenti con wordcraft-cli, invio via MailCraft.
    need_env
    set_env() { if grep -q "^$1=" .env; then sed -i.bak "s#^$1=.*#$1=$2#" .env && rm -f .env.bak; else echo "$1=$2" >> .env; fi; }
    case "${2:-up}" in
      up|build|upgrade)
        mkdir -p private/quotecraft data/quotecraft
        if grep -q '^COMPOSE_PROFILES=' .env; then
          grep -q "^COMPOSE_PROFILES=.*quotecraft" .env || { sed -i.bak "s/^COMPOSE_PROFILES=\(.*\)\$/COMPOSE_PROFILES=\1,quotecraft/" .env && rm -f .env.bak; }
        else
          echo "COMPOSE_PROFILES=quotecraft" >> .env
        fi
        tok=$(grep '^QUOTECRAFT_TOKEN=' .env | cut -d= -f2- || true); [ ${#tok} -ge 32 ] || set_env QUOTECRAFT_TOKEN "$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
        set_env QUOTECRAFT_URL "http://quotecraft:7878"
        set_env QUOTECRAFT_MCP_HOST "quotecraft:7899"
        if [ "$2" = upgrade ]; then
          sha=$(git ls-remote https://github.com/rickyb82/quotecraft HEAD 2>/dev/null | cut -f1)
          [ -n "$sha" ] || { echo "!! non riesco a leggere il repository quotecraft (rete?)"; exit 1; }
          if grep -q "^QUOTECRAFT_REF=$sha" .env; then echo ">> quotecraft e' gia' all'ultimo commit (${sha:0:10})"; exit 0; fi
          echo ">> quotecraft: aggiorno al commit ${sha:0:10} e ricompilo…"
          set_env QUOTECRAFT_REF "$sha"
        fi
        echo ">> Build di QuoteCraft dal repository (compila Rust + WebAssembly + wordcraft-cli: la prima volta anche 30-60 minuti)…"
        DOCKER_BUILDKIT=1 compose --profile quotecraft build quotecraft
        compose --profile quotecraft up -d quotecraft
        # invio via MailCraft a nome dell'utente: URL e token di servizio di MailCraft nelle preferenze di QuoteCraft (una volta)
        mtok=$(grep '^MAILCRAFT_TOKEN=' .env | cut -d= -f2- || true)
        if [ -n "$mtok" ]; then
          sleep 3
          compose --profile quotecraft exec -T -u quotecraft quotecraft quotecraft-cli prefs --home /qc "mailcraft_url=http://mailcraft:7878" "mailcraft_token=$mtok" >/dev/null 2>&1 \
            && echo ">> MailCraft collegato: i preventivi partono dall'account di posta dell'utente" \
            || echo "!! non sono riuscito a impostare MailCraft nelle preferenze di QuoteCraft: dalle Impostazioni della web app (mailcraft_url=http://mailcraft:7878, token = MAILCRAFT_TOKEN del .env)"
        else
          echo "   MailCraft non attivo: i preventivi si generano ma non si spediscono (./familai.sh mailcraft up, poi di nuovo quotecraft up)"
        fi
        compose up -d --build backend
        compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true
        echo ">> QuoteCraft attivo: menu 🧰 Produttivita' > 💶 Preventivi (cartella APP) e tool mcp__quotecraft__* in chat."
        echo "   Listino, carta intestata e azienda li gestiscono il super amministratore e gli amministratori dell'app (scheda del membro > Software)."
        echo "   Dati in private/quotecraft/ (nel backup); documenti prodotti in data/quotecraft/.";;
      down)
        compose --profile quotecraft stop quotecraft
        set_env QUOTECRAFT_URL ""
        set_env QUOTECRAFT_MCP_HOST ""
        compose up -d backend;;
      logs) compose --profile quotecraft logs -f --tail=100 quotecraft;;
      *) echo "uso: ./familai.sh quotecraft up|build|down|logs|upgrade"; exit 1;;
    esac;;
  covercraft)
    # CoverCraft: verifica di copertura a un indirizzo dal database netmap dell'operatore; web app su /covercraft/ (API via backend), tool MCP per utente.
    need_env
    set_env() { if grep -q "^$1=" .env; then sed -i.bak "s#^$1=.*#$1=$2#" .env && rm -f .env.bak; else echo "$1=$2" >> .env; fi; }
    case "${2:-up}" in
      up|build|upgrade)
        mkdir -p private/covercraft
        if grep -q '^COMPOSE_PROFILES=' .env; then
          grep -q "^COMPOSE_PROFILES=.*covercraft" .env || { sed -i.bak "s/^COMPOSE_PROFILES=\(.*\)\$/COMPOSE_PROFILES=\1,covercraft/" .env && rm -f .env.bak; }
        else
          echo "COMPOSE_PROFILES=covercraft" >> .env
        fi
        # token di servizio: resta tra backend e container (il browser non lo vede mai)
        tok=$(grep '^COVERCRAFT_TOKEN=' .env | cut -d= -f2- || true); [ ${#tok} -ge 32 ] || set_env COVERCRAFT_TOKEN "$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
        set_env COVERCRAFT_URL "http://covercraft:7979"
        set_env COVERCRAFT_MCP_HOST "covercraft:7999"
        if [ "$2" = upgrade ]; then
          sha=$(git ls-remote https://github.com/rickyb82/covercraft HEAD 2>/dev/null | cut -f1)
          [ -n "$sha" ] || { echo "!! non riesco a leggere il repository covercraft (rete?)"; exit 1; }
          if grep -q "^COVERCRAFT_REF=$sha" .env; then echo ">> covercraft e' gia' all'ultimo commit (${sha:0:10})"; exit 0; fi
          echo ">> covercraft: aggiorno al commit ${sha:0:10} e ricompilo…"
          set_env COVERCRAFT_REF "$sha"
        fi
        echo ">> Build di CoverCraft dal repository (compila Rust + WebAssembly: la prima volta anche 20-40 minuti)…"
        DOCKER_BUILDKIT=1 compose --profile covercraft build covercraft
        compose --profile covercraft up -d covercraft
        compose up -d --build backend
        compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true
        echo ">> CoverCraft attivo: menu 🧰 Produttivita' > 📡 Copertura (cartella APP nei Documenti) e tool mcp__covercraft__* in chat."
        echo "   Collega il database netmap (una volta sola): ./familai.sh covercraft db --kind mysql --host <ip> --port 3306 --user netmap --password '…' --database netmap"
        echo "   Basta un utente MySQL in sola lettura: lo storico delle verifiche e' locale (private/covercraft/history.jsonl)."
        echo "   Configurazione in private/covercraft/ (password in secrets.json: inclusa nel backup). Geocoder facoltativo: ./familai.sh covercraft geo up";;
      db)
        # inoltra a covercraft-cli db dentro il container: ./familai.sh covercraft db --kind mysql --host … --user … --password … --database netmap
        shift 2
        compose --profile covercraft exec -u covercraft covercraft covercraft-cli db --home /data "$@"
        echo ">> riavvio CoverCraft per rileggere la configurazione…"; compose --profile covercraft restart covercraft;;
      down)
        compose --profile covercraft stop covercraft
        set_env COVERCRAFT_URL ""
        set_env COVERCRAFT_MCP_HOST ""
        compose up -d backend;;
      logs) compose --profile covercraft logs -f --tail=100 covercraft;;
      geo)
        # Nominatim (geocoder OpenStreetMap) per i civici senza coordinate nelle tabelle: ./familai.sh covercraft geo up|down|logs
        case "${3:-up}" in
          up)
            if grep -q '^COMPOSE_PROFILES=' .env; then
              grep -q "^COMPOSE_PROFILES=.*nominatim" .env || { sed -i.bak "s/^COMPOSE_PROFILES=\(.*\)\$/COMPOSE_PROFILES=\1,nominatim/" .env && rm -f .env.bak; }
            else
              echo "COMPOSE_PROFILES=nominatim" >> .env
            fi
            grep -q '^NOMINATIM_PASSWORD=.\+' .env || set_env NOMINATIM_PASSWORD "$(openssl rand -hex 16 2>/dev/null || head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
            echo ">> Avvio Nominatim: il primo avvio importa l'Italia (~2 GB di download, 1-3 ore, serve ~10 GB di RAM per Docker)…"
            compose --profile nominatim up -d nominatim
            compose --profile covercraft exec -u covercraft covercraft covercraft-cli prefs --home /data geocode_url=http://nominatim:8080 >/dev/null \
              && compose --profile covercraft restart covercraft >/dev/null \
              && echo ">> CoverCraft usera' http://nominatim:8080 quando le tabelle non danno un punto (appena l'import e' finito: ./familai.sh covercraft geo logs)." \
              || echo "!! CoverCraft non e' attivo: dopo './familai.sh covercraft up' imposta il geocoder dalle Impostazioni (geocode_url=http://nominatim:8080)";;
          down)
            compose --profile nominatim stop nominatim
            compose --profile covercraft exec -u covercraft covercraft covercraft-cli prefs --home /data geocode_url= >/dev/null 2>&1 && compose --profile covercraft restart covercraft >/dev/null 2>&1 || true
            echo ">> Nominatim fermo (i dati importati restano nei volumi nominatim-data/nominatim-flatnode)";;
          logs) compose --profile nominatim logs -f --tail=100 nominatim;;
          *) echo "uso: ./familai.sh covercraft geo up|down|logs"; exit 1;;
        esac;;
      *) echo "uso: ./familai.sh covercraft up|build|down|logs|upgrade|db …|geo up|down|logs"; exit 1;;
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
  *) sed -n '2,18p' "$0";;
esac
