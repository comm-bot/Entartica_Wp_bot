"""Health-check endpoint."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings


router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response returned when the service is available."""

    status: Literal["ok"]
    app_revision: str
    router_revision: str
    started_at: str
    process_started_at: str
    environment: str
    raipur_langgraph_enabled: bool
    raipur_langgraph_comparison_mode: bool
    active_conversation_engine: Literal["legacy", "langgraph"]
    coimbatore_langgraph_enabled: bool
    active_coimbatore_engine: Literal["legacy", "langgraph"]


_STARTED_AT = datetime.now(timezone.utc).isoformat()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Confirm that the HTTP service is running."""

    settings = get_settings()
    return HealthResponse(
        status="ok",
        app_revision=settings.app_revision,
        router_revision=settings.router_revision,
        started_at=_STARTED_AT,
        process_started_at=_STARTED_AT,
        environment=settings.app_env,
        raipur_langgraph_enabled=settings.raipur_langgraph_enabled,
        raipur_langgraph_comparison_mode=settings.raipur_langgraph_comparison_mode,
        active_conversation_engine="langgraph" if settings.raipur_langgraph_enabled else "legacy",
        coimbatore_langgraph_enabled=settings.coimbatore_langgraph_enabled,
        active_coimbatore_engine="langgraph" if settings.coimbatore_langgraph_enabled else "legacy",
    )
