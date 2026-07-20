"""Tests for environment-backed application configuration."""

from app.config import Settings


def test_settings_reads_supabase_secret_key(monkeypatch) -> None:
    """The server-side Supabase key uses the current environment variable."""

    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-secret-key")

    settings = Settings()

    assert settings.supabase_secret_key is not None
    assert settings.supabase_secret_key.get_secret_value() == "test-secret-key"
