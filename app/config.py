"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the API."""

    app_name: str = "Entartica WhatsApp Chatbot"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    supabase_url: str | None = None
    supabase_secret_key: SecretStr | None = None
    exotel_account_sid: str | None = None
    exotel_api_token: SecretStr | None = None
    exotel_signature_validation_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""

    return Settings()
