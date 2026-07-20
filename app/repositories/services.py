"""Data access for services offered at an active location."""

from typing import Any

from supabase import Client


class ServiceRepository:
    """Read services through the server-side Supabase client."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list_active_for_location(self, location_id: str) -> list[dict[str, Any]]:
        """Return active services for a location, ordered by name."""

        response = (
            self._client.table("services")
            .select("*")
            .eq("location_id", location_id)
            .eq("is_active", True)
            .order("name")
            .execute()
        )
        return response.data or []
