"""Data access for services offered at an active location."""

from typing import Any

from supabase import Client

from app.services.raipur_services import normalize_service_text
from app.services.latency import latency_counter


class ServiceRepository:
    """Read services through the server-side Supabase client."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list_active_for_location(self, location_id: str) -> list[dict[str, Any]]:
        """Return active services for a location, ordered by name."""

        latency_counter("supabase_reads")
        response = (
            self._client.table("services")
            .select("*")
            .eq("location_id", location_id)
            .eq("is_active", True)
            .order("name")
            .execute()
        )
        data = getattr(response, "data", None) if response is not None else None
        if isinstance(data, list):
            return [service for service in data if isinstance(service, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    def get_active_by_slug(self, location_id: str, slug: str) -> dict[str, Any] | None:
        """Return one active service by its per-location slug, or no match."""

        response = (
            self._client.table("services").select("*").eq("location_id", location_id)
            .eq("slug", slug.strip().casefold()).eq("is_active", True).maybe_single().execute()
        )
        data = getattr(response, "data", None) if response is not None else None
        return data if isinstance(data, dict) else None

    def find_active_by_customer_text(self, location_id: str, customer_text: object) -> dict[str, Any] | None:
        """Find an exact normalized active name or slug; ambiguity never guesses."""

        normalized = normalize_service_text(customer_text)
        if normalized is None:
            return None
        matches = [
            service for service in self.list_active_for_location(location_id)
            if normalize_service_text(service.get("name")) == normalized
            or normalize_service_text(service.get("slug")) == normalized
        ]
        return matches[0] if len(matches) == 1 else None

    def list_active_by_ids(self, service_ids: list[str]) -> list[dict[str, Any]]:
        """Return active service names for batched local sales-report linking."""

        if not service_ids:
            return []
        response = self._client.table("services").select("id,name").in_("id", service_ids).eq("is_active", True).execute()
        data = getattr(response, "data", None) if response is not None else None
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
