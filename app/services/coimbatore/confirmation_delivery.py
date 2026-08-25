"""Booking-confirmation delivery through the existing durable draft sender."""
from __future__ import annotations

import asyncio
from typing import Any

from app.integrations.exotel import ExotelClient
from app.repositories.outbound_drafts import OutboundDraftRepository
from app.services.raipur_draft_sender import RaipurDraftSender


class ExotelConfirmationDelivery:
    def __init__(self, database: Any, settings: Any) -> None:
        values = (settings.exotel_account_sid, settings.exotel_api_key,
                  settings.exotel_api_token, settings.exotel_whatsapp_from)
        if any(value is None for value in values):
            raise RuntimeError("confirmation_sender_configuration_unavailable")
        self._repository = OutboundDraftRepository(database)
        exotel = ExotelClient(
            account_sid=settings.exotel_account_sid,
            api_key=settings.exotel_api_key.get_secret_value(),
            api_token=settings.exotel_api_token.get_secret_value(),
            whatsapp_from=settings.exotel_whatsapp_from,
            api_base_url=settings.exotel_api_base_url,
        )
        self._sender = RaipurDraftSender(self._repository, settings, exotel)

    def send(self, *, booking: dict[str, Any], payment: dict[str, Any], pdf_url: str,
             filename: str, caption: str) -> bool:
        if not booking.get("customer_mobile"):
            return False
        draft, _created = self._repository.create_booking_confirmation_draft(
            booking=booking, content=caption, document_url=pdf_url, filename=filename,
        )
        if draft.get("draft_status") == "sent" or draft.get("external_message_id"):
            return True
        if draft.get("draft_status") == "pending_review" and not self._repository.approve_draft(draft["id"]):
            return False
        result = asyncio.run(self._sender.send(draft["id"], booking["customer_mobile"], confirmed=True))
        return bool(result.accepted and result.sid_recorded)
