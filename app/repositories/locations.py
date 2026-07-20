"""Data access for active Entartica locations."""

from typing import Any

from supabase import Client


class LocationRepository:
    """Read locations through the server-side Supabase client."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list_active(self) -> list[dict[str, Any]]:
        """Return active locations ordered by name."""

        response = (
            self._client.table("locations")
            .select("*")
            .eq("is_active", True)
            .order("name")
            .execute()
        )
        return response.data or []

    def get_active(self, location_id: str) -> dict[str, Any] | None:
        """Return one active location, or ``None`` when it is unavailable."""

        response = (
            self._client.table("locations")
            .select("*")
            .eq("id", location_id)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        return response.data
