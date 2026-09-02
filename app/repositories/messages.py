"""Data access for normalized inbound messages."""

from typing import Any
from datetime import UTC, datetime

from supabase import Client

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.latency import latency_counter


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
            latency_counter("supabase_writes")
            response = self._client.table("messages").insert(record).execute()
        except Exception as error:
            if getattr(error, "code", None) == "23505":
                raise DuplicateMessageError from error
            raise
        return response.data[0]

    def create_outbound_pending(
        self, *, customer_id: str, conversation_id: str, content: str
    ) -> dict[str, Any]:
        """Create the durable outbound record before contacting Exotel."""

        response = self._client.table("messages").insert(
            {
                "conversation_id": conversation_id,
                "customer_id": customer_id,
                "direction": "outbound",
                "message_type": "text",
                "content": content,
                "external_provider": "exotel",
                "delivery_status": "pending",
            }
        ).execute()
        return response.data[0]

    def create_outbound_draft(
        self, *, customer_id: str, conversation_id: str, related_inbound_message_id: str,
        content: str, metadata: dict[str, Any], generated_by: str = "raipur_draft_orchestrator",
    ) -> tuple[dict[str, Any], bool]:
        """Persist an idempotent local draft; this method never contacts a provider."""

        existing = (
            self._client.table("messages").select("*").eq("direction", "outbound")
            .eq("related_inbound_message_id", related_inbound_message_id).eq("generated_by", generated_by)
            .eq("draft_status", "draft").maybe_single().execute()
        )
        if existing is not None and isinstance(existing.data, dict):
            return existing.data, False
        response = self._client.table("messages").insert({
            "conversation_id": conversation_id, "customer_id": customer_id, "direction": "outbound",
            "message_type": "text", "content": content, "delivery_status": "draft", "draft_status": "draft",
            "related_inbound_message_id": related_inbound_message_id, "draft_metadata": metadata,
            "generated_by": generated_by,
        }).execute()
        return response.data[0], True

    def mark_outbound_accepted(
        self, message_id: str, provider_message_id: str
    ) -> dict[str, Any]:
        """Attach the Exotel SID after its accepted response."""

        response = self._client.table("messages").update(
            {
                "external_message_id": provider_message_id,
                "delivery_status": "accepted",
                "accepted_at": datetime.now(UTC).isoformat(),
            }
        ).eq("id", message_id).execute()
        return response.data[0]

    def mark_outbound_failed(self, message_id: str, failure_code: str) -> None:
        """Retain a failed outbound record without provider error details."""

        self._client.table("messages").update(
            {
                "delivery_status": "failed",
                "failed_at": datetime.now(UTC).isoformat(),
                "failure_code": failure_code,
                "failure_description": "provider_request_failed",
            }
        ).eq("id", message_id).execute()

    def find_outbound_by_provider_sid(self, provider_message_id: str) -> dict[str, Any] | None:
        """Return an outbound Exotel message by provider SID."""

        response = (
            self._client.table("messages")
            .select("*")
            .eq("direction", "outbound")
            .eq("external_provider", "exotel")
            .eq("external_message_id", provider_message_id)
            .maybe_single()
            .execute()
        )
        return response.data if response is not None else None

    def find_outbound_by_id(self, message_id: str) -> dict[str, Any] | None:
        """Return an outbound message by its internal UUID callback identifier."""

        response = (
            self._client.table("messages")
            .select("*")
            .eq("id", message_id)
            .eq("direction", "outbound")
            .maybe_single()
            .execute()
        )
        return response.data if response is not None else None

    def update_delivery_status(self, message_id: str, fields: dict[str, Any]) -> None:
        """Update one existing outbound message lifecycle record."""

        self._client.table("messages").update(fields).eq("id", message_id).execute()
