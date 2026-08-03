"""Server-side Supabase client factory."""

from functools import lru_cache
import logging

from supabase import Client, create_client

from app.config import get_settings


logger = logging.getLogger("uvicorn.error")


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


def log_startup_readiness(client: Client) -> bool:
    """Read minimal table metadata once and emit only safe readiness fields."""
    tables = ("customers", "conversations", "messages", "knowledge_documents")
    try:
        for table in tables:
            client.table(table).select("id").limit(1).execute()
    except Exception as error:
        logger.error(
            "supabase_startup_readiness ready=false error_category=%s database_code=%s",
            "authentication_failure" if getattr(error, "code", None) == "PGRST303" else "read_access_failure",
            getattr(error, "code", None),
        )
        return False
    logger.info("supabase_startup_readiness ready=true required_tables_accessible=true")
    return True
