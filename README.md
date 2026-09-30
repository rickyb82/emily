# FamilAI — assistente AI di famiglia

Framework self-hosted stile "chatbot Claude" pensato per una famiglia: adulti e bambini con livelli di permesso diversi, più provider LLM (Claude, OpenAI, Gemini), tool (ricerca web, immagini, video, documenti), server MCP, progetti e condivisione fra membri, con accesso remoto sicuro (HTTPS + passkey).

## Architettura

```
Internet ──HTTPS──▶ Caddy (TLS automatico Let's Encrypt)
                      ├── /api/*, /files/*  ──▶ backend  (FastAPI, Python)
                      └── /*                ──▶ frontend (React/Vite servito da nginx)
backend ──▶ SQLite (./data/familai.db) · ./data/uploads · ./data/generated
        ──▶ sandbox (esecuzione codice isolata, rete interna senza internet)
        ──▶ API Anthropic / OpenAI / Gemini · Tavily/Brave · server MCP (stdio o HTTP)
```

- **backend/** — FastAPI. Auth (password + passkey WebAuthn per gli adulti, PIN su dispositivi approvati per i bambini), policy per fascia d'età, agent loop con tool calling unificato per i tre provider, client MCP, progetti, condivisioni, log di utilizzo e audit.
- **frontend/** — Webapp React (login, passkey, PIN bambini, chat in streaming, progetti, condivisione, pannello famiglia).
- **Caddyfile / docker-compose.yml** — deploy su Ubuntu con un solo comando.

## Sicurezza (riassunto)

| Aspetto | Come |
|---|---|
| Trasporto | Solo HTTPS via Caddy, HSTS, header di sicurezza |
| Adulti | Email + password (Argon2) **e** passkey WebAuthn obbligatoria come secondo fattore (`REQUIRE_MFA_FOR_ADULTS`), codici di recupero monouso |
| Bambini | Login con avatar + PIN, **solo** da dispositivi approvati da un genitore (cookie di fiducia revocabile) |
| Sessioni | Cookie opaco HttpOnly + Secure + SameSite=Strict, header anti-CSRF, scadenza diversa adulti/bambini, revoca sessioni |
| Brute force | Rate limit su login/PIN, blocco account 15 min dopo 5 errori |
| Controllo genitori | Strumenti/provider consentiti, quote giornaliere (messaggi/immagini/video), fasce orarie, filtro contenuti (blocklist + OpenAI Moderation), supervisione conversazioni, messaggi segnalati, audit log |

## Avvio rapido

Tutto si gestisce con `./familai.sh` (stesso script sul Mac e sulla Ubuntu):

| Comando | Cosa fa |
|---|---|
| `./familai.sh dev` | Anteprima locale su **http://localhost:8080**, senza certificati (le passkey funzionano su localhost). Provider `mock` attivo se non hai chiavi. |
| `./familai.sh prod` | Produzione con HTTPS automatico sul dominio del `.env` |
| `./familai.sh update` | **Aggiornamento**: `git pull`, backup automatico di `data/` + `.env`, rebuild e riavvio dei soli servizi cambiati |
| `./familai.sh logs [servizio]` · `status` · `stop` | Diagnostica |
| `./familai.sh backup` · `restore backups/<file>` | Backup/ripristino di DB, file caricati e configurazione |

Al primo avvio lo script crea `.env` da `.env.example` con una `SECRET_KEY` casuale.

### 1. Anteprima sul Mac
Serve Docker Desktop. Nella cartella del progetto:
```bash
./familai.sh dev
```
Apri http://localhost:8080, entra con `ADMIN_EMAIL`/`ADMIN_PASSWORD` del `.env` (default `admin@example.com` / `changeme`), registra la passkey (Touch ID), poi in **Famiglia → Provider AI** incolla le chiavi e prova le connessioni. Il DB e i file restano in `./data`.

### 2. Installazione sulla Ubuntu
Prerequisiti: Docker + plugin Compose (`sudo apt install docker.io docker-compose-v2` oppure lo script ufficiale get.docker.com); un dominio che punta all'IP di casa; porte **80/443** inoltrate alla Ubuntu.
```bash
git clone <url-del-tuo-repo> ~/FamilAI     # vedi "Aggiornamenti" per il repository
cd ~/FamilAI
cp .env.example .env && nano .env          # PUBLIC_HOST, ACME_EMAIL, WEBAUTHN_RP_ID/ORIGIN, SECRET_KEY, ADMIN_*
./familai.sh prod
./familai.sh logs backend
```
Se vuoi partire dai dati provati sul Mac: `./familai.sh backup` sul Mac, copia il file in `backups/` sulla Ubuntu e `./familai.sh restore backups/<file>` (poi correggi `PUBLIC_HOST` e `WEBAUTHN_*` nel `.env`: le passkey registrate su `localhost` non valgono per il dominio e vanno rifatte).

> WebAuthn richiede un origin sicuro: `https://` con dominio reale oppure `http://localhost`. Non funziona su `http://192.168.x.x`.

### 3. Aggiornamenti
Il progetto è un repository git. Flusso consigliato:
1. Crea un repository **privato** (GitHub/GitLab/Gitea) e collegalo dal Mac: `git remote add origin <url> && git push -u origin main`.
2. Ogni miglioria viene committata sul Mac e pushata (`git push`).
3. Sulla Ubuntu: `./familai.sh update` → pull, backup, rebuild, riavvio. Le migrazioni leggere del DB (nuove colonne/tabelle) sono automatiche all'avvio del backend.

Senza repository remoto funziona anche con `git pull` via SSH dal Mac (`git remote add origin riccardo@mac.local:Documents/Progetti/FamilAI`) o copiando la cartella con `rsync` ed eseguendo `./familai.sh update` (senza `.git` aggiorna solo i container).

Il numero di versione è nel file `VERSION` (mostrato in Famiglia e da `/api/health`).

## Configurazione

### Provider e modelli
Le chiavi si inseriscono da **Famiglia → Provider AI** (salvate cifrate nel DB con `SECRET_KEY`, applicate a caldo, con pulsante "Prova connessione") oppure nel `.env` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `*_DEFAULT_MODEL`); il pannello ha la precedenza sul file. Attenzione: se cambi `SECRET_KEY` le chiavi salvate dal pannello non sono più leggibili e vanno reinserite.

- **Bambini**: il genitore fissa provider e modello nella scheda del membro (Permessi → Provider AI / Modello); il bambino non vede il selettore.
- **Adulti**: scelgono provider e modello chat per chat dal menu in alto. Cambiando modello in una chat esistente viene proposto di **rigenerare l'ultima risposta** con il nuovo modello (`POST /chat/conversations/{id}/regenerate`); in ogni caso la cronologia viene convertita nel formato del nuovo provider e passata ai messaggi successivi. Il pulsante "↻ Rigenera risposta" è sempre disponibile.

### Tool
- **web_search**: Tavily (`TAVILY_API_KEY`) o Brave (`BRAVE_API_KEY`); fallback DuckDuckGo limitato. Ricerca sicura forzata per i bambini.
- **generate_image**: OpenAI `IMAGE_MODEL` (gpt-image-1). Per i bambini il prompt viene prefissato con vincoli "adatto ai bambini".
- **generate_video**: Gemini/Veo `VIDEO_MODEL`.
- **read_document**: PDF, DOCX, XLSX, testo; i documenti piccoli vengono inseriti direttamente nel contesto.

### Email: inviti, password dimenticata, codice al posto della passkey
Configura l'SMTP in **Famiglia → Provider AI → Email** (pulsante "Preimposta Gmail": `smtp.gmail.com:587` STARTTLS; utente = indirizzo Gmail; password = *password per le app* di Google) e verifica con "Invia email di prova". Da quel momento:
- creando un adulto senza password parte un **invito** con link (valido 48 h) per scegliere la password (pulsante "✉️ Invito" per reinviarlo);
- al login compare **"Password dimenticata?"**: codice a 6 cifre via email (10 min, 5 tentativi) e nuova password;
- se `EMAIL_MFA_FALLBACK=true`, al passo passkey si può chiedere **un codice via email** come secondo fattore alternativo (comodo contro i blocchi, leggermente meno sicuro della sola passkey: disattivabile dal pannello).

### Costi e budget
**Famiglia → Costi** mostra per il mese corrente la spesa **stimata** per provider e per membro (log di utilizzo × listino prezzi modificabile), un **budget mensile** per provider con rimanente e barra, e, inserendo le chiavi *Admin* di Anthropic/OpenAI, la **spesa reale** letta dai rispettivi report di costo dell'organizzazione. Nessun provider espone il credito residuo a una chiave API normale; Gemini non offre report via API.

### Coding, artifact e anteprime
- **Artifact** (`create_artifact` / `update_artifact`): pagine e app HTML/CSS/JS, SVG, diagrammi Mermaid, markdown e programmi completi vengono creati in un pannello laterale con schede *Anteprima* e *Codice*, versioni, modifica manuale, download e apertura in nuova scheda. L'anteprima gira in un `<iframe sandbox>` senza `allow-same-origin`, quindi il codice generato non può leggere cookie né chiamare le API di FamilAI; l'endpoint `/api/artifacts/{id}/raw` aggiunge una CSP `sandbox`.
- **Esecuzione codice** (`run_code`): Python (numpy, pandas, matplotlib, pillow, sympy, scipy), JavaScript/TypeScript (Node 22), Java (JDK) e Bash girano nel servizio **`sandbox`** del compose: container separato, utente non root, filesystem read-only con tmpfs, `cap_drop: ALL`, limiti CPU/RAM/PID, timeout per esecuzione e **rete interna senza internet** (`sandbox_net: internal`). Output e file prodotti (grafici, CSV, immagini) tornano in chat come allegati. Il modello può passare file della chat/progetto alla sandbox (`file_ids`).
- Permessi: voci "Artifact" e "Esecuzione codice" nella policy. Default: 5–8 anni solo artifact, dai 9 anni anche esecuzione, adulti tutto.
- Non ancora supportato: avviare server web (Flask, Streamlit, Spring…) dentro la sandbox ed esporli in anteprima. È la naturale fase successiva (proxy verso una porta della sandbox per conversazione).

### RAG — ricerca nei documenti
Ogni documento caricato in un progetto (o allegato a una chat) viene estratto, spezzato in frammenti (`RAG_CHUNK_CHARS`) e indicizzato in background nella tabella `chunks`:
- con `OPENAI_API_KEY` o `GEMINI_API_KEY` i frammenti ricevono un **embedding** (`EMBEDDING_PROVIDER=auto|openai|gemini`) e la ricerca è **ibrida** (similarità coseno + BM25);
- senza chiavi la ricerca è solo per parole chiave (BM25), comunque utile.

A ogni messaggio l'assistente riceve automaticamente i `RAG_TOP_K` passaggi più pertinenti (evento `rag` nello stream, mostrato in chat) e dispone del tool `search_documents` per ricerche mirate; i documenti sotto `RAG_INLINE_MAX_CHARS` vengono comunque inseriti per intero. Nella pagina del progetto si vede lo stato dell'indice per file e si può **reindicizzare** (utile dopo aver aggiunto una chiave di embedding). Il permesso è lo stesso di "Documenti" nella policy dell'utente.

### Server MCP
Si gestiscono da **Famiglia → MCP**: aggiungi un server (stdio = comando avviato nel container backend, es. `npx -y @modelcontextprotocol/server-filesystem /data/shared`; http = server Streamable HTTP già in esecuzione), scegli il ruolo minimo (bambini/adulti/admin) e premi **Connetti**: la connessione avviene a caldo, senza riavvio, e i tool compaiono subito come `mcp__<server>__<tool>`. Header e variabili d'ambiente (token, chiavi) sono cifrati nel DB. Dalla tabella puoi provare ogni tool con argomenti JSON. Il file `mcp_servers.json` viene importato solo al primo avvio se il DB è vuoto.

### Policy per fascia d'età
Default in `backend/app/policy/permissions.py` (`DEFAULTS` e `SYSTEM_PROMPTS`), sovrascrivibili per singolo utente dal pannello Famiglia (strumenti, provider, quote, orari, filtro, parole bloccate, istruzioni personalizzate).

## Struttura dati principale
`families` · `users` (ruolo, fascia, policy JSON) · `webauthn_credentials` · `sessions` · `trusted_devices` · `projects` · `conversations` · `messages` (blocchi JSON: text/image/tool_use/tool_result) · `files` · `chunks` (RAG) · `artifacts` · `app_settings` · `shares` · `usage_log` · `audit_log`.

## Roadmap / idee
- Passkey come **unico** fattore (login senza password) e supporto a più famiglie.
- Vector store dedicato (pgvector/sqlite-vec) se i progetti crescono molto; re-ranking.
- Notifiche push ai genitori per messaggi segnalati.
- Voce (STT/TTS) per i più piccoli.
- Migrazioni DB con Alembic; backup automatico di `./data`.
