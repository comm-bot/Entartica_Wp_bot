"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.exotel_webhook import router as exotel_webhook_router
from app.api.health import router as health_router
from app.api.status_webhook import router as status_webhook_router
from app.config import get_settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.include_router(health_router)
    app.include_router(exotel_webhook_router)
    app.include_router(status_webhook_router)
    return app


app = create_app()
