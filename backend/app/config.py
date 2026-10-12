from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base
    data_dir: Path = Path("./data")
    database_url: str = "sqlite+aiosqlite:///./data/familai.db"
    secret_key: str = "dev-secret-change-me"
    log_level: str = "info"
    cookie_secure: bool = True

    # Esposizione / WebAuthn
    public_host: str = "localhost"
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "FamilAI"
    webauthn_origin: str = "http://localhost:5173"
    require_mfa_for_adults: bool = True
    session_hours_adult: int = 168
    session_hours_child: int = 12

    # Bootstrap admin
    admin_email: str = "admin@example.com"
    admin_password: str = "changeme"
    admin_name: str = "Admin"
    family_name: str = "Famiglia"

    # Provider
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_default_model: str = "claude-sonnet-4-5"
    openai_default_model: str = "gpt-4.1"
    openai_reasoning_effort: str = "auto"   # auto | none | low | medium | high (modelli OpenAI con ragionamento)
    gemini_default_model: str = "gemini-2.5-flash"
    enable_mock_provider: bool = False  # utile per test senza chiavi
    # Modello locale (Ollama). Vuoto = disabilitato. Mac: http://host.docker.internal:11434 (Ollama nativo, usa la GPU);
    # Linux con profilo compose 'ollama': http://ollama:11434
    ollama_url: str = ""
    ollama_default_model: str = "qwen3:8b"
    # Server LLM di casa con API compatibile OpenAI (vLLM, llama.cpp, LM Studio...): es. http://192.168.4.2:8000
    custom_llm_url: str = ""
    custom_llm_key: str = ""              # opzionale
    custom_llm_model: str = ""            # vuoto = primo modello esposto da /v1/models
    custom_llm_label: str = "Server LLM di casa"
    # Router "Auto": un modello locale piccolo decide se rispondere in locale o passare al cloud
    router_model: str = "qwen3:4b"        # modello locale usato per decidere (e per le risposte rapide se uguale al default)
    router_local_provider: str = "auto"   # chi risponde in locale: auto (custom se presente, altrimenti ollama) | ollama | custom
    router_cloud_provider: str = "auto"   # provider cloud a cui inoltrare: auto | anthropic | openai | gemini
    router_mode: str = "locale"           # locale (prima il locale: cloud solo su richiesta) | economico | balanced | qualita | off
    max_output_tokens: int = 32768      # lunghezza massima di UNA chiamata al modello (serve alta per app/artifact e codice)
    max_total_output_tokens: int = 256000   # oltre questo totale la risposta si ferma davvero (continuazioni automatiche incluse)
    auto_continue: str = "true"
    thinking_mode: str = "cloud"        # off | cloud (Claude/Gemini mostrano il ragionamento) | all (anche i modelli locali, piu' lenti)
    thinking_budget: int = 4096         # token di ragionamento per risposta (Claude/Gemini)         # se la risposta si interrompe per lunghezza, il backend chiede di continuare da solo

    # Tool
    web_search_provider: str = "auto"      # auto | searxng | anthropic | openai | gemini | tavily | brave
    searxng_url: str = ""                  # es. http://searxng:8080 (servizio nel compose): ricerca web in casa, senza chiavi
    web_search_read_pages: int = 3         # pagine da leggere per arricchire i risultati SearXNG (0 = solo snippet)
    web_search_summarize: str = "auto"     # auto (modello locale se c'e') | none: riassunto delle pagine lette
    web_search_model_openai: str = "gpt-4.1-mini"
    web_search_model_gemini: str = "gemini-2.5-flash"
    anthropic_native_search: str = "true"   # con Claude in chat usa il tool di ricerca nativo di Anthropic
    tavily_api_key: str = ""
    brave_api_key: str = ""
    image_provider: str = "auto"          # auto | comfyui | openai | gemini  (auto = ComfyUI in casa se c'e', poi OpenAI, poi Gemini)
    comfyui_url: str = ""                 # es. http://192.168.4.2:8188 (vedi extras/comfyui)
    comfyui_model: str = "flux-dev"       # flux-dev | flux-schnell | sdxl | sd35 | nome di un checkpoint .safetensors
    comfyui_workflow: str = ""            # opzionale: percorso di un workflow API JSON personalizzato con segnaposto
    comfyui_timeout: int = 1800           # secondi di attesa massima per un'immagine (Mac/GPU piccole: la prima e' lenta)
    video_provider: str = "auto"          # auto | comfyui | gemini (auto = ComfyUI se ha il modello video, altrimenti Veo)
    comfyui_video_model: str = "wan22-5b"
    comfyui_video_size: str = "832x480"   # Mac: 832x480; L40S: 1280x704
    comfyui_video_frames: int = 49        # 4n+1; 49 frame = 2 s a 24 fps, 121 = 5 s
    comfyui_video_timeout: int = 5400
    image_model: str = "gpt-image-1"
    gemini_image_model: str = "imagen-4.0-generate-001"
    video_model: str = "veo-3.0-generate-001"
    # Voce (sintesi vocale naturale per lettura messaggi e giochi/app negli artifact)
    tts_provider: str = "auto"            # auto | openai | gemini | none
    tts_model_openai: str = "gpt-4o-mini-tts"
    tts_voice_openai: str = "nova"
    tts_model_gemini: str = "gemini-2.5-flash-preview-tts"
    tts_voice_gemini: str = "Kore"
    tts_style: str = ""                   # istruzioni di stile (vuoto = default: voce calda e chiara per bambini)
    child_moderation: bool = True
    mcp_config_path: Path = Path("mcp_servers.json")
    wordcraft_host: str = ""          # host:porta del container WordCraft (es. wordcraft:7982): documenti Word/PDF via MCP
    wordcraft_web: bool = False       # editor WordCraft nel browser servito su /wordcraft/ (container wordcraft-web)

    # Email (SMTP) — configurabile dal pannello
    smtp_host: str = ""
    smtp_port: str = ""               # vuoto = 587 (starttls) / 465 (ssl)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "FamilAI"
    smtp_security: str = "starttls"   # starttls | ssl | none
    email_mfa_fallback: str = "true"  # consente il codice via email al posto della passkey al login
    mail_transport: str = "auto"      # auto | gmail_oauth | smtp  (auto = Gmail OAuth se collegato, altrimenti SMTP)
    gmail_oauth_refresh_token: str = ""   # ottenuto con "Collega account Google" (cifrato nel DB)
    gmail_oauth_email: str = ""

    # Accesso con Google (OAuth client 'Web application' su console.cloud.google.com)
    google_client_id: str = ""
    google_client_secret: str = ""

    # Costi e budget (pannello Costi)
    pricing_json: str = ""            # override del listino prezzi (JSON), vedi services/costs.py
    budget_anthropic: str = ""        # budget mensile in USD (vuoto = nessun budget)
    budget_openai: str = ""
    budget_gemini: str = ""
    anthropic_admin_key: str = ""     # chiave Admin (sk-ant-admin…) per leggere la spesa reale
    openai_admin_key: str = ""        # Admin API key OpenAI per leggere la spesa reale

    # Sandbox esecuzione codice (servizio separato nel compose; vuoto = esecuzione disabilitata)
    sandbox_url: str = ""
    sandbox_timeout: int = 60
    artifact_max_history: int = 20

    # Compattazione delle chat lunghe: riassunto cumulativo + archivio cercabile (RAG) dei messaggi vecchi
    compaction_enabled: str = "true"
    context_budget_tokens: int = 24000    # oltre questa stima di token di cronologia si compatta
    context_keep_tokens: int = 8000       # messaggi recenti da tenere integrali

    # Memoria di famiglia (fatti estratti dalle chat, con approvazione)
    memory_enabled: str = "true"
    memory_auto_approve: str = "false"    # true = le voci sicure (confidenza alta, autore adulto) entrano senza approvazione
    memory_model: str = "auto"            # modello per l'estrazione: auto | provider/modello (es. openai/gpt-4.1-mini)
    memory_top_k: int = 8

    # RAG (ricerca semantica sui file di progetto)
    embedding_provider: str = "auto"      # auto | ollama | openai | gemini | none (auto = Ollama se c'e', poi OpenAI, poi Gemini)
    embedding_model: str = ""             # vuoto = default del provider
    rag_chunk_chars: int = 2500           # dimensione frammenti (caratteri)
    rag_chunk_overlap: int = 300
    rag_top_k: int = 6                    # frammenti inseriti automaticamente nel contesto
    rag_inline_max_chars: int = 15000     # documenti più piccoli vengono inseriti interi

    @property
    def uploads_dir(self) -> Path:
        p = self.data_dir / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def generated_dir(self) -> Path:
        p = self.data_dir / "generated"
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
