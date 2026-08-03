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
        if existing_response is not None and isinstance(existing_response.data, dict):
            return existing_response.data

        response = self._client.table("conversations").insert(
            {"customer_id": customer_id, "state": "new", "mode": "bot"}
        ).execute()
        return response.data[0]

    def get_open(self, customer_id: str) -> dict[str, Any] | None:
        """Return the customer's open conversation without creating one."""

        response = (
            self._client.table("conversations")
            .select("*")
            .eq("customer_id", customer_id)
            .neq("state", "closed")
            .is_("closed_at", "null")
            .maybe_single()
            .execute()
        )
        return response.data if response is not None else None

    def get_service_context(self, conversation_id: str, customer_id: str) -> dict[str, Any] | None:
        """Return context only for the exact customer-owned conversation."""

        response = (
            self._client.table("conversations")
            .select("customer_id,service_context")
            .eq("id", conversation_id)
            .eq("customer_id", customer_id)
            .maybe_single()
            .execute()
        )
        data = response.data if response is not None else None
        if not isinstance(data, dict) or data.get("customer_id") != customer_id:
            return None
        context = data.get("service_context")
        return context if isinstance(context, dict) else None

    def save_service_context(self, conversation_id: str, customer_id: str, context: dict[str, Any]) -> bool:
        """Persist only the exact structured context for its owning conversation."""

        response = (
            self._client.table("conversations")
            .update({"service_context": context})
            .eq("id", conversation_id)
            .eq("customer_id", customer_id)
            .execute()
        )
        return bool(getattr(response, "data", None))
