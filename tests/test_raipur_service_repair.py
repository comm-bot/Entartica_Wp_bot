"""Service-information repairs must retry exact-service retrieval, not existence."""

from datetime import UTC, datetime

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft, RaipurConversationService


class _Knowledge:
    def __init__(self): self.calls = []
    def answer(self, _question): return KnowledgeDraft(None)
    def answer_service_details(self, question, name, code=None, **kwargs):
        self.calls.append((question, name, code, kwargs.get("detail_mode")))
        return KnowledgeDraft(f"{name} ride experience has approved additional information.", f"{code}.md", .8, False, "How It Generally Works", 3)


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"name": "Jet Ski", "slug": "jet-ski", "is_active": True}, {"name": "Staycation Combo", "slug": "staycation-combo", "is_active": True}]


class _Bookings:
    def create_idempotent(self, row): return row, True
class _Availability:
    def check(self, _request): return AvailabilityResult("verification_required")
class _Drafts:
    def create_outbound_draft(self, **_kwargs): return {}, False


def _service(knowledge):
    services = _Services()
    return RaipurConversationService(knowledge=knowledge, bookings=BookingEnquiryService(_Bookings(), _Availability(), services), drafts=_Drafts(), services=services, persist_drafts=False)


def _process(service, text, state=None):
    message = NormalizedInboundMessage(external_message_id="repair", customer_whatsapp_number="+910000000000", business_whatsapp_number="+911111111111", message_type="text", content=text, received_at=datetime.now(UTC))
    return service.process(message, customer={"id": "customer"}, conversation={"id": "conversation", "location_id": "raipur"}, source_message_id="repair", current_state=state)


@pytest.mark.parametrize("question", ("No first give me details about Jet Ski", "Why can't you provide more info about Jet Ski?"))
def test_repair_requests_use_exact_service_more_details_not_existence(question):
    knowledge = _Knowledge()
    result = _process(_service(knowledge), question)

    assert result.detected_intent == "service_more_details"
    assert result.context.last_service_code == "jet_ski"
    assert knowledge.calls and knowledge.calls[0][1:] == ("Jet Ski", "jet_ski_ride", "more_details")
    assert "is offered at" not in result.draft_text.casefold()


def test_contextual_more_details_uses_previous_service_before_fallback():
    knowledge = _Knowledge()
    state = ConversationContext(BookingDetails(None, "Staycation Combo", None, None, None, None, None), last_service_name="Staycation Combo", last_service_code="staycation_combo")
    result = _process(_service(knowledge), "Can you give more details about it?", state)

    assert result.detected_intent == "service_more_details"
    assert result.context.last_service_code == "staycation_combo"
    assert knowledge.calls and knowledge.calls[0][1:] == ("Staycation Combo", "staycation_combo", "more_details")
