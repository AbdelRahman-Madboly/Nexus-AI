"""
api/config.py
=============
Pydantic-settings singleton for Nexus-AI.

All configuration is loaded from .env (or environment variables).
Every other module imports settings via:
    from api.config import get_settings

Rules:
  - Zero hardcoded values in this file or anywhere else.
  - PRIVACY_MODE=true forces ALL LLM calls to Ollama via llm_router.py.
  - LLM backend is switchable with a single .env change — zero code changes.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central settings class.  All fields map 1-to-1 to .env.example.
    pydantic-settings reads from the .env file automatically.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,   # LLM_BACKEND and llm_backend both work
        extra="ignore",         # silently ignore unknown env vars
    )

    # -------------------------------------------------------------------------
    # LLM Backend Selection
    # -------------------------------------------------------------------------
    llm_backend: Literal["openai", "claude", "gemini", "ollama"] = Field(
        default="ollama",
        description="Which LLM provider to use.  Overridden by PRIVACY_MODE.",
    )
    privacy_mode: bool = Field(
        default=False,
        description="Force ALL LLM calls to Ollama.  Zero data leaves the machine.",
    )

    # -------------------------------------------------------------------------
    # OpenAI
    # -------------------------------------------------------------------------
    openai_api_key: str = Field(default="", description="OpenAI API key.")
    openai_model: str = Field(default="gpt-4o", description="OpenAI model name.")

    # -------------------------------------------------------------------------
    # Anthropic / Claude
    # -------------------------------------------------------------------------
    anthropic_api_key: str = Field(default="", description="Anthropic API key.")
    claude_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model string.",
    )

    # -------------------------------------------------------------------------
    # Google Gemini
    # -------------------------------------------------------------------------
    gemini_api_key: str = Field(default="", description="Google Gemini API key.")
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model name.",
    )

    # -------------------------------------------------------------------------
    # Ollama (local / privacy backend)
    # -------------------------------------------------------------------------
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL.  In Docker Compose: http://nexus-ollama:11434",
    )
    ollama_model: str = Field(
        default="llama3.2:3b",
        description="Ollama chat/completion model.",
    )
    ollama_embed_model: str = Field(
        default="nomic-embed-text",
        description="Ollama embedding model — required for RAG.",
    )

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    database_url: str = Field(
        default="sqlite:///./nexus.db",
        description="SQLite file path.  WAL mode is enabled by database.py.",
    )

    # -------------------------------------------------------------------------
    # ChromaDB
    # -------------------------------------------------------------------------
    chroma_host: str = Field(
        default="localhost",
        description="ChromaDB host.  In Docker Compose: nexus-chroma",
    )
    chroma_port: int = Field(default=8001, description="ChromaDB HTTP port.")

    # -------------------------------------------------------------------------
    # Auth
    # -------------------------------------------------------------------------
    jwt_secret: str = Field(
        default="change-me-to-a-random-32-char-string-in-production",
        description="JWT signing secret.  MUST be changed in production.",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm.")

    # -------------------------------------------------------------------------
    # n8n Automation
    # -------------------------------------------------------------------------
    n8n_webhook_url: str = Field(
        default="http://localhost:5678",
        description="Base URL for n8n webhook calls.",
    )

    # -------------------------------------------------------------------------
    # OpenClaw Gateway
    # -------------------------------------------------------------------------
    openclaw_model: str = Field(
        default="ollama/llama3.2:3b",
        description="Model string passed to OpenClaw.  Prefixed with provider.",
    )
    openclaw_cloud_fallback: bool = Field(
        default=False,
        description="Allow OpenClaw to fall back to cloud LLM when Ollama is slow.",
    )
    openclaw_nexus_api_url: str = Field(
        default="http://localhost:8000",
        description="URL that OpenClaw uses to call back into the Nexus FastAPI.",
    )

    # Telegram
    telegram_bot_token: str = Field(default="", description="Telegram @BotFather token.")

    # Twilio / WhatsApp
    twilio_account_sid: str = Field(default="", description="Twilio Account SID.")
    twilio_auth_token: str = Field(default="", description="Twilio Auth Token.")
    twilio_phone_number: str = Field(default="", description="Twilio WhatsApp-enabled number.")

    # Slack
    slack_bot_token: str = Field(default="", description="Slack bot token (xoxb-…).")
    slack_app_token: str = Field(default="", description="Slack app token (xapp-…).")

    # -------------------------------------------------------------------------
    # FastAPI Server
    # -------------------------------------------------------------------------
    api_host: str = Field(default="0.0.0.0", description="Uvicorn bind host.")
    api_port: int = Field(default=8000, description="Uvicorn bind port.")
    debug: bool = Field(default=False, description="FastAPI debug / reload mode.")

    # -------------------------------------------------------------------------
    # Computed helpers (not env vars — derived at runtime)
    # -------------------------------------------------------------------------
    @property
    def effective_llm_backend(self) -> str:
        """
        The backend that llm_router.py should actually use.
        PRIVACY_MODE always wins — returns 'ollama' regardless of llm_backend.
        """
        if self.privacy_mode:
            return "ollama"
        return self.llm_backend

    @property
    def sqlite_db_path(self) -> str:
        """
        Extract the file path portion from the DATABASE_URL string.
        'sqlite:///./nexus.db'  →  './nexus.db'
        """
        return self.database_url.replace("sqlite:///", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    lru_cache(maxsize=1) ensures the .env file is parsed exactly once per
    process, regardless of how many modules call get_settings().

    Usage:
        from api.config import get_settings
        settings = get_settings()
        print(settings.effective_llm_backend)
    """
    return Settings()