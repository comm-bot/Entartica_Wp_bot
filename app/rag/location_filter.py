"""Location metadata rules for future knowledge ingestion and retrieval."""

from __future__ import annotations

from typing import Any


def build_location_metadata(*, location_code: str, location_id: str, document_category: str) -> dict[str, str]:
    """Build mandatory metadata for a location-specific approved document."""

    return {
        "location_code": location_code.strip().lower(),
        "location_id": location_id,
        "document_category": document_category,
    }


def is_document_available_for_location(metadata: dict[str, Any], location_code: str) -> bool:
    """Permit only matching location documents or explicitly approved global documents."""

    requested = location_code.strip().lower()
    document_location = metadata.get("location_code")
    if document_location == requested:
        return True
    return document_location == "global" and metadata.get("global_approved") is True
