"""Fake-only Daycation routing and safety coverage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService


class _Knowledge:
    def __init__(self): self.detail_calls: list[tuple[str, str]] = []
    def answer(self, _question): return KnowledgeDraft(None)
    def answer_service_details(self, question, service_name):
        self.detail_calls.append((question, service_name))
        return KnowledgeDraft("Daycation generally means a same-day leisure experience without an overnight stay. Entartica Raipur offers a Daycation Package. Current package details must be confirmed by the Entartica team.", "daycation_package.md", .8, False)


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"name": "Daycation Package", "slug": "daycation-package", "is_active": True}]


class _Bookings:
    def create_idempotent(self, record): return record, True


class _Availability:
    def __init__(self): self.calls = 0
    def check(self, _request): self.calls += 1; return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class _Drafts:
    def create_outbound_draft(self, **_kwargs): return {}, False


def _message(text: str) -> NormalizedInboundMessage:
    return NormalizedInboundMessage(external_message_id="daycation", customer_whatsapp_number="+910000000000", business_whatsapp_number="+911111111111", message_type="text", content=text, received_at=datetime.now(UTC))


def _service():
    knowledge, availability, services = _Knowledge(), _Availability(), _Services()
    return RaipurConversationService(knowledge=knowledge, bookings=BookingEnquiryService(_Bookings(), availability, services), drafts=_Drafts(), services=services, location={"id": "raipur"}, persist_drafts=False), knowledge, availability


def _process(text: str):
    service, knowledge, availability = _service()
    result = service.process(_message(text), customer={"id": "customer"}, conversation={"id": "conversation", "location_id": "raipur"}, source_message_id="daycation")
    return result, knowledge, availability


@pytest.mark.parametrize("question", ["Daycation kya hai?", "What is a Daycation?", "Daycation package ka matlab kya hai?", "Same-day package kya hota hai?"])
def test_daycation_definition_is_safe_and_grounded_in_catalogue(question):
    result, knowledge, _ = _process(question)
    text = result.draft_text.casefold()

    assert result.detected_intent == "service_overview"
    assert "same-day leisure experience" in text and "overnight stay" in text
    assert "entartica raipur" in text and "daycation package" in text
    assert all(term not in text for term in ("10 am", "hours", "guests", "₹", "confirmed booking"))
    assert knowledge.detail_calls == [(question.casefold(), "Daycation Package")]


def test_daycation_detail_confirmation_pricing_and_availability_use_correct_routes():
    detail, knowledge, _ = _process("Tell me about Entartica Daycation Package.")
    confirmation, _, _ = _process("Do you offer Daycation?")
    pricing, _, _ = _process("Daycation ka price?")
    availability, _, provider = _process("Daycation kal available hai?")

    assert detail.detected_intent == "service_overview" and knowledge.detail_calls == [("tell me about entartica daycation package.", "Daycation Package")]
    assert confirmation.detected_intent == "service_overview"
    assert pricing.detected_intent == "pricing" and pricing.human_handover_required
    assert availability.detected_intent == "availability" and availability.human_handover_required and provider.calls == 0
