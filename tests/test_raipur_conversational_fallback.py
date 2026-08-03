"""Fake-only coverage for the safe Raipur conversational fallback."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.prompts.raipur_system_prompt import RAIPUR_SYSTEM_PROMPT
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_automatic_replies import eligible_for_automatic_reply
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService
from app.services.raipur_conversational_fallback import RaipurConversationalFallback


class _Knowledge:
    def __init__(self, text: str | None = None, low_confidence: bool = True): self.text, self.low_confidence, self.calls = text, low_confidence, 0
    def answer(self, _question): self.calls += 1; return KnowledgeDraft(self.text, "approved.md" if self.text else None, .7 if self.text else None, self.low_confidence)
    def fallback_context(self, _question): return ("Approved Raipur celebration information.",)


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"name": "Jet Ski", "slug": "jet-ski", "is_active": True}, {"name": "Party Boat Celebration", "slug": "party-boat-celebration", "is_active": True}]
    def find_active_by_customer_text(self, _location_id, _text): return None


class _Bookings:
    def create_idempotent(self, record): return record, True


class _Availability:
    def check(self, _request): return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class _Drafts:
    def create_outbound_draft(self, **_kwargs): return {}, False


def _message(text: str):
    return NormalizedInboundMessage(
        external_message_id="id", customer_whatsapp_number="+910000000000", business_whatsapp_number="+911111111111",
        message_type="text", content=text, received_at=datetime.now(UTC),
    )


def _service(responder, *, knowledge=None):
    services = _Services()
    return RaipurConversationService(
        knowledge=knowledge or _Knowledge(), bookings=BookingEnquiryService(_Bookings(), _Availability(), services), drafts=_Drafts(),
        services=services, location={"id": "raipur", "city": "Raipur", "state": "Chhattisgarh"}, persist_drafts=False,
        conversational_fallback=RaipurConversationalFallback(responder),
    )


def _process(service, text, state=None):
    return service.process(_message(text), customer={"id": "customer"}, conversation={"id": "conversation", "location_id": "raipur"}, source_message_id="id", current_state=state)


def test_unexpected_safe_question_gets_a_valid_information_reply_and_uses_prompt_context():
    calls = []
    def responder(prompt, context, retry):
        calls.append((prompt, context, retry))
        return "I can help you choose a Raipur experience. Do you prefer thrill, relaxation, family activity, or a celebration?"
    result = _process(_service(responder), "I do not know which ride will be good for me")
    assert result.reason_code == "safe_conversational_fallback"
    assert result.detected_intent == "safe_conversational_fallback"
    assert result.safe_metadata["response_basis"] == "conversational_fallback"
    assert calls and calls[0][1]["approved_knowledge_excerpts"] and calls[0][0] == RAIPUR_SYSTEM_PROMPT


def test_centralized_prompt_is_the_single_runtime_prompt_definition():
    from app.services.raipur_prompts import RAIPUR_CONVERSATIONAL_FALLBACK_SYSTEM_PROMPT

    assert RAIPUR_SYSTEM_PROMPT
    assert RAIPUR_CONVERSATIONAL_FALLBACK_SYSTEM_PROMPT is RAIPUR_SYSTEM_PROMPT
    assert "retrieved context is authoritative" in RAIPUR_SYSTEM_PROMPT.casefold()


@pytest.mark.parametrize("question", ["Anything fun?", "Mujhe kuch fun chahiye", "कुछ मज़ेदार चाहिए", "I wnt somthing fun"])
def test_safe_fallback_handles_english_hinglish_hindi_and_typos(question):
    result = _process(_service(lambda *_: "Would you prefer thrill, relaxation, a family activity, or a celebration?"), question)
    assert result.action == "answer_information" and not result.human_handover_required


def test_fallback_uses_selected_service_context_and_does_not_repeat_previous_response():
    seen = []
    def responder(_prompt, context, _retry):
        seen.append(context)
        return "For Party Boat Celebration, please share the occasion you have in mind."
    service = _service(responder)
    selected = _process(service, "Party Boat Celebration")
    result = _process(service, "What would suit a surprise?", selected.context)
    assert seen[-1]["selected_service"] == "Party Boat Celebration"
    assert result.draft_text != selected.draft_text


@pytest.mark.parametrize("unsafe", ["It costs ₹500", "The slot is available tomorrow", "Your booking is confirmed", "Payment is confirmed", "It accommodates 50 guests", "The package includes cake", "This is completely safe", "Source: private.docx"])
def test_unsafe_fallback_output_retries_once_then_uses_safe_clarification(unsafe):
    calls = []
    def responder(*_args): calls.append(1); return unsafe
    result = _process(_service(responder), "Anything fun?")
    assert len(calls) == 2
    assert result.reason_code == "approved_safe_fallback"
    assert result.safe_metadata["response_basis"] == "clarification"
    assert "sales@entartica.com" in result.draft_text
    assert unsafe.casefold() not in result.draft_text.casefold()
    assert "available tomorrow" not in result.draft_text.casefold()


def test_safe_fallback_is_automatic_reply_eligible_as_information():
    result = _process(_service(lambda *_: "Would you prefer thrill, relaxation, a family activity, or a celebration?"), "Anything fun?")
    settings = SimpleNamespace(exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True, raipur_automatic_reply_enabled=True, raipur_automatic_reply_intents=("information",))
    draft = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}
    assert eligible_for_automatic_reply(settings, result, draft) == (True, "eligible")


def test_restricted_pricing_booking_and_live_availability_never_call_fallback():
    calls = []
    service = _service(lambda *_: calls.append(1) or "unsafe")
    assert _process(service, "What is the price for Jet Ski?").detected_intent == "pricing"
    assert _process(service, "I want to book Jet Ski").detected_intent == "booking"
    assert _process(service, "Is Jet Ski available tomorrow at 4 PM?").detected_intent == "availability"
    assert calls == []


def test_active_rag_answer_keeps_existing_route_without_fallback():
    calls = []
    result = _process(_service(lambda *_: calls.append(1) or "unused", knowledge=_Knowledge("Approved Raipur activities include boating.", low_confidence=False)), "What can visitors enjoy?")
    assert result.reason_code == "approved_knowledge" and calls == []
