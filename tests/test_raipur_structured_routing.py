"""Fake-only coverage for structured Raipur location and active-service routing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_automatic_replies import eligible_for_automatic_reply
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft, RaipurConversationService


class Knowledge:
    def __init__(self): self.calls = 0; self.detail_calls = []
    def answer(self, _question): self.calls += 1; return KnowledgeDraft(None)
    def answer_service_details(self, question, service_name):
        self.detail_calls.append((question, service_name))
        return KnowledgeDraft(f"{service_name} is an approved Raipur experience.", "services.docx", .7, False)


class Services:
    def __init__(self):
        self.rows = [
            {"id": "jet", "name": "Jet Ski", "slug": "jet-ski", "is_active": True},
            {"id": "speed", "name": "Speed Boat", "slug": "speed-boat", "is_active": True},
            {"id": "kayak", "name": "Kayak", "slug": "kayak", "is_active": True},
            {"id": "gazebo", "name": "Floating Gazebo", "slug": "floating-gazebo", "is_active": True},
            {"id": "inactive", "name": "Pontoon Boat", "slug": "pontoon-boat", "is_active": False},
        ]
    def list_active_for_location(self, _location_id): return list(self.rows)
    def find_active_by_customer_text(self, _location_id, _text): return None


class BookingRepository:
    def create_idempotent(self, record): return record, True


class Availability:
    def __init__(self): self.calls = 0
    def check(self, _request): self.calls += 1; return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class Drafts:
    def create_outbound_draft(self, **_kwargs): return {}, False


def _message(text: str):
    return NormalizedInboundMessage(
        external_message_id="message",
        customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111",
        message_type="text",
        content=text,
        received_at=datetime(2026, 7, 24, tzinfo=UTC),
    )


def _service():
    knowledge, services, availability = Knowledge(), Services(), Availability()
    bookings = BookingEnquiryService(BookingRepository(), availability, services)
    conversation = RaipurConversationService(
        knowledge=knowledge,
        bookings=bookings,
        drafts=Drafts(),
        services=services,
        location={
            "id": "raipur",
            "name": "Entartica Sea World Raipur",
            "address": "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh",
            "metadata": {
                "location_name": "Entartica Sea World Raipur",
                "address_line": "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh",
                "landmark": "Near MAYFAIR Resort",
                "maps_url": "https://maps.app.goo.gl/VtxPyANfMC3rztex8",
            },
        },
    )
    return conversation, knowledge, availability


def _process(text: str):
    service, knowledge, availability = _service()
    result = service.process(_message(text), customer={"id": "customer", "name": "Customer"}, conversation={"id": "conversation", "location_id": "raipur"}, source_message_id="message")
    return result, knowledge, availability


@pytest.mark.parametrize("question", ["Where is Entartica Raipur?", "Can you give location for Raipur?", "Can you give me location of Raipur?", "Raipur ka location kaha par hain?", "Raipur mein Entartica kaha hai?", "Address bhejo.", "Google Maps link bhejo.", "\u090f\u0902\u091f\u093e\u0930\u094d\u091f\u093f\u0915\u093e \u0930\u093e\u092f\u092a\u0941\u0930 \u0915\u0939\u093e\u0901 \u0939\u0948?"])
def test_location_is_deterministic_and_never_calls_rag(question):
    result, knowledge, _ = _process(question)
    assert result.reason_code == "structured_location"
    for approved_part in ("Sector 24", "Jhanjh Lake", "Atal Nagar", "New Raipur", "Chhattisgarh", "MAYFAIR Resort", "https://maps.app.goo.gl/VtxPyANfMC3rztex8"):
        assert approved_part in result.draft_text
    assert result.draft_text != "Our location is in Raipur, Chhattisgarh."
    assert knowledge.calls == 0
    assert result.safe_metadata["deterministic_answer_used"] is True
    assert result.safe_metadata["response_basis"] == "deterministic"
    assert result.safe_metadata["structured_grounding"] is True


def test_service_list_uses_only_active_approved_records_without_price_or_slot_claims():
    result, knowledge, _ = _process("What activities are available at Entartica Raipur?")
    assert result.reason_code == "structured_service_list" and knowledge.calls == 0
    assert "Jet Ski" in result.draft_text and "Speed Boat" in result.draft_text and "Kayak" in result.draft_text
    assert "Pontoon Boat" not in result.draft_text
    assert "price" not in result.draft_text.casefold() and "slot" not in result.draft_text.casefold()


@pytest.mark.parametrize("question,expected", [("Do you have jet skiing?", "Jet Ski"), ("Is speedboat offered?", "Speed Boat"), ("\u0915\u094d\u092f\u093e \u091c\u0947\u091f \u0938\u094d\u0915\u0940 \u0939\u0948?", "Jet Ski")])
def test_explicit_aliases_use_exact_overviews_for_active_approved_services(question, expected):
    result, knowledge, _ = _process(question)
    assert result.reason_code == "approved_service_detail" and expected in result.draft_text
    assert knowledge.calls == 0 and result.safe_metadata["matched_service_present"] is True
    assert "is offered at entartica raipur" not in result.draft_text.casefold()


def test_live_time_availability_uses_booking_workflow_not_service_confirmation():
    result, knowledge, availability = _process("Is Jet Ski available tomorrow at 5 PM?")
    assert result.action == "check_availability" and result.human_handover_required
    assert "currently appears available" not in result.draft_text.casefold()
    assert knowledge.calls == 0 and availability.calls == 1


def test_unsupported_service_clarifies_and_high_risk_requests_remain_blocked():
    clarification, knowledge, _ = _process("Tell me about surfing at Raipur")
    # Unresolved Entartica questions now attempt approved Raipur retrieval
    # before clarification; the fallback must still not invent Surfing facts.
    assert clarification.reason_code == "clarification_required" and not clarification.human_handover_required and knowledge.calls == 1
    assert "surfing" not in clarification.draft_text.casefold()
    pricing, _, _ = _process("What is the price of Jet Ski?")
    assert pricing.reason_code == "human_quotation_required" and pricing.human_handover_required


def test_structured_answers_and_live_availability_use_safe_response_modes():
    result, _, _ = _process("Do you have jet skiing?")
    settings = SimpleNamespace(exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True, raipur_automatic_reply_enabled=True, raipur_automatic_reply_intents=("services", "location", "information", "clarification"))
    draft = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}
    assert eligible_for_automatic_reply(settings, result, draft) == (True, "eligible")
    availability, _, _ = _process("Is Jet Ski available tomorrow at 5 PM?")
    assert availability.human_handover_required
    assert availability.safe_metadata["response_mode"] == "human_handover"
    assert eligible_for_automatic_reply(settings, availability, draft) == (True, "eligible")


def test_service_detail_uses_exact_service_rag_instead_of_confirmation():
    result, knowledge, _ = _process("Give me information about Floating Gazebo")
    assert result.reason_code == "approved_service_detail"
    assert "approved Raipur experience" in result.draft_text
    assert "is offered at" not in result.draft_text
    assert knowledge.detail_calls == [("give me information about floating gazebo", "Floating Gazebo")]
    assert result.safe_metadata["rag_used"] is True and result.safe_metadata["exact_service_chunk_match"] is True


def test_follow_up_uses_same_conversation_service_context_and_replaces_it_when_changed():
    service, knowledge, _ = _service()
    customer, conversation = {"id": "customer", "name": "Customer"}, {"id": "conversation", "location_id": "raipur"}
    first = service.process(_message("Floating Gazebo"), customer=customer, conversation=conversation, source_message_id="one")
    follow_up = service.process(_message("Can you give me?"), customer=customer, conversation=conversation, source_message_id="two", current_state=first.context)
    changed = service.process(_message("Jet Ski"), customer=customer, conversation=conversation, source_message_id="three", current_state=follow_up.context)
    assert first.context.last_service_name == "Floating Gazebo"
    assert follow_up.reason_code == "approved_service_detail" and knowledge.detail_calls[-2][1] == "Floating Gazebo"
    assert changed.context.last_service_name == "Jet Ski"


def test_location_correction_preempts_stale_service_context():
    service, knowledge, _ = _service()
    customer, conversation = {"id": "customer", "name": "Customer"}, {"id": "conversation", "location_id": "raipur"}
    service_context = service.process(_message("Floating Gazebo"), customer=customer, conversation=conversation, source_message_id="one")
    correction = service.process(_message("Mera matlab Raipur mein location kaha hai"), customer=customer, conversation=conversation, source_message_id="two", current_state=service_context.context)

    assert correction.reason_code == "structured_location"
    assert "Floating Gazebo" not in correction.draft_text
    assert correction.context.last_service_name == "Floating Gazebo"
    assert correction.context.active_topic == "entartica_raipur_location"
    assert correction.context.active_entity_type == "place"
    assert correction.context.active_entity_name == "Entartica Sea World Raipur"
    assert correction.context.pending_action is None
    assert knowledge.calls == 0


@pytest.mark.parametrize("service_name,service_code", [("Pontoon Boat", "pontoon_boat"), ("Kayak", "kayak")])
def test_explicit_location_request_preempts_stale_service_context(service_name, service_code):
    service, knowledge, _ = _service()
    customer, conversation = {"id": "customer", "name": "Customer"}, {"id": "conversation", "location_id": "raipur"}
    stale = ConversationContext(
        details=BookingDetails(None, service_name, None, None, None, None, None, special_requirements_collected=False),
        last_service_name=service_name,
        last_service_code=service_code,
        pending_question_type="yes_no",
        pending_action="provide_service_details",
        pending_entity_type="service",
        pending_entity_name=service_name,
        pending_created_at="2026-07-28T10:00:00+00:00",
        pending_service_code=service_code,
    )
    result = service.process(_message("Can you give location for Raipur?"), customer=customer, conversation=conversation, source_message_id="location", current_state=stale)

    assert result.reason_code == "structured_location"
    assert "Sector 24" in result.draft_text
    assert service_name not in result.draft_text
    assert result.context.active_topic == "entartica_raipur_location"
    assert result.context.pending_action is None
    assert knowledge.calls == 0 and knowledge.detail_calls == []


def test_location_link_follow_up_uses_latest_location_entity_without_service_rag():
    service, knowledge, _ = _service()
    customer, conversation = {"id": "customer", "name": "Customer"}, {"id": "conversation", "location_id": "raipur"}
    location = service.process(_message("Raipur ka location kaha par he"), customer=customer, conversation=conversation, source_message_id="one")
    follow_up = service.process(_message("Uski koy link he kya"), customer=customer, conversation=conversation, source_message_id="two", current_state=location.context)

    assert follow_up.reason_code == "structured_location"
    assert "https://maps.app.goo.gl/VtxPyANfMC3rztex8" in follow_up.draft_text
    assert "Pontoon Boat" not in follow_up.draft_text and "Celebration" not in follow_up.draft_text
    assert knowledge.calls == 0 and knowledge.detail_calls == []


def test_location_correction_clears_pending_service_action_and_answers_immediately():
    service, knowledge, _ = _service()
    customer, conversation = {"id": "customer", "name": "Customer"}, {"id": "conversation", "location_id": "raipur"}
    service_prompt = service.process(_message("What is Floating Gazebo?"), customer=customer, conversation=conversation, source_message_id="one")
    pending_service = replace(
        service_prompt.context,
        pending_action="provide_service_details",
        pending_question_type="yes_no",
        pending_service_code="floating_gazebo",
    )
    correction = service.process(_message("Pontoon ki baat nahi kar raha, location ki baat kar raha hoon"), customer=customer, conversation=conversation, source_message_id="two", current_state=pending_service)

    assert pending_service.pending_action == "provide_service_details"
    assert correction.reason_code == "structured_location"
    assert correction.safe_metadata["response_basis"] == "conversation_repair"
    assert correction.context.pending_action is None
    assert correction.context.pending_question_type is None
    assert correction.context.pending_service_code is None
    assert not correction.context.service_selection_prompted
    assert "https://maps.app.goo.gl/VtxPyANfMC3rztex8" in correction.draft_text
    assert knowledge.calls == 0 and len(knowledge.detail_calls) == 1


def test_yes_uses_the_latest_pending_location_map_action_not_service_action():
    service, knowledge, _ = _service()
    customer, conversation = {"id": "customer", "name": "Customer"}, {"id": "conversation", "location_id": "raipur"}
    state = ConversationContext(
        details=BookingDetails(None, "Floating Gazebo", None, None, None, None, None, special_requirements_collected=False),
        last_service_name="Floating Gazebo",
        last_service_code="floating_gazebo",
        pending_question_type="yes_no",
        pending_action="send_location_map_link",
        pending_entity_type="place",
        pending_entity_name="Entartica Sea World Raipur",
        pending_created_at="2026-07-28T10:00:00+00:00",
        pending_service_code="floating_gazebo",
    )
    result = service.process(_message("Yes"), customer=customer, conversation=conversation, source_message_id="yes", current_state=state)

    assert result.reason_code == "structured_location"
    assert "https://maps.app.goo.gl/VtxPyANfMC3rztex8" in result.draft_text
    assert "Floating Gazebo" not in result.draft_text
    assert knowledge.calls == 0 and knowledge.detail_calls == []


def test_city_geography_and_travel_do_not_return_entartica_location():
    city, _, _ = _process("Raipur city kaha hai?")
    travel, _, _ = _process("Raipur kaise ja sakte hain?")

    assert city.reason_code == "raipur_city_geography"
    assert "Chhattisgarh" in city.draft_text
    assert "Sector 24" not in city.draft_text
    assert travel.reason_code == "destination_scope_clarification"
    assert "Sector 24" not in travel.draft_text


def test_localized_location_response_and_automatic_reply_eligibility():
    english, _, _ = _process("Where is Entartica Raipur?")
    hinglish, _, _ = _process("Raipur location kaha hai?")
    hindi, _, _ = _process("रायपुर का स्थान कहाँ है?")
    settings = SimpleNamespace(exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True, raipur_automatic_reply_enabled=True, raipur_automatic_reply_intents=("location",))
    draft = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}

    assert "is located at" in english.draft_text
    assert "mein" in hinglish.draft_text and "ke paas located hai" in hinglish.draft_text
    assert "में" in hindi.draft_text and "स्थित है" in hindi.draft_text
    assert english.detected_intent == "location"
    assert eligible_for_automatic_reply(settings, english, draft) == (True, "eligible")


def test_hinglish_and_hindi_templates_keep_the_current_language_style():
    hinglish, _, _ = _process("Raipur ki activity kya hain?")
    hindi, _, _ = _process("क्या जेट स्की है?")
    assert "Raipur mein" in hinglish.draft_text
    assert "Jet Ski" in hindi.draft_text and "is offered at entartica raipur" not in hindi.draft_text.casefold()
