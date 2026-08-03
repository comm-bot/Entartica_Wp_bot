"""Data access for active Entartica locations."""

from collections.abc import Iterable
from typing import Any

from supabase import Client


class LocationRepository:
    """Read locations through the server-side Supabase client."""

    def __init__(
        self,
        client: Client,
        *,
        default_location_code: str | None = None,
        enabled_location_codes: Iterable[str] = (),
    ) -> None:
        self._client = client
        self._default_location_code = _normalize_code(default_location_code)
        self._enabled_location_codes = tuple(
            dict.fromkeys(code for value in enabled_location_codes if (code := _normalize_code(value)))
        )

    def list_active(self) -> list[dict[str, Any]]:
        """Return active locations ordered by name."""

        response = (
            self._client.table("locations")
            .select("*")
            .eq("is_active", True)
            .order("name")
            .execute()
        )
        return _response_rows(response)

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
        return _response_row(response)

    def get_location_by_code(self, code: str) -> dict[str, Any] | None:
        """Return one active location using its normalized database slug."""

        normalized = _normalize_code(code)
        if normalized is None:
            return None
        response = (
            self._client.table("locations")
            .select("*")
            .eq("slug", normalized)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        return _response_row(response)

    def get_default_enabled_location(self) -> dict[str, Any] | None:
        """Return the configured default location only when it is enabled."""

        if (
            self._default_location_code is None
            or self._default_location_code not in self._enabled_location_codes
        ):
            return None
        return self.get_location_by_code(self._default_location_code)

    def list_enabled_locations(self) -> list[dict[str, Any]]:
        """Return only active locations within the configured MVP scope."""

        if not self._enabled_location_codes:
            return []
        response = (
            self._client.table("locations")
            .select("*")
            .eq("is_active", True)
            .in_("slug", list(self._enabled_location_codes))
            .order("name")
            .execute()
        )
        return _response_rows(response)

    def ensure_location_is_enabled(self, location_id: str) -> dict[str, Any] | None:
        """Return an active configured location by ID, otherwise ``None``."""

        if not self._enabled_location_codes:
            return None
        response = (
            self._client.table("locations")
            .select("*")
            .eq("id", location_id)
            .eq("is_active", True)
            .in_("slug", list(self._enabled_location_codes))
            .maybe_single()
            .execute()
        )
        return _response_row(response)


def _normalize_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _response_rows(response: object) -> list[dict[str, Any]]:
    data = getattr(response, "data", None) if response is not None else None
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _response_row(response: object) -> dict[str, Any] | None:
    rows = _response_rows(response)
    return rows[0] if rows else None
