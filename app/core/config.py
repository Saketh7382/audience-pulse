from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    log_format: str = "human"

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/" "audience_intelligence"
    )
    redis_url: str = "redis://localhost:6379/0"

    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost"
    openrouter_app_name: str = "Muvion Audience Pulse"
    openrouter_timeout_seconds: float = Field(default=120, gt=0)
    openrouter_max_retries: int = Field(default=3, ge=1, le=10)
    openrouter_max_output_tokens: int = Field(default=32768, ge=256, le=65536)

    analyzer_mention_model: str = "google/gemini-3.5-flash-lite"
    analyzer_theme_model: str = "google/gemini-3.5-flash"
    analyzer_narrative_model: str = "google/gemini-3.5-flash"
    analyzer_synthesis_model: str = "google/gemini-3.5-flash"
    analyzer_fallback_models: str = "openai/gpt-5-mini"
    analyzer_mention_batch_size: int = Field(default=25, ge=1, le=200)
    analyzer_mention_batch_max_attempts: int = Field(default=3, ge=1, le=10)
    analyzer_storage_root: Path = Path(".analyzer-data")
    analyzer_version: str = "0.1.0"
    prompt_bundle_version: str = "v1"

    redis_analysis_job_stream: str = "audience:analysis:jobs"
    redis_analysis_event_stream: str = "audience:analysis:events"
    redis_analysis_consumer_group: str = "audience-pulse-workers"
    redis_analysis_dead_letter_stream: str = "audience:analysis:jobs:dead-letter"
    redis_stream_maxlen: int = Field(default=1000, gt=0)
    redis_block_ms: int = Field(default=5000, gt=0)
    redis_batch_size: int = Field(default=1, gt=0, le=100)
    redis_pending_idle_ms: int = Field(default=60000, gt=0)
    redis_max_delivery_attempts: int = Field(default=3, ge=2, le=20)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection URL")
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be a standard Python logging level")
        return normalized

    @field_validator("log_format")
    @classmethod
    def normalize_log_format(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"human", "json"}:
            raise ValueError("LOG_FORMAT must be human or json")
        return normalized

    @property
    def analyzer_fallback_model_list(self) -> list[str]:
        return [
            part.strip()
            for part in self.analyzer_fallback_models.split(",")
            if part.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
