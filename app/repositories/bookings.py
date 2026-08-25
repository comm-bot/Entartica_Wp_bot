"""Durable server-side access to booking journeys."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supabase import Client


def _one(response: object) -> dict[str, Any] | None:
    data = getattr(response, "data", None) if response is not None else None
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


class BookingRepository:
    """Persist booking records independently of conversational sales state."""

    ACTIVE_STATUSES = (
        "form_pending", "form_submitted", "form_invalid",
        "payment_link_created", "payment_link_failed", "payment_pending",
        "payment_received", "confirmation_generating", "confirmation_failed",
        "handoff",
    )

    def __init__(self, client: Client) -> None:
        self._client = client

    def create_booking(self, record: Mapping[str, Any]) -> dict[str, Any]:
        row = _one(self._client.table("bookings").insert(dict(record)).execute())
        if row is None:
            raise RuntimeError("Booking insert returned no row.")
        return row

    def get_booking_by_ref(self, booking_ref: str) -> dict[str, Any] | None:
        return _one(self._client.table("bookings").select("*").eq("booking_ref", booking_ref).maybe_single().execute())

    def get_booking_by_id(self, booking_id: str) -> dict[str, Any] | None:
        return _one(self._client.table("bookings").select("*").eq("id", booking_id).maybe_single().execute())

    def update_booking(self, booking_id: str, fields: Mapping[str, Any]) -> dict[str, Any] | None:
        if not fields:
            return self.get_booking_by_id(booking_id)
        return _one(self._client.table("bookings").update(dict(fields)).eq("id", booking_id).execute())

    def get_active_booking_for_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        response = (
            self._client.table("bookings").select("*")
            .eq("conversation_id", conversation_id)
            .in_("status", list(self.ACTIVE_STATUSES))
            .order("created_at", desc=True).limit(1).maybe_single().execute()
        )
        return _one(response)
