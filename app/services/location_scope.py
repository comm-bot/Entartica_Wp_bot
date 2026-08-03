"""Data-driven location scope for the single-location MVP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.config import Settings
from app.repositories.locations import LocationRepository


LocationScopeStatus = Literal[
    "enabled", "unsupported_location", "location_not_configured", "human_handover_required"
]


@dataclass(frozen=True)
class LocationScopeResult:
    """Safe internal outcome; it contains no customer message content."""

    status: LocationScopeStatus
    location: dict[str, Any] | None = None
    requested_location: str | None = None
    available_location: str | None = None
    human_handover_required: bool = False


class LocationScopeService:
    """Resolve only explicit, active locations configured for this MVP."""

    def __init__(self, settings: Settings, repository: LocationRepository) -> None:
        self._settings = settings
        self._repository = repository

    def get_default_location(self) -> LocationScopeResult:
        """Return the configured default only when it is active in Supabase."""

        if not self._settings.mvp_location_configuration_is_valid():
            return LocationScopeResult("location_not_configured")
        location = self._repository.get_default_enabled_location()
        if location is None:
            return LocationScopeResult("human_handover_required", human_handover_required=True)
        return LocationScopeResult("enabled", location=location, available_location=location.get("name"))

    def resolve_requested_location(self, requested_location: str) -> LocationScopeResult:
        """Allow configured locations only; other requests require a human handover."""

        default = self.get_default_location()
        if default.status != "enabled":
            return default
        normalized = _normalize_requested_location(requested_location)
        if normalized not in self._settings.mvp_enabled_location_codes:
            return LocationScopeResult(
                "unsupported_location",
                requested_location=normalized,
                available_location=default.available_location,
                human_handover_required=True,
            )
        location = self._repository.get_location_by_code(normalized)
        if location is None:
            return LocationScopeResult("human_handover_required", human_handover_required=True)
        return LocationScopeResult("enabled", location=location, available_location=location.get("name"))

    def require_enabled_location_id(self, location_id: str | None) -> str:
        """Guard future booking-enquiry writes against null or unsupported locations."""

        if not location_id or self._repository.ensure_location_is_enabled(location_id) is None:
            raise ValueError("A valid enabled location is required for an MVP booking enquiry.")
        return location_id


def _normalize_requested_location(value: str) -> str:
    """Normalize a location label without retaining arbitrary user text."""

    return "".join(character for character in value.strip().lower() if character.isalnum() or character == "-")[:64]
