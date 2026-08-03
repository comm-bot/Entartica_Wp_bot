"""Safe persistence and sales-team views for booking enquiries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supabase import Client


def _rows(response: object) -> list[dict[str, Any]]:
    data = getattr(response, "data", None) if response is not None else None
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


class BookingEnquiryRepository:
    """Store enquiries idempotently; never creates a booking or payment action."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_by_source_message(self, source: str, source_message_id: str) -> dict[str, Any] | None:
        response = (
            self._client.table("booking_enquiries")
            .select("*")
            .eq("source", source)
            .eq("source_message_id", source_message_id)
            .maybe_single()
            .execute()
        )
        rows = _rows(response)
        return rows[0] if rows else None

    def create_idempotent(self, record: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        """Create once per inbound provider message and return ``(record, created)``."""

        source = record.get("source")
        message_id = record.get("source_message_id")
        if isinstance(source, str) and isinstance(message_id, str) and message_id:
            existing = self.get_by_source_message(source, message_id)
            if existing is not None:
                return existing, False
        rows = _rows(self._client.table("booking_enquiries").insert(dict(record)).execute())
        if not rows:
            raise RuntimeError("Booking enquiry insert returned no row.")
        return rows[0], True

    def list_recent_for_sales(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return only the fields needed for the local masked sales report."""

        response = (
            self._client.table("booking_enquiries")
            .select(
                "reference,customer_id,requested_service_id,requested_service_text,preferred_date,preferred_time,"
                "total_guests,availability_status,enquiry_status,assigned_salesperson,special_requirements"
            )
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return _rows(response)
