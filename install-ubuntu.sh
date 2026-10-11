#!/usr/bin/env bash
# Installazione FamilAI su Ubuntu (22.04/24.04) in un colpo solo: Docker, clone del repo, .env, avvio in produzione.
#
#   Uso tipico (dalla Ubuntu, come utente normale con sudo):
#     curl -fsSL https://raw.githubusercontent.com/<utente>/FamilAI/main/install-ubuntu.sh | bash -s -- \
#         --repo https://github.com/<utente>/FamilAI.git --host familai.tuodominio.it --email tu@esempio.it
#   oppure, se il repo e' gia' clonato:  ./install-ubuntu.sh --host familai.tuodominio.it --email tu@esempio.it
#
#   Opzioni: --repo URL  --dir /percorso (default ~/FamilAI)  --host DOMINIO  --email EMAIL_ACME
#            --admin-email EMAIL --admin-password PASS  --ollama (avvia anche il modello locale nel compose)
#            --dev (anteprima http://IP:8080 senza dominio/certificati)  --portainer (pannello web Docker su :9443)
set -euo pipefail

REPO=""; DIR="$HOME/FamilAI"; HOST=""; EMAIL=""; ADMIN_EMAIL=""; ADMIN_PASS=""; OLLAMA=0; DEV=0; PORTAINER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;
    --dir) DIR="$2"; shift 2;;
    --host) HOST="$2"; shift 2;;
    --email) EMAIL="$2"; shift 2;;
    --admin-email) ADMIN_EMAIL="$2"; shift 2;;
    --admin-password) ADMIN_PASS="$2"; shift 2;;
    --ollama) OLLAMA=1; shift;;
    --dev) DEV=1; shift;;
    --portainer) PORTAINER=1; shift;;
    *) echo "opzione sconosciuta: $1"; exit 1;;
  esac
done

say() { printf '\n\033[1;34m>> %s\033[0m\n' "$*"; }

# ---------- Docker ----------
if ! command -v docker >/dev/null 2>&1; then
  say "Installo Docker Engine + Compose (repository ufficiale)"
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl gnupg git
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
fi
if ! id -nG "$USER" | grep -qw docker; then
  say "Aggiungo $USER al gruppo docker"
  sudo usermod -aG docker "$USER"
  NEWGRP=1
else
  NEWGRP=0
fi
command -v git >/dev/null 2>&1 || sudo apt-get install -y git

# ---------- repo ----------
if [ -f "./familai.sh" ] && [ -z "$REPO" ]; then
  DIR="$(pwd)"
elif [ ! -d "$DIR/.git" ]; then
  [ -n "$REPO" ] || { echo "!! Serve --repo URL (il repository git di FamilAI) oppure lancia lo script dentro la cartella del progetto"; exit 1; }
  say "Clono $REPO in $DIR"
  git clone "$REPO" "$DIR"
else
  say "Repo gia' presente in $DIR: aggiorno"
  git -C "$DIR" pull --ff-only || true
fi
cd "$DIR"
chmod +x familai.sh install-ubuntu.sh 2>/dev/null || true

# ---------- .env ----------
if [ ! -f .env ]; then
  say "Creo .env"
  cp .env.example .env
  KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$KEY/" .env
  if [ -n "$HOST" ]; then
    sed -i "s/^PUBLIC_HOST=.*/PUBLIC_HOST=$HOST/; s/^WEBAUTHN_RP_ID=.*/WEBAUTHN_RP_ID=$HOST/; s#^WEBAUTHN_ORIGIN=.*#WEBAUTHN_ORIGIN=https://$HOST#" .env
  fi
  [ -n "$EMAIL" ] && sed -i "s/^ACME_EMAIL=.*/ACME_EMAIL=$EMAIL/" .env
  [ -n "$ADMIN_EMAIL" ] && sed -i "s/^ADMIN_EMAIL=.*/ADMIN_EMAIL=$ADMIN_EMAIL/" .env
  if [ -n "$ADMIN_PASS" ]; then
    sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$ADMIN_PASS/" .env
  else
    GEN=$(openssl rand -base64 12 | tr -d '/+=' | head -c 14)
    sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$GEN/" .env
    echo ">> Password iniziale dell'amministratore: $GEN  (salvala, poi cambiala dal pannello o ripristina un backup)"
  fi
  if [ "$OLLAMA" = 1 ]; then
    grep -q '^COMPOSE_PROFILES=' .env || echo "COMPOSE_PROFILES=ollama" >> .env
    sed -i "s#^OLLAMA_URL=.*#OLLAMA_URL=http://ollama:11434#" .env
  fi
else
  say ".env gia' presente: non lo tocco"
fi
mkdir -p data backups

# ---------- firewall (se ufw e' attivo) ----------
if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
  say "Apro le porte 80/443 (ufw)"
  sudo ufw allow 80/tcp >/dev/null; sudo ufw allow 443/tcp >/dev/null
  [ "$DEV" = 1 ] && sudo ufw allow 8080/tcp >/dev/null
  [ "$PORTAINER" = 1 ] && sudo ufw allow from 192.168.0.0/16 to any port 9443 proto tcp >/dev/null
fi

# ---------- porte occupate? (es. Pi-hole usa la 80 per la sua interfaccia) ----------
if [ "$DEV" = 0 ]; then
  for port in 80 443; do
    if (command -v ss >/dev/null && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$"); then
      echo "!! La porta $port e' gia' occupata su questa macchina (controlla con: sudo ss -ltnp | grep ':$port')."
      echo "   Caddy (HTTPS di FamilAI) ne ha bisogno. Se e' Pi-hole: sposta la sua interfaccia web su un'altra porta"
      echo "   (Pi-hole in Docker: cambia il mapping '80:80' in '8081:80' nel suo compose e riavvialo;"
      echo "    Pi-hole nativo v6: 'sudo pihole-FTL --config webserver.port 8081'; v5: /etc/lighttpd/external.conf server.port = 8081)."
      echo "   Poi rilancia questo script."
      exit 1
    fi
  done
fi

# ---------- avvio ----------
RUN="./familai.sh"
[ "$NEWGRP" = 1 ] && RUN="sg docker -c './familai.sh"
say "Avvio FamilAI ($([ "$DEV" = 1 ] && echo anteprima || echo produzione))"
if [ "$NEWGRP" = 1 ]; then
  sg docker -c "./familai.sh $([ "$DEV" = 1 ] && echo dev || echo prod)"
else
  ./familai.sh $([ "$DEV" = 1 ] && echo dev || echo prod)
fi
if [ "$OLLAMA" = 1 ]; then
  say "Scarico i modelli locali (qwen3:8b e qwen3:4b): puo' richiedere qualche minuto"
  docker compose exec -T ollama ollama pull qwen3:8b || true
  docker compose exec -T ollama ollama pull qwen3:4b || true
fi

if [ "$PORTAINER" = 1 ]; then
  say "Avvio Portainer (pannello Docker)"
  if [ "$NEWGRP" = 1 ]; then sg docker -c "./familai.sh portainer up"; else ./familai.sh portainer up; fi
fi

say "Fatto."
if [ "$DEV" = 1 ]; then
  echo "   Apri http://$(hostname -I | awk '{print $1}'):8080"
else
  echo "   Apri https://${HOST:-<PUBLIC_HOST>}  (le porte 80 e 443 del router devono puntare a questa macchina e il DNS al tuo IP pubblico)"
fi
echo "   Aggiornamenti: cd $DIR && ./familai.sh update"
[ "$PORTAINER" = 1 ] && echo "   Pannello Docker: https://$(hostname -I | awk '{print $1}'):9443  (apri subito e crea l'utente admin: dopo 5 minuti va riavviato con ./familai.sh portainer down && ./familai.sh portainer up)"
[ "$NEWGRP" = 1 ] && echo "   Nota: esci e rientra nella shell (o 'newgrp docker') per usare docker senza sudo."
exit 0
