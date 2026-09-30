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
    gemini_default_model: str = "gemini-2.5-flash"
    enable_mock_provider: bool = False  # utile per test senza chiavi

    # Tool
    web_search_provider: str = "tavily"
    tavily_api_key: str = ""
    brave_api_key: str = ""
    image_model: str = "gpt-image-1"
    video_model: str = "veo-3.0-generate-001"
    child_moderation: bool = True
    mcp_config_path: Path = Path("mcp_servers.json")

    # Sandbox esecuzione codice (servizio separato nel compose; vuoto = esecuzione disabilitata)
    sandbox_url: str = ""
    sandbox_timeout: int = 60
    artifact_max_history: int = 20

    # RAG (ricerca semantica sui file di progetto)
    embedding_provider: str = "auto"      # auto | openai | gemini | none (none = solo ricerca per parole chiave)
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
