"""Data access for customer conversations."""

from typing import Any

from supabase import Client


class ConversationRepository:
    """Find and create open conversations."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_or_create_open(self, customer_id: str) -> dict[str, Any]:
        """Return the current open conversation or create a bot-mode conversation."""

        existing_response = (
            self._client.table("conversations")
            .select("*")
            .eq("customer_id", customer_id)
            .neq("state", "closed")
            .is_("closed_at", "null")
            .maybe_single()
            .execute()
        )
        if existing_response is not None:
            return existing_response.data

        response = self._client.table("conversations").insert(
            {"customer_id": customer_id, "state": "new", "mode": "bot"}
        ).execute()
        return response.data[0]
