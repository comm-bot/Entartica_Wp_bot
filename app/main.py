"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.exotel_webhook import router as exotel_webhook_router
from app.api.health import router as health_router
from app.api.status_webhook import router as status_webhook_router
from app.config import get_settings
from app.integrations.supabase import get_supabase_client, log_startup_readiness


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.include_router(health_router)
    app.include_router(exotel_webhook_router)
    app.include_router(status_webhook_router)

    @app.on_event("startup")
    async def verify_supabase_readiness() -> None:
        """Fail visibly but safely before webhook testing when auth/access is bad."""
        try:
            log_startup_readiness(get_supabase_client())
        except Exception:
            # The health endpoint stays available; the safe log above or this
            # category tells operators to repair configuration before testing.
            import logging
            logging.getLogger("uvicorn.error").error("supabase_startup_readiness ready=false error_category=client_initialization_failure")
    return app


app = create_app()
