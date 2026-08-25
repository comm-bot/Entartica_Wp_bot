"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.api.exotel_webhook import get_raipur_inbound_orchestrator, router as exotel_webhook_router
from app.api.health import router as health_router
from app.api.coimbatore_payments import router as coimbatore_payments_router
from app.api.coimbatore_customer_details import router as coimbatore_customer_details_router
from app.api.status_webhook import router as status_webhook_router
from app.api.razorpay_webhook import router as razorpay_webhook_router
from app.config import get_settings
from app.integrations.supabase import get_supabase_client, log_startup_readiness
from app.services.latency import configure_latency_logging


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    settings = get_settings()
    for handler in logging.getLogger("uvicorn.error").handlers:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s.%(msecs)03d %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
        ))
    configure_latency_logging()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.include_router(health_router)
    app.include_router(coimbatore_payments_router)
    app.include_router(coimbatore_customer_details_router)
    app.include_router(exotel_webhook_router)
    app.include_router(status_webhook_router)
    app.include_router(razorpay_webhook_router)

    @app.on_event("startup")
    async def verify_supabase_readiness() -> None:
        """Fail visibly but safely before webhook testing when auth/access is bad."""
        langgraph_enabled = bool(settings.raipur_langgraph_enabled)
        logging.getLogger("uvicorn.error").info(
            "coimbatore_conversation_engine_selected engine=%s feature_flag_value=%s checkpointer=false",
            "langgraph" if settings.coimbatore_langgraph_enabled else "legacy",
            settings.coimbatore_langgraph_enabled,
        )
        if settings.razorpay_enabled:
            valid_test_config = bool(
                settings.razorpay_mode == "test"
                and isinstance(settings.razorpay_key_id, str)
                and settings.razorpay_key_id.startswith("rzp_test_")
                and settings.razorpay_key_secret
                and settings.razorpay_webhook_secret
            )
            if not valid_test_config:
                logging.getLogger("uvicorn.error").error(
                    "razorpay_startup_readiness ready=false mode=%s error_category=test_configuration_invalid",
                    settings.razorpay_mode,
                )
            else:
                logging.getLogger("uvicorn.error").info("razorpay_startup_readiness ready=true mode=test")
        logging.getLogger("uvicorn.error").info(
            "raipur_conversation_engine_selected engine=%s feature_flag_value=%s "
            "compatibility_mode=%s environment=%s",
            "langgraph" if langgraph_enabled else "legacy",
            langgraph_enabled,
            not langgraph_enabled,
            settings.app_env,
        )
        try:
            ready = log_startup_readiness(get_supabase_client())
            if ready and settings.raipur_inbound_orchestrator_enabled:
                await run_in_threadpool(get_raipur_inbound_orchestrator)
                logging.getLogger("uvicorn.error").info(
                    "active_orchestrator_ready active_location=%s active_product=%s cached=true",
                    settings.active_location, settings.active_product,
                )
        except Exception:
            # The health endpoint stays available; the safe log above or this
            # category tells operators to repair configuration before testing.
            logging.getLogger("uvicorn.error").error("supabase_startup_readiness ready=false error_category=client_initialization_failure")
    return app


app = create_app()
