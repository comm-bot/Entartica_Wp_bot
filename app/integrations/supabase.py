"""Server-side Supabase client factory."""

from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def get_supabase_client() -> Client:
    """Create the configured server-side Supabase client."""

    settings = get_settings()
    if settings.supabase_url is None or settings.supabase_secret_key is None:
        raise RuntimeError("Supabase server-side configuration is required.")

    return create_client(
        settings.supabase_url,
        settings.supabase_secret_key.get_secret_value(),
    )
