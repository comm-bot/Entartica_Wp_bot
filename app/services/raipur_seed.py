"""Validation and database mapping for approved Raipur seed data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SeedValidationResult:
    """Non-sensitive validation outcome for the Raipur seed files."""

    errors: tuple[str, ...]
    placeholders: tuple[str, ...]
    service_count: int

    @property
    def is_valid(self) -> bool:
        return not self.errors


def load_seed_json(path: Path) -> dict[str, Any]:
    """Load a JSON object without logging its potentially sensitive contents."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Seed file must contain a JSON object.")
    return data


def validate_raipur_seed(location: dict[str, Any], services_document: dict[str, Any]) -> SeedValidationResult:
    """Validate only approved, location-scoped seed structure."""

    errors: list[str] = []
    placeholders: list[str] = []
    if location.get("code") != "raipur":
        errors.append("location_code_must_be_raipur")
    if location.get("city") != "Raipur":
        errors.append("location_city_must_be_raipur")
    if location.get("state") != "Chhattisgarh":
        errors.append("location_state_must_be_chhattisgarh")
    if location.get("status") != "active":
        errors.append("location_status_must_be_active")
    for key in ("booking_enquiry_enabled", "requires_human_confirmation", "requires_human_quotation"):
        if location.get(key) is not True:
            errors.append(f"{key}_must_be_true")
    for key, value in location.items():
        if isinstance(value, str) and value.strip().upper() == "TO_BE_APPROVED":
            placeholders.append(key)
        if any(marker in key.lower() for marker in ("price", "rate", "cost")) and value not in (None, "", "TO_BE_APPROVED"):
            errors.append("unapproved_price_field")

    if services_document.get("location_code") != "raipur":
        errors.append("services_location_code_must_be_raipur")
    services = services_document.get("services")
    if not isinstance(services, list):
        errors.append("services_must_be_a_list")
        services = []
    codes: set[str] = set()
    for service in services:
        if not isinstance(service, dict):
            errors.append("service_must_be_an_object")
            continue
        if service.get("location_code", "raipur") != "raipur":
            errors.append("service_must_belong_to_raipur")
        code = service.get("code")
        name = service.get("name")
        if not isinstance(code, str) or not code.strip():
            errors.append("service_code_must_not_be_empty")
        elif code.lower() in codes:
            errors.append("duplicate_service_code")
        else:
            codes.add(code.lower())
        if not isinstance(name, str) or not name.strip():
            errors.append("service_name_must_not_be_empty")
        for flag in ("booking_enquiry_allowed", "requires_human_quotation", "requires_human_confirmation"):
            if service.get(flag) is not True:
                errors.append(f"service_{flag}_must_be_true")
        for key, value in service.items():
            if any(marker in key.lower() for marker in ("price", "rate", "cost")) and value not in (None, "", "TO_BE_APPROVED"):
                errors.append("unapproved_price_field")
            if isinstance(value, str) and value.strip().upper() == "TO_BE_APPROVED":
                placeholders.append(f"service_{key}")
    return SeedValidationResult(tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(placeholders)), len(services))


def location_database_row(location: dict[str, Any]) -> dict[str, Any]:
    """Map approved seed fields to the existing locations schema."""

    return {
        "slug": "raipur",
        "name": location["name"],
        "city": "Raipur",
        "state": "Chhattisgarh",
        "country": location.get("country", "India"),
        "is_active": True,
        "address": location.get("address"),
        "metadata": {
            "location_name": location["name"],
            "address_line": location.get("address_line") or location.get("address"),
            "landmark": location.get("landmark"),
            "maps_url": location.get("maps_url"),
            "booking_enquiry_enabled": True,
            "requires_human_confirmation": True,
            "requires_human_quotation": True,
            "contact_reference": location.get("contact_reference"),
            "operating_hours": location.get("operating_hours"),
        },
    }


def service_database_row(service: dict[str, Any], location_id: str) -> dict[str, Any]:
    """Map an approved service to the existing services schema."""

    return {
        "location_id": location_id,
        "slug": service["code"].strip().lower(),
        "name": service["name"].strip(),
        "description": service.get("short_description") or None,
        "is_active": service.get("active") is True,
        "metadata": {
            "category": service.get("category") or None,
            "booking_enquiry_allowed": True,
            "requires_human_quotation": True,
            "requires_human_confirmation": True,
        },
    }
