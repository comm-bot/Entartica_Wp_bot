"""Catalogue and venue intents must override stale selected-service context."""

from datetime import UTC, datetime

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft, RaipurConversationService


class _Knowledge:
    def __init__(self): self.calls = []
    def answer(self, _question): return KnowledgeDraft(None)
    def answer_service_details(self, question, name, code=None, **_kwargs):
        self.calls.append((question, name, code))
        return KnowledgeDraft(f"{name} approved inclusion detail.", f"{code}.md", .8, False, "What Is Included", 2)


class _Services:
    rows = (
        ("Staycation Combo", "staycation-combo"), ("Jet Ski", "jet-ski"),
        ("Kayak", "kayak"), ("Floating Gazebo", "floating-gazebo"),
    )
    def list_active_for_location(self, _location_id):
        return [{"name": name, "slug": slug, "is_active": True} for name, slug in self.rows]


class _Bookings:
    def create_idempotent(self, row): return row, True


class _Availability:
    def check(self, _request): return AvailabilityResult("verification_required")


class _Drafts:
    def create_outbound_draft(self, **_kwargs): return {}, False


def _service(knowledge):
    services = _Services()
    return RaipurConversationService(knowledge=knowledge, bookings=BookingEnquiryService(_Bookings(), _Availability(), services), drafts=_Drafts(), services=services, persist_drafts=False)


def _state(name="Staycation Combo", code="staycation_combo"):
    return ConversationContext(BookingDetails(None, name, None, None, None, None, None), last_service_name=name, last_service_code=code, active_entity_type="service", active_entity_name=name)


def _process(service, text, state):
    message = NormalizedInboundMessage(
        external_message_id="catalogue-context",
        customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111",
        message_type="text",
        content=text,
        received_at=datetime.now(UTC),
    )
    return service.process(message, customer={"id": "customer"}, conversation={"id": "conversation", "location_id": "raipur"}, source_message_id="catalogue-context", current_state=state)


@pytest.mark.parametrize("state", (_state(), _state("Kayak", "kayak")))
@pytest.mark.parametrize("question", ("How many rides are there?", "What rides do you have?", "What are the rides?", "What are the rides available?", "Show all activities", "Show all water activities", "Can you provide other rides?", "Show me other rides.", "What else do you have?", "Any other activities?", "Aur kaun si rides hain?", "Dusri rides batao.", "Aur kya hai?", "can you tell me about various rides", "tell me about various rides", "what are the different rides", "show me all activities", "aur kaun kaun si rides hain"))
def test_catalogue_questions_bypass_stale_service_context(state, question):
    knowledge = _Knowledge()
    result = _process(_service(knowledge), question, state)

    assert result.reason_code == "structured_service_list"
    assert result.detected_intent == "service_catalogue"
    assert "Jet Ski" in result.draft_text and "Kayak" in result.draft_text
    assert knowledge.calls == []
    assert result.context.last_service_code is None
    assert result.context.active_entity_type == "catalogue"
    assert result.context.active_topic == "service_catalogue"
    assert "+91" not in result.draft_text and "visit date" not in result.draft_text.casefold() and "guest count" not in result.draft_text.casefold()


def test_inclusion_count_keeps_selected_service_context_and_uses_exact_rag():
    knowledge = _Knowledge()
    result = _process(_service(knowledge), "How many rides are included?", _state())

    assert result.detected_intent == "service_detail"
    assert result.context.last_service_code == "staycation_combo"
    assert knowledge.calls == [("How many rides are included?", "Staycation Combo", "staycation_combo")]


def test_explicit_service_inclusion_replaces_old_context():
    knowledge = _Knowledge()
    result = _process(_service(knowledge), "How many rides are included in Jet Ski?", _state())

    assert result.context.last_service_code == "jet_ski"
    assert knowledge.calls == [("how many rides are included in jet ski?", "Jet Ski", "jet_ski_ride")]


def test_celebration_catalogue_bypasses_stale_service_context():
    knowledge = _Knowledge()
    result = _process(_service(knowledge), "What celebration options are available?", _state())

    assert result.reason_code == "structured_celebration_service_list"
    assert result.context.last_service_code is None
    assert result.context.active_topic == "celebration_catalogue"
    assert knowledge.calls == []
