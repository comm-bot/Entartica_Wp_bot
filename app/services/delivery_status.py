"""Idempotent Exotel outbound delivery-status processing."""

from datetime import UTC, datetime

from supabase import Client

from app.repositories.messages import MessageRepository
from app.schemas.exotel_status import NormalizedDeliveryStatus


_STATUS_RANK = {"pending": 0, "accepted": 1, "sent": 2, "delivered": 3, "read": 4}


class DeliveryStatusService:
    """Update only valid forward delivery transitions for outbound messages."""

    def __init__(self, client: Client) -> None:
        self._messages = MessageRepository(client)

    def process(self, callback: NormalizedDeliveryStatus) -> bool:
        """Apply one delivery callback; return false for duplicate or unsupported data."""

        message = None
        if callback.provider_message_id:
            message = self._messages.find_outbound_by_provider_sid(callback.provider_message_id)
        if message is None or callback.status is None:
            return False

        current = message.get("delivery_status") or "pending"
        if not self._can_transition(current, callback.status):
            return False

        timestamp = (callback.occurred_at or datetime.now(UTC)).isoformat()
        fields: dict[str, str] = {"delivery_status": callback.status}
        if callback.status == "sent":
            fields["sent_at"] = timestamp
        elif callback.status == "delivered":
            fields["delivered_at"] = timestamp
        elif callback.status == "read":
            fields["read_at"] = timestamp
        elif callback.status == "failed":
            fields["failed_at"] = timestamp
            fields["failure_code"] = callback.failure_code or "provider_delivery_failed"
            fields["failure_description"] = callback.failure_description or "provider_delivery_failed"
        self._messages.update_delivery_status(message["id"], fields)
        return True

    @staticmethod
    def _can_transition(current: str, incoming: str) -> bool:
        if current in {"read", "failed"}:
            return False
        if current == "delivered":
            return incoming == "read"
        if incoming == "failed":
            return current in {"pending", "accepted", "sent"}
        return _STATUS_RANK.get(incoming, -1) > _STATUS_RANK.get(current, -1)
