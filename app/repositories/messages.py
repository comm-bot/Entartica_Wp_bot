"""Data access for normalized inbound messages."""

from typing import Any

from supabase import Client

from app.schemas.exotel_webhook import NormalizedInboundMessage


class DuplicateMessageError(Exception):
    """Raised when a provider message has already been stored."""


class MessageRepository:
    """Persist inbound messages without retaining raw provider payloads."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def store_inbound(
        self,
        message: NormalizedInboundMessage,
        *,
        customer_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        """Store a normalized inbound message or report a duplicate provider ID."""

        record = {
            "conversation_id": conversation_id,
            "customer_id": customer_id,
            "direction": "inbound",
            "message_type": message.message_type,
            "content": message.content,
            "external_provider": message.external_provider,
            "external_message_id": message.external_message_id,
            "received_at": message.received_at.isoformat(),
        }
        try:
            response = self._client.table("messages").insert(record).execute()
        except Exception as error:
            if getattr(error, "code", None) == "23505":
                raise DuplicateMessageError from error
            raise
        return response.data[0]
