"""Fake-only regression coverage for general service-definition responses."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_automatic_replies import eligible_for_automatic_reply
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService
from app.services.raipur_conversational_fallback import RaipurConversationalFallback


class _Knowledge:
    def answer(self, _question): return KnowledgeDraft(None)
    def answer_service_details(self, _question, service_name, *_args): return KnowledgeDraft(f"{service_name} approved overview.", "service.md", .8, False)
    def fallback_context(self, _question): return ()


class _Services:
    def list_active_for_location(self, _location_id): return [{"name": "Bumper Boat", "slug": "bumper-boat", "is_active": True}, {"name": "Jet Ski", "slug": "jet-ski", "is_active": True}]
    def find_active_by_customer_text(self, _location_id, _text): return None


class _Bookings:
    def create_idempotent(self, record): return record, True


class _Availability:
    def check(self, _request): return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class _Drafts:
    def create_outbound_draft(self, **_kwargs): return {}, False


def _message(text):
    return NormalizedInboundMessage(external_message_id="id", customer_whatsapp_number="+910000000000", business_whatsapp_number="+911111111111", message_type="text", content=text, received_at=datetime.now(UTC))


def _service(responder=None):
    services = _Services()
    return RaipurConversationService(
        knowledge=_Knowledge(), bookings=BookingEnquiryService(_Bookings(), _Availability(), services), drafts=_Drafts(), services=services,
        location={"id": "raipur"}, persist_drafts=False, conversational_fallback=RaipurConversationalFallback(responder),
    )


def _process(service, text, state=None):
    return service.process(_message(text), customer={"id": "customer"}, conversation={"id": "conversation", "location_id": "raipur"}, source_message_id="id", current_state=state)


@pytest.mark.parametrize("question", ["Bumper Boat kya hai?", "What is a Bumper Boat?", "Bumper boat kya chiz hai?", "Mera matlab bumper boat kya hoti hai?", "buper bot kya hai?"])
def test_definition_phrases_route_to_general_definition(question):
    result = _process(_service(lambda *_: "A bumper boat is generally a small recreational boat that a guest gently steers on water."), question)
    assert result.detected_intent == "service_overview"
    assert result.context.last_service_code == "bumper_boat"
    assert result.draft_text.startswith("Bumper Boat")
    assert "is offered at" not in result.draft_text.casefold()


def test_definition_context_is_preserved_for_hinglish_follow_up():
    service = _service(lambda *_: "A bumper boat is generally a small recreational boat that a guest gently steers on water.")
    first = _process(service, "Bumper Boat kya hai?")
    follow_up = _process(service, "Mera matalab ye kaise hoti hai?", first.context)
    assert follow_up.detected_intent == "generic_service_definition"
    assert follow_up.context.last_service_name == "Bumper Boat"


def test_definition_is_information_eligible_and_operational_claims_are_rejected():
    unsafe = _service(lambda *_: "It accommodates 50 guests for one hour and is completely safe.")
    result = _process(unsafe, "Bumper Boat kya hai?")
    assert result.detected_intent == "service_overview"
    assert all(value not in result.draft_text.casefold() for value in ("50", "hour", "safe"))
    settings = SimpleNamespace(exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True, raipur_automatic_reply_enabled=True, raipur_automatic_reply_intents=("information",))
    draft = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}
    assert eligible_for_automatic_reply(settings, result, draft) == (True, "eligible")


def test_confirmation_pricing_and_live_availability_remain_on_existing_routes():
    service = _service(lambda *_: (_ for _ in ()).throw(AssertionError("definition model must not be called")))
    overview = _process(service, "Do you offer Bumper Boat?")
    assert overview.detected_intent == "service_overview"
    assert "is offered at entartica raipur" not in overview.draft_text.casefold()
    assert _process(service, "Bumper Boat ka price kya hai?").detected_intent == "pricing"
    assert _process(service, "Kal Bumper Boat available hai?").detected_intent == "availability"
