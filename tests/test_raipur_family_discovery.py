"""Fake-only coverage for natural family-activity discovery on the LangGraph path.

Family/children fun-activity questions must receive the approved combined
discovery answer (water rides + celebration options + short follow-up) instead
of the generic fallback or the plain activity list.  Price, booking, availability,
location, contact, and exact-service questions must keep their existing routes.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.raipur.response_models import KnowledgeDraft
import app.services.raipur_inbound_orchestrator as module


class _Locations:
    def __init__(self, _client): pass

    def get_location_by_code(self, _code):
        return {
            "id": "raipur-id",
            "metadata": {
                "location_name": "Entartica Sea World Raipur",
                "address_line": "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh",
            },
        }


class _Services:
    def __init__(self, _client): pass

    def list_active_for_location(self, _location_id):
        return [
            {"name": "Speed Boat"}, {"name": "Kayak"}, {"name": "Jet Ski"},
            {"name": "Kids Bumper Boat"}, {"name": "Kids Paddle Boat"}, {"name": "Zorbing Ball"},
            {"name": "Pontoon Celebration"}, {"name": "Floating Gazebo"},
            {"name": "Jetty Gazebo"}, {"name": "Party Boat Celebration"}, {"name": "Houseboat Celebration"},
            {"name": "Staycation Combo"}, {"name": "Daycation Package"},
        ]


class _Contexts:
    def __init__(self, _client): self.saved = []; self.records = {}

    def get_service_context(self, conversation_id, customer_id):
        return self.records.get((conversation_id, customer_id))

    def save_service_context(self, conversation_id, customer_id, record):
        self.saved.append((conversation_id, customer_id, record))
        self.records[(conversation_id, customer_id)] = record


class _Knowledge:
    def __init__(self): self.service_calls = []; self.venue_calls = []

    def answer_service_details(self, question, service_name, service_code, **kwargs):
        self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
        return KnowledgeDraft("Speed Boat is an approved Raipur water-ride experience.", "speed_boat_ride.md", .8, False, "Overview")

    def answer_venue_overview(self, question):
        self.venue_calls.append(question)
        return KnowledgeDraft("Entartica Sea World Raipur is a water activity and celebration destination.", "raipur_general_information.md", .8, False, "About Entartica Raipur")


_ALL_FIVE_CELEBRATIONS = ("Pontoon Celebration", "Floating Gazebo", "Jetty Gazebo", "Party Boat Celebration", "Houseboat Celebration")


def _message(text):
    return NormalizedInboundMessage(
        external_message_id="message-id", customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111", message_type="text", content=text,
        received_at=datetime.now(timezone.utc),
    )


def _orchestrator(monkeypatch, knowledge):
    monkeypatch.setattr(module, "LocationRepository", _Locations)
    monkeypatch.setattr(module, "ServiceRepository", _Services)
    monkeypatch.setattr(module, "ConversationRepository", _Contexts)
    monkeypatch.setattr(module, "BookingEnquiryRepository", lambda _client: object())
    monkeypatch.setattr(module, "BookingEnquiryService", lambda *_args: object())
    monkeypatch.setattr(module, "build_raipur_availability_provider", lambda *_args, **_kwargs: object())
    settings = SimpleNamespace(
        app_timezone="Asia/Kolkata", raipur_langgraph_enabled=True,
        router_revision="raipur-router-test", raipur_conversation_context_ttl_minutes=120,
        conversation_session_ttl_minutes=30,
    )
    return module.RaipurInboundOrchestrator(object(), settings, knowledge_provider=knowledge)


def _process(orchestrator, text, context=None, *, customer_id="customer-id", conversation_id="conversation-id"):
    return orchestrator.process(
        _message(text), customer={"id": customer_id}, conversation={"id": conversation_id},
        source_message_id="message-id", current_state=context,
    )


def _assert_discovery_no_fallback(result, knowledge):
    assert result.detected_intent == "family_activity_discovery"
    assert result.safe_metadata["selected_route"] == "answer_venue_knowledge"
    assert result.safe_metadata["graph_answer_source"] == "family_activity_discovery"
    assert result.safe_metadata["response_basis"] == "deterministic"
    assert not result.human_handover_required
    assert knowledge.service_calls == [] and knowledge.venue_calls == []
    assert result.context.active_topic == "activity_catalogue"


def test_english_family_fun_question_returns_approved_family_discovery(monkeypatch):
    knowledge = _Knowledge()
    result = _process(
        _orchestrator(monkeypatch, knowledge),
        "i am coming with my family, which fun activities we can do?",
    )

    _assert_discovery_no_fallback(result, knowledge)
    text = result.draft_text
    assert "Water rides and activities:" in text
    assert "Celebration experiences:" in text
    for name in ("Speed Boat", "Kayak", "Jet Ski"):
        assert name in text
    for name in _ALL_FIVE_CELEBRATIONS:
        assert name in text
    assert "age group" in text
    assert "guests" in text
    assert "celebration" in text
    assert "price" not in text.casefold()
    assert "booking confirm" not in text.casefold()
    assert "available today" not in text.casefold()


def test_hinglish_family_question_returns_family_discovery_in_hinglish(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "family ke saath kya activities kar sakte hain?")

    _assert_discovery_no_fallback(result, knowledge)
    assert result.response_language == "hinglish"
    text = result.draft_text
    assert "Water rides aur activities" in text
    assert "Celebration experiences" in text
    assert "bataiye" in text
    for name in _ALL_FIVE_CELEBRATIONS:
        assert name in text


def test_hindi_family_question_returns_family_discovery_in_hindi(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "परिवार के साथ क्या कर सकते हैं?")

    _assert_discovery_no_fallback(result, knowledge)
    assert result.response_language == "hi"
    text = result.draft_text
    assert any("\u0900" <= char <= "\u097f" for char in text)
    assert "Celebration experiences" in text
    for name in _ALL_FIVE_CELEBRATIONS:
        assert name in text


def test_children_family_question_asks_for_children_age_group_without_suitability_claim(monkeypatch):
    knowledge = _Knowledge()
    result = _process(
        _orchestrator(monkeypatch, knowledge),
        "We are coming with children. What rides can we do?",
    )

    _assert_discovery_no_fallback(result, knowledge)
    text = result.draft_text
    assert "age group of the children" in text
    assert "celebration" in text
    assert "suitable for every" not in text.casefold()
    assert "all ages" not in text.casefold()
    assert "every ride" not in text.casefold()


def test_family_discovery_followup_kids_options_uses_catalogue_context_not_fallback(monkeypatch):
    knowledge = _Knowledge()
    orchestrator = _orchestrator(monkeypatch, knowledge)
    first = _process(orchestrator, "family ke saath kya kar sakte hain?")
    followup = _process(orchestrator, "kids options batao")

    assert first.detected_intent == "family_activity_discovery"
    assert first.context.active_topic == "activity_catalogue"
    assert followup.detected_intent == "activity_service_list"
    assert followup.safe_metadata["graph_answer_source"] == "approved_kids_activity_catalogue"
    assert followup.safe_metadata["selected_route"] == "answer_catalogue"
    assert followup.safe_metadata["catalogue_item_count"] > 0
    assert not followup.human_handover_required
    assert knowledge.service_calls == [] and knowledge.venue_calls == []


def test_explicit_service_question_is_not_captured_as_family_discovery(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "Tell me about Jet Ski")
    assert result.detected_intent == "service_overview"
    assert result.safe_metadata["selected_route"] == "answer_service_knowledge"
    assert knowledge.service_calls == [("Tell me about Jet Ski", "Jet Ski", "jet_ski_ride", "overview")]


def test_normal_activity_catalogue_question_keeps_its_route(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "What activities do you have?")
    assert result.detected_intent == "activity_service_list"
    assert result.safe_metadata["graph_answer_source"] == "approved_activity_catalogue"
    assert result.safe_metadata["selected_route"] == "answer_catalogue"
    assert result.safe_metadata["catalogue_type"] == "activity"


@pytest.mark.parametrize("message", ("kids water activities", "boat for kids", "kids ke liye kya hai?"))
def test_kids_discovery_uses_approved_kids_catalogue_without_celebrations(monkeypatch, message):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), message)
    assert result.detected_intent == "activity_service_list"
    assert result.safe_metadata["graph_answer_source"] == "approved_kids_activity_catalogue"
    for name in ("Kids Bumper Boat", "Kids Paddle Boat", "Zorbing Ball"):
        assert name in result.draft_text
    assert "Pontoon Celebration" not in result.draft_text and "Speed Boat" not in result.draft_text
    assert knowledge.service_calls == [] and knowledge.venue_calls == []


def test_kids_category_overrides_stale_service_context(monkeypatch):
    knowledge = _Knowledge(); orchestrator = _orchestrator(monkeypatch, knowledge)
    selected = _process(orchestrator, "Tell me about Jet Ski")
    result = _process(orchestrator, "kids water activities", selected.context)
    assert result.detected_intent == "activity_service_list"
    assert result.safe_metadata["graph_answer_source"] == "approved_kids_activity_catalogue"
    assert result.context.last_service_code is None
    assert "Kids Bumper Boat" in result.draft_text and "Jet Ski" not in result.draft_text


def test_rides_then_adventure_stays_in_water_activity_discovery(monkeypatch):
    knowledge = _Knowledge(); orchestrator = _orchestrator(monkeypatch, knowledge)
    catalogue = _process(orchestrator, "rides")
    result = _process(orchestrator, "adventure", module._context_to_record(catalogue.context))

    assert catalogue.safe_metadata["graph_answer_source"] == "approved_activity_catalogue"
    assert "Pontoon Celebration" not in catalogue.draft_text
    assert result.safe_metadata["graph_answer_source"] == "approved_activity_catalogue"
    assert result.context.active_topic == "activity_catalogue"
    assert "celebration details" not in result.draft_text.casefold()


def test_compound_water_activity_phrase_uses_only_water_catalogue(monkeypatch):
    result = _process(_orchestrator(monkeypatch, _Knowledge()), "water sports ride activity???")

    assert result.safe_metadata["graph_answer_source"] == "approved_activity_catalogue"
    assert result.context.active_topic == "activity_catalogue"
    assert "Speed Boat" in result.draft_text
    assert not any(name in result.draft_text for name in (
        "Floating Gazebo", "Houseboat Celebration", "Party Boat Celebration",
        "Pontoon Celebration", "Jetty Gazebo",
    ))


@pytest.mark.parametrize("preference", (
    "i am looking good and calm experience", "something relaxing",
    "peaceful activity", "easy and relaxing", "I don't want adventure",
    "bahut fast nahi", "relaxing chahiye", "calm activity batao",
))
def test_natural_calm_preference_continues_water_discovery(monkeypatch, preference):
    orchestrator = _orchestrator(monkeypatch, _Knowledge())
    catalogue = _process(orchestrator, "water sports ride activity???")
    result = _process(orchestrator, preference, module._context_to_record(catalogue.context))

    assert result.safe_metadata["graph_answer_source"] == "approved_activity_catalogue"
    assert result.context.active_topic == "activity_catalogue"
    lowered = result.draft_text.casefold()
    assert "noted that preference" not in lowered and "celebration details" not in lowered
    assert "Speed Boat" in result.draft_text and "Pontoon Celebration" not in result.draft_text


@pytest.mark.parametrize("first_message", ("rides", "water activities"))
def test_activity_catalogue_then_family_fun_uses_family_discovery(monkeypatch, first_message):
    knowledge = _Knowledge(); orchestrator = _orchestrator(monkeypatch, knowledge)
    catalogue = _process(orchestrator, first_message)
    result = _process(orchestrator, "family fun", module._context_to_record(catalogue.context))

    assert result.detected_intent == "family_activity_discovery"
    assert result.safe_metadata["graph_answer_source"] == "family_activity_discovery"
    assert result.context.active_topic == "activity_catalogue"
    assert "celebration details" not in result.draft_text.casefold()


@pytest.mark.parametrize("preference,expected_source", (
    ("adventure", "approved_activity_catalogue"),
    ("family fun", "family_activity_discovery"),
))
def test_new_rides_discovery_overrides_stale_celebration_domain(monkeypatch, preference, expected_source):
    knowledge = _Knowledge(); orchestrator = _orchestrator(monkeypatch, knowledge)
    celebration = _process(orchestrator, "I want to celebrate")
    rides = _process(orchestrator, "rides", module._context_to_record(celebration.context))
    result = _process(orchestrator, preference, module._context_to_record(rides.context))

    assert rides.context.active_entity_name == "activity"
    assert rides.context.pending_action is None
    assert result.safe_metadata["graph_answer_source"] == expected_source
    assert "celebration details" not in result.draft_text.casefold()


def test_availability_family_catalogue_question_keeps_catalogue_route(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "Which family rides are available today?")
    assert result.detected_intent == "activity_service_list"
    assert result.safe_metadata["selected_route"] == "answer_catalogue"
    assert not result.human_handover_required
    assert knowledge.service_calls == [] and knowledge.venue_calls == []


def test_family_pricing_question_still_handovers_to_sales(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "What is the price for family activities?")
    assert result.detected_intent == "pricing"
    assert result.safe_metadata["selected_route"] == "handover_to_sales"
    assert result.human_handover_required
    assert "sales@entartica.com" in result.draft_text
    assert "₹" not in result.draft_text
    assert knowledge.service_calls == [] and knowledge.venue_calls == []


def test_family_booking_question_still_handovers_without_confirmation(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "Book family activities for tomorrow.")
    assert result.detected_intent == "booking"
    assert result.safe_metadata["selected_route"] == "handover_to_sales"
    assert result.human_handover_required
    assert "sales@entartica.com" in result.draft_text
    assert "confirmed" not in result.draft_text.casefold()
    assert not result.booking_enquiry_created
    assert knowledge.service_calls == [] and knowledge.venue_calls == []
