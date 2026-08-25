"""Send form completion through the existing durable outbound claim pipeline."""
from __future__ import annotations

from typing import Any

from app.integrations.exotel import ExotelClient
from app.repositories.outbound_drafts import OutboundDraftRepository
from app.services.raipur_draft_sender import RaipurDraftSender


class CustomerDetailsDelivery:
    def __init__(self, database: Any, settings: Any) -> None:
        values = (settings.exotel_account_sid, settings.exotel_api_key,
                  settings.exotel_api_token, settings.exotel_whatsapp_from)
        if any(value is None for value in values):
            raise RuntimeError("customer_details_sender_configuration_unavailable")
        self._repository = OutboundDraftRepository(database)
        exotel = ExotelClient(
            account_sid=settings.exotel_account_sid,
            api_key=settings.exotel_api_key.get_secret_value(),
            api_token=settings.exotel_api_token.get_secret_value(),
            whatsapp_from=settings.exotel_whatsapp_from,
            api_base_url=settings.exotel_api_base_url,
        )
        self._sender = RaipurDraftSender(self._repository, settings, exotel)

    async def send(self, *, customer: dict[str, Any], conversation_id: str,
                   form_id: str, content: str) -> bool:
        number, customer_id = customer.get("whatsapp_number"), customer.get("id")
        if not isinstance(number, str) or not isinstance(customer_id, str):
            return False
        draft, _created = self._repository.create_customer_details_continuation_draft(
            customer_id=customer_id, conversation_id=conversation_id,
            form_id=form_id, content=content,
        )
        if draft.get("draft_status") == "sent" or draft.get("external_message_id"):
            return True
        if draft.get("draft_status") == "pending_review" and not self._repository.approve_draft(draft["id"]):
            return False
        result = await self._sender.send(draft["id"], number, confirmed=True)
        return bool(result.accepted and result.sid_recorded)
