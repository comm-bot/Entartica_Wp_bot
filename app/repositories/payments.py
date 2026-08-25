"""Durable server-side access to payment attempts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supabase import Client

from app.repositories.bookings import _one


class PaymentRepository:
    """Store provider-neutral payment state without confirming bookings."""

    ACTIVE_STATUSES = ("created", "issued", "pending")

    def __init__(self, client: Client) -> None:
        self._client = client

    def create_payment(self, record: Mapping[str, Any]) -> dict[str, Any]:
        row = _one(self._client.table("payments").insert(dict(record)).execute())
        if row is None:
            raise RuntimeError("Payment insert returned no row.")
        return row

    def get_payment_by_id(self, payment_id: str) -> dict[str, Any] | None:
        return _one(self._client.table("payments").select("*").eq("id", payment_id).maybe_single().execute())

    def get_payment_by_reference(self, reference_id: str) -> dict[str, Any] | None:
        return _one(self._client.table("payments").select("*").eq("reference_id", reference_id).maybe_single().execute())

    def get_payment_by_provider_link_id(self, provider_payment_link_id: str) -> dict[str, Any] | None:
        return _one(self._client.table("payments").select("*").eq("provider_payment_link_id", provider_payment_link_id).maybe_single().execute())

    def get_active_payment_for_booking(self, booking_id: str) -> dict[str, Any] | None:
        response = (
            self._client.table("payments").select("*").eq("booking_id", booking_id)
            .in_("status", list(self.ACTIVE_STATUSES))
            .order("created_at", desc=True).limit(1).maybe_single().execute()
        )
        return _one(response)

    def get_latest_payment_for_booking(self, booking_id: str) -> dict[str, Any] | None:
        response = (
            self._client.table("payments").select("*").eq("booking_id", booking_id)
            .order("created_at", desc=True).limit(1).maybe_single().execute()
        )
        return _one(response)

    def update_payment(self, payment_id: str, fields: Mapping[str, Any]) -> dict[str, Any] | None:
        if not fields:
            return self.get_payment_by_id(payment_id)
        return _one(self._client.table("payments").update(dict(fields)).eq("id", payment_id).execute())
