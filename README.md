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
| Adulti | Email + password (Argon2) **e** un secondo fattore obbligatorio a scelta (`REQUIRE_MFA_FOR_ADULTS`): passkey WebAuthn **oppure** app authenticator (TOTP: Google/Microsoft Authenticator, Authy, 1Password…), anche entrambi; codici di recupero monouso. La passkey è legata all'origine (localhost ≠ dominio), l'app authenticator vale ovunque |
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
Apri http://localhost:8080, entra con `ADMIN_EMAIL`/`ADMIN_PASSWORD` del `.env` (default `admin@example.com` / `changeme`), attiva il secondo fattore (passkey con Touch ID oppure app authenticator inquadrando il QR), poi in **Famiglia → Provider AI** incolla le chiavi e prova le connessioni. Il DB e i file restano in `./data`. Per il RAG (documenti e memoria) serve un modello di **embedding**: in locale basta `ollama pull bge-m3` (multilingua, ottimo in italiano) e in Altre impostazioni l'embedding su auto/Ollama; altrimenti OpenAI o Gemini, o solo parole chiave.

### 2. Installazione sulla Ubuntu
Prerequisiti: Docker + plugin Compose (`sudo apt install docker.io docker-compose-v2` oppure lo script ufficiale get.docker.com); un dominio che punta all'IP di casa; porte **80/443** inoltrate alla Ubuntu.
```bash
git clone <url-del-tuo-repo> ~/FamilAI     # vedi "Aggiornamenti" per il repository
cd ~/FamilAI
cp .env.example .env && nano .env          # PUBLIC_HOST, ACME_EMAIL, WEBAUTHN_RP_ID/ORIGIN, SECRET_KEY, ADMIN_*
./familai.sh prod
./familai.sh logs backend
```
Se vuoi partire dai dati provati sul Mac: `./familai.sh backup` sul Mac, copia il file in `backups/` sulla Ubuntu e `./familai.sh restore backups/<file>` (poi correggi `PUBLIC_HOST` e `WEBAUTHN_*` nel `.env`: le passkey registrate su `localhost` non valgono per il dominio e vanno rifatte; l'app authenticator invece continua a funzionare).

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
- **web_search**: con Claude in chat usa la ricerca web nativa di Anthropic (fonti citate dal modello); altrimenti il tool interroga OpenAI (API Responses, `web_search_preview`) o Gemini (grounding Google) con le chiavi già presenti, oppure Tavily/Brave se configurati; fallback DuckDuckGo. Per i bambini è forzata la ricerca sicura (istruzioni "adatto ai minori", niente tool nativo).
- **generate_image**: OpenAI `IMAGE_MODEL` (gpt-image-1). Per i bambini il prompt viene prefissato con vincoli "adatto ai bambini".
- **generate_video**: Gemini/Veo `VIDEO_MODEL`.
- **read_document**: PDF, DOCX, XLSX, testo; i documenti piccoli vengono inseriti direttamente nel contesto.

### Installazione sulla Ubuntu e aggiornamenti
Sulla Ubuntu basta lo script `install-ubuntu.sh`: installa Docker, clona il repo, crea il `.env` (SECRET_KEY casuale, dominio, password admin) e avvia in produzione. Esempio:

```
curl -fsSL https://raw.githubusercontent.com/<utente>/FamilAI/main/install-ubuntu.sh | bash -s -- \
  --repo https://github.com/<utente>/FamilAI.git --host familai.tuodominio.it --email tu@esempio.it [--ollama]
```

Servono DNS del dominio verso l'IP pubblico di casa e porte 80/443 del router inoltrate alla Ubuntu (Caddy ottiene i certificati da solo). Poi, dal pannello **Famiglia → Backup**, carica il backup fatto sul Mac e ritrovi tutto.

Aggiornare: sulla Ubuntu `./familai.sh update` (git pull + rebuild dei soli servizi cambiati + backup automatico). Dal Mac in un colpo solo: `./familai.sh deploy utente@ubuntu` (fa il `git push` e lancia `update` via SSH; la destinazione si può scrivere una volta nel file `.deploy`). Senza un remote git, `deploy` copia i file con rsync.

### Pannello Docker (Portainer)
`./familai.sh portainer up` (o `--portainer` nello script di installazione) avvia Portainer CE su `https://<ip-macchina>:9443`: container, immagini, volumi, log, console e "Stack" (file compose incollati nel browser) per aggiungere altri servizi alla stessa macchina. Certificato autofirmato, pensato per la rete locale: il firewall lo apre solo alle reti 192.168.x.x. Al primo avvio crea l'amministratore entro 5 minuti.

### Backup completo e ripristino (pannello)
In **Famiglia → Backup** si scarica un unico file `.fab` cifrato con una password a scelta: contiene il database (membri, permessi, chat, progetti, artifact, server MCP, impostazioni), i file caricati/generati e i segreti in chiaro (chiavi API, SMTP, token Gmail, authenticator), che nel DB sono cifrati con una chiave derivata da `SECRET_KEY`. Per reinstallare da zero: avvia FamilAI, entra con l'amministratore iniziale del `.env`, vai in Backup e carica il file con la sua password. Il backend si riavvia, sostituisce dati e file (copia dei precedenti in `data/pre-restore-…`), ricifra i segreti con la nuova `SECRET_KEY` e chiude tutte le sessioni. Le passkey tornano a funzionare solo se `PUBLIC_HOST`/`WEBAUTHN_*` sono gli stessi; altrimenti si entra con app authenticator o codice di recupero.

### Modello locale (Ollama) e router "Auto"
FamilAI può usare un modello open source locale (provider **Locale (Ollama)**), gratis e senza far uscire i dati di casa. Consigliati con 16–24 GB di memoria: `qwen3:8b` per le risposte e `qwen3:4b` come router (entrambi multilingua, con tool). Sul **Mac** Ollama va installato nativo (`brew install ollama`, `ollama pull qwen3:8b`, `ollama pull qwen3:4b`): dentro Docker non userebbe la GPU. Poi in **Famiglia → Provider AI → Modello locale** metti `http://host.docker.internal:11434` e prova la connessione. Sulla **Ubuntu** puoi avviarlo nel compose con `COMPOSE_PROFILES=ollama` nel `.env` e indirizzo `http://ollama:11434` (scarica i modelli con `docker compose exec ollama ollama pull qwen3:8b`).

Oltre a Ollama si può collegare qualsiasi **server LLM con API compatibile OpenAI** (vLLM, llama.cpp server, LM Studio, TGI…): in **Provider AI → Server LLM di casa** inserisci l'indirizzo (es. `http://192.168.4.2:8000`; il percorso `/v1/chat/completions` e `/v1/models` vengono aggiunti da soli), eventuale chiave API e nome. I modelli esposti da `/v1/models` compaiono nel menu (es. `openai/gpt-oss-120b`) e il server usa tutti i tool. Il router Auto risponde in locale con questo server se presente (altrimenti con Ollama), mentre il classificatore veloce gira su Ollama se c'è.

Con un provider locale attivo compare il provider **Auto (locale + cloud)**: a ogni messaggio il modello locale piccolo classifica la richiesta e decide se rispondere in locale (domande semplici, chiacchiere, traduzioni, riassunti) o inoltrarla al provider cloud (codice, ragionamento, ricerca, immagini, file, tool). In chat ogni risposta mostra da chi è arrivata. Modalità (Altre impostazioni): *bilanciato*, *economico*, *qualità*, *off*. Anche i bambini possono avere Auto o il modello locale come provider fisso.

### Immagini in casa (ComfyUI su GPU NVIDIA)
`extras/comfyui/` contiene il compose di ComfyUI (immagine `yanwk/comfyui-boot`, GPU via nvidia-container-toolkit, modelli nel volume `storage/`) e `download-models.sh` che scarica i modelli open nelle cartelle giuste: `flux-schnell` (Apache 2.0, 4 passi), `flux-dev` (qualità massima, serve `HF_TOKEN` dopo aver accettato la licenza), `sdxl`, `sd35`. In **Provider AI → Immagini in casa** metti `http://<ip-gpu>:8188`, scegli il modello (preset o nome di un checkpoint `.safetensors`) e prova la connessione: mostra GPU e modelli presenti. FamilAI usa workflow integrati (Flux: unet+dual clip+vae; SDXL/SD3.5: checkpoint) oppure un tuo workflow API JSON con segnaposto `{{PROMPT}} {{NEGATIVE}} {{WIDTH}} {{HEIGHT}} {{SEED}} {{STEPS}}` (`COMFYUI_WORKFLOW`). Sul **Mac** (Apple Silicon, 16-24 GB) niente Docker: `extras/comfyui/install-mac.sh` installa ComfyUI nativo con Metal e scarica Flux.1 schnell quantizzato GGUF Q8 (`--dev` per Flux dev Q6, `--sdxl` per SDXL); si avvia con `~/ComfyUI/start.sh`, indirizzo per FamilAI `http://host.docker.internal:8188`, modello `flux-schnell-gguf`. Con ComfyUI attivo le immagini costano zero, le generano anche i modelli locali e il router non le manda più al cloud.

### Ricerca web in casa (SearXNG)
Nel compose c'è **SearXNG**, metamotore open source che aggrega Google, Bing, DuckDuckGo, Brave e Wikipedia via API JSON, senza chiavi e senza tracciamento, raggiungibile solo dal backend. Con `SEARXNG_URL` impostato (default nel compose) è il primo motore usato dal tool `web_search`: il backend prende i risultati, legge le prime pagine e, se c'è un modello locale, ne estrae i punti chiave con le fonti, così anche Qwen/gpt-oss in locale fanno ricerche aggiornate e il router Auto non deve più inoltrarle al cloud. Con Claude in chat resta disponibile la sua ricerca nativa (impostazione dedicata). Ricerca sicura forzata per i bambini.

### Compattazione delle chat lunghe
Quando la cronologia di una chat supera il budget (`CONTEXT_BUDGET_TOKENS`, 24k token stimati), il backend riassume la parte vecchia con un modello economico in un **riassunto cumulativo** e archivia i messaggi integrali in un file virtuale "Cronologia chat" indicizzato dal RAG della conversazione. Al modello arrivano riassunto + ultimi ~8k token; i dettagli vecchi restano raggiungibili tramite il recupero automatico e il tool `search_documents`. Vale per tutti i provider, locali compresi: il RAG e' nel backend, il modello riceve i passaggi gia' nel prompt.

### Memoria di famiglia (RAG con "firewall" e approvazione)
Ogni pochi messaggi un modello economico (locale se c'è) estrae dalle chat i **fatti durevoli** utili in futuro (membri, scuola, preferenze, hobby, progetti, casa, regole). Ogni voce passa un **firewall** a due livelli: istruzioni al modello più regole fisse che scartano dati sanitari, religione/politica, finanze con cifre, credenziali, numeri di documenti e cose temporanee; i duplicati vengono fusi. Le voci finiscono in **Famiglia → Memoria → Da approvare**: solo quelle approvate entrano nel prompt, scegliendo a ogni messaggio le più pertinenti (embedding o parole chiave) più quelle "fissate". Opzioni in Altre impostazioni: attiva/disattiva, approvazione automatica delle voci sicure degli adulti (i bambini restano sempre in coda), modello di estrazione. In chat: "ricordati che…" e "dimentica…" (tool `remember`/`forget`); in Impostazioni ognuno vede e può cancellare ciò che lo riguarda. "Analizza le chat passate" riempie la memoria dallo storico.

### Consultare un altro modello dalla chat (`ask_model`)
Gli adulti possono chiedere in linguaggio naturale di coinvolgere un altro provider ("chiedi a Gemini cosa ne pensa", "fai rispondere anche GPT e confronta"): il modello in uso chiama il tool `ask_model`, che passa la richiesta (con gli ultimi messaggi come contesto) all'altro provider e riporta la risposta indicando chi l'ha data. Il consumo viene registrato sul provider consultato. Il tool si disattiva per utente dalla pagina Famiglia; i bambini non lo hanno (il loro provider è fissato dal genitore). Per cambiare il modello che risponde d'ora in poi resta il menu in alto nella chat.

### Prompt caching (costi)
Il prompt di sistema e i tool sono costruiti in modo da restare **identici** tra una richiesta e l'altra (data/ora ed estratti RAG vanno in una parte separata, dopo il punto di cache). Con Claude vengono inviati i `cache_control` espliciti (fine del system e ultimo messaggio utente: cache incrementale della conversazione, letture al 10% del prezzo); OpenAI e Gemini 2.5 mettono in cache automaticamente il prefisso identico (25–50%). Nella pagina **Costi** ogni provider mostra la quota di input servita dalla cache e il risparmio stimato; i token in cache sono conteggiati a parte nel log di utilizzo.

### Voce naturale (TTS)
Con una chiave OpenAI (o Gemini) FamilAI legge i messaggi ad alta voce (pulsante 🔊 sotto ogni risposta) e mette a disposizione dei giochi/app negli artifact la funzione `FamilAI.speak(testo)`, che Claude usa al posto della sintesi vocale del browser: voci umane, in italiano, con stile configurabile in **Provider AI → Altre impostazioni** (provider, voce, istruzioni di stile). L'audio è messo in cache in `data/tts/`, quindi una frase già generata non costa più nulla. Endpoint: `POST /api/tts {text, voice?, style?}`.

### Email: inviti, password dimenticata, codice al posto della passkey
In **Famiglia → Provider AI → Email** puoi **collegare un account Google** (OAuth, scope `gmail.send`: nessuna password per le app; usa il client della scheda "Accesso con Google" e richiede anche l'URI `/api/admin/email/google/callback`; finché l'app Google è in modalità Test aggiungi l'account fra gli utenti di test) oppure configurare l'SMTP classico (pulsante "Preimposta Gmail": `smtp.gmail.com:587` STARTTLS; utente = indirizzo Gmail; password = *password per le app* di Google) e verifica con "Invia email di prova". Da quel momento:
- creando un adulto senza password parte un **invito** con link (valido 48 h) per scegliere la password (pulsante "✉️ Invito" per reinviarlo);
- al login compare **"Password dimenticata?"**: codice a 6 cifre via email (10 min, 5 tentativi) e nuova password;
- se `EMAIL_MFA_FALLBACK=true`, al passo passkey si può chiedere **un codice via email** come secondo fattore alternativo (comodo contro i blocchi, leggermente meno sicuro della sola passkey: disattivabile dal pannello).

### Accesso con Google
In **Famiglia → Provider AI → Accesso con Google** inserisci Client ID e secret di un client OAuth "Applicazione web" creato su console.cloud.google.com (API e servizi → Credenziali), con URI di reindirizzamento `https://<PUBLIC_HOST>/api/auth/google/callback` (in dev `http://localhost:8080/api/auth/google/callback`). Sulla schermata di login compare "Accedi con Google": entra chi ha un account Google con la **stessa email** di un membro adulto creato dall'amministratore (nessuna auto-registrazione). L'accesso Google vale come secondo fattore, quindi non richiede la passkey. È del tutto separato dall'account Gmail usato per l'SMTP.

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
