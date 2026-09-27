from pathlib import Path

from app.core.config import Settings


def test_settings_normalize_database_and_fallback_models():
    settings = Settings(
        openrouter_api_key="secret",
        database_url="postgresql://user:pass@localhost/db",
        analyzer_fallback_models="openai/gpt-5-mini, anthropic/claude-sonnet-4.5",
        analyzer_storage_root=Path("test-data"),
    )

    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.analyzer_fallback_models == [
        "openai/gpt-5-mini",
        "anthropic/claude-sonnet-4.5",
    ]
