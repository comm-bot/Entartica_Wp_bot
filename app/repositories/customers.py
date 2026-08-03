"""Data access for WhatsApp customers."""

from typing import Any

from supabase import Client


class CustomerRepository:
    """Find and create customers by normalized WhatsApp number."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_or_create(self, whatsapp_number: str, profile_name: str | None) -> dict[str, Any]:
        """Return an existing customer or create the first record for a number."""

        existing_response = (
            self._client.table("customers")
            .select("*")
            .eq("whatsapp_number", whatsapp_number)
            .maybe_single()
            .execute()
        )
        if existing_response is not None and isinstance(existing_response.data, dict):
            return existing_response.data

        record: dict[str, Any] = {"whatsapp_number": whatsapp_number}
        if profile_name is not None:
            record["name"] = profile_name
        response = self._client.table("customers").insert(record).execute()
        return response.data[0]

    def get_by_whatsapp_number(self, whatsapp_number: str) -> dict[str, Any] | None:
        """Return one customer by normalized WhatsApp number."""

        response = (
            self._client.table("customers")
            .select("*")
            .eq("whatsapp_number", whatsapp_number)
            .maybe_single()
            .execute()
        )
        return response.data if response is not None else None

    def list_by_ids(self, customer_ids: list[str]) -> list[dict[str, Any]]:
        """Return the minimal customer fields for a local, masked sales view."""

        if not customer_ids:
            return []
        response = self._client.table("customers").select("id,name,whatsapp_number").in_("id", customer_ids).execute()
        data = getattr(response, "data", None) if response is not None else None
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
