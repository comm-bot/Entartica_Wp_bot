"""Inbound-message persistence workflow."""

from dataclasses import dataclass
import logging
import re
from typing import Any

from supabase import Client

from app.repositories.conversations import ConversationRepository
from app.repositories.customers import CustomerRepository
from app.repositories.messages import DuplicateMessageError, MessageRepository
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.latency import current_latency_trace, latency_stage


# Uvicorn configures this logger for normal server-console output.
logger = logging.getLogger("uvicorn.error")


def _database_target(error: Exception) -> str:
    """Return only a safe database column, relation, or constraint identifier."""

    for value in (getattr(error, "message", None), getattr(error, "details", None)):
        if not isinstance(value, str):
            continue
        match = re.search(
            r'(?:column|constraint|relation)\s+"?([A-Za-z_][A-Za-z0-9_.]*)"?',
            value,
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
    return "unknown"


def _log_repository_failure(operation: str, error: Exception) -> None:
    """Log redacted diagnostics for a failed Supabase repository operation."""

    logger.error(
        "inbound_repository_failed operation=%s exception_class=%s database_code=%s database_target=%s",
        operation,
        type(error).__name__,
        getattr(error, "code", None),
        _database_target(error),
    )


@dataclass(frozen=True)
class InboundMessageResult:
    """Outcome of persisting an inbound message."""

    duplicate: bool
    customer: dict[str, Any] | None = None
    conversation: dict[str, Any] | None = None
    inbound_message: dict[str, Any] | None = None
    recovered_after_transient_duplicate: bool = False


class InboundMessageService:
    """Persist normalized inbound messages in the required order."""

    def __init__(self, client: Client) -> None:
        self._customers = CustomerRepository(client)
        self._conversations = ConversationRepository(client)
        self._messages = MessageRepository(client)

    def process(self, message: NormalizedInboundMessage) -> InboundMessageResult:
        """Find or create the customer and conversation, then store the message."""

        try:
            with latency_stage("customer_lookup"):
                customer = self._customers.get_or_create(
                    message.customer_whatsapp_number, message.profile_name
                )
            if (trace := current_latency_trace()) is not None: trace.event("customer_lookup_complete", duration_ms=trace.value("customer_lookup"))
        except Exception as error:
            _log_repository_failure("customer_get_or_create", error)
            raise

        try:
            with latency_stage("conversation_load"):
                conversation = self._conversations.get_or_create_open(customer["id"])
            if (trace := current_latency_trace()) is not None: trace.event("conversation_lookup_complete", duration_ms=trace.value("conversation_load"))
        except Exception as error:
            _log_repository_failure("conversation_get_or_create_open", error)
            raise

        try:
            with latency_stage("duplicate_check"), latency_stage("draft_or_message_persistence"), latency_stage("inbound_message_persistence"):
                stored = self._messages.store_inbound(
                    message,
                    customer_id=customer["id"],
                    conversation_id=conversation["id"],
                )
        except DuplicateMessageError:
            existing = self._messages.find_inbound_by_provider_id(
                message.external_provider,
                message.external_message_id,
            )
            return InboundMessageResult(True, customer, conversation, existing)
        except Exception as error:
            _log_repository_failure("message_store_inbound", error)
            raise
        return InboundMessageResult(False, customer, conversation, stored)
