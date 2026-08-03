"""Disabled-by-default outbound WhatsApp sending workflow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from supabase import Client

from app.config import Settings, get_settings
from app.integrations.exotel import ExotelClient, ExotelOutboundError
from app.repositories.conversations import ConversationRepository
from app.repositories.customers import CustomerRepository
from app.repositories.messages import MessageRepository


class OutboundMessageError(RuntimeError):
    """Safe error returned to a trusted local caller."""


class OutboundMessagingDisabledError(OutboundMessageError):
    """Raised while outbound sending is disabled."""


class OutboundMessageValidationError(OutboundMessageError):
    """Raised for invalid local send requests."""


@dataclass(frozen=True)
class OutboundSendResult:
    """Minimal accepted outbound message result."""

    internal_message_id: str
    provider_message_id: str


class OutboundMessageService:
    """Create, submit, and retain outbound Exotel messages."""

    def __init__(
        self,
        client: Client,
        *,
        settings: Settings | None = None,
        exotel_client: ExotelClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._customers = CustomerRepository(client)
        self._conversations = ConversationRepository(client)
        self._messages = MessageRepository(client)
        self._exotel_client = exotel_client

    async def send_text_message(self, *, to_number: str, text: str) -> OutboundSendResult:
        """Send one text only after recording it as a pending outbound message."""

        if not self._settings.exotel_outbound_enabled:
            raise OutboundMessagingDisabledError("Outbound messaging is disabled.")
        if not to_number.startswith("+") or not to_number[1:].isdigit() or len(text.strip()) == 0:
            raise OutboundMessageValidationError("Recipient and message are required.")
        if len(text) > 4096:
            raise OutboundMessageValidationError("Message is too long.")
        exotel_client = self._client()
        status_callback = self._status_callback_url()

        customer = await asyncio.to_thread(
            self._customers.get_by_whatsapp_number, to_number
        )
        if customer is None:
            raise OutboundMessageValidationError("Customer does not exist.")
        conversation = await asyncio.to_thread(self._conversations.get_open, customer["id"])
        if conversation is None:
            raise OutboundMessageValidationError("Open conversation does not exist.")
        pending = await asyncio.to_thread(
            self._messages.create_outbound_pending,
            customer_id=customer["id"],
            conversation_id=conversation["id"],
            content=text,
        )

        try:
            accepted = await exotel_client.send_text_message(
                to_number,
                text,
                status_callback,
                str(pending["id"]),
            )
        except ExotelOutboundError as error:
            await asyncio.to_thread(
                self._messages.mark_outbound_failed, pending["id"], error.code
            )
            raise OutboundMessageError("Outbound provider request failed.") from error

        await asyncio.to_thread(
            self._messages.mark_outbound_accepted,
            pending["id"],
            accepted.provider_message_id,
        )
        return OutboundSendResult(
            internal_message_id=str(pending["id"]),
            provider_message_id=accepted.provider_message_id,
        )

    def _client(self) -> ExotelClient:
        if self._exotel_client is not None:
            return self._exotel_client
        required = (
            self._settings.exotel_account_sid,
            self._settings.exotel_api_key,
            self._settings.exotel_api_token,
            self._settings.exotel_whatsapp_from,
            self._settings.public_base_url,
        )
        if any(value is None for value in required):
            raise OutboundMessageValidationError("Outbound configuration is incomplete.")
        return ExotelClient(
            account_sid=self._settings.exotel_account_sid or "",
            api_key=self._settings.exotel_api_key.get_secret_value(),
            api_token=self._settings.exotel_api_token.get_secret_value(),
            whatsapp_from=self._settings.exotel_whatsapp_from or "",
            api_base_url=self._settings.exotel_api_base_url,
        )

    def _status_callback_url(self) -> str:
        if not self._settings.public_base_url:
            raise OutboundMessageValidationError("PUBLIC_BASE_URL is required.")
        return f"{self._settings.public_base_url.rstrip('/')}/webhooks/exotel/status"
