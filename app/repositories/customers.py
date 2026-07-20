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
        if existing_response is not None:
            return existing_response.data

        record: dict[str, Any] = {"whatsapp_number": whatsapp_number}
        if profile_name is not None:
            record["name"] = profile_name
        response = self._client.table("customers").insert(record).execute()
        return response.data[0]
