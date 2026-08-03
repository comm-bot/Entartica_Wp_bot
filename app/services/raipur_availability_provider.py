"""Configuration-controlled construction of the local Raipur availability provider."""
from __future__ import annotations
from datetime import timedelta
from typing import Any
from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.repositories.service_availability import ServiceAvailabilityRepository
from app.services.availability import AvailabilityRequest, AvailabilityResult, SupabaseAvailabilityProvider, UnavailableAvailabilityProvider

class FailedAvailabilityProvider:
    def check(self, request: AvailabilityRequest) -> AvailabilityResult:
        del request
        return AvailabilityResult("provider_error", safe_reason_code="availability_provider_initialization_failed")

def build_raipur_availability_provider(settings: Settings | None = None, *, client: Any | None = None):
    settings = settings or Settings()
    if settings.raipur_availability_provider == "unavailable":
        return UnavailableAvailabilityProvider()
    try:
        active_client = client or get_supabase_client()
        active_client.table("service_availability").select("id").limit(0).execute()
        return SupabaseAvailabilityProvider(ServiceAvailabilityRepository(active_client), maximum_age=timedelta(minutes=settings.availability_max_age_minutes))
    except Exception:
        return FailedAvailabilityProvider()
