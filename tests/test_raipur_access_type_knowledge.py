"""D3 approved access-type knowledge: offline document and LangGraph routing tests.

These tests use only local documents and fake repositories.  No external API
or database is called.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.rag.raipur_ingestion import build_plan
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.raipur.response_models import KnowledgeDraft
import app.services.raipur_inbound_orchestrator as module

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Offline document assertions
# --------------------------------------------------------------------------- #

def _documents_by_code():
    plan, errors = build_plan(ROOT)
    assert not errors, errors
    return {row.document.metadata["service_code"]: row.document for row in plan if row.document is not None}


def _section_text(document, heading):
    wanted = re.sub(r"[^a-z0-9]+", " ", heading.casefold()).strip()
    for section in document.sections:
        if re.sub(r"[^a-z0-9]+", " ", section.heading.casefold()).strip() == wanted:
            return section.text
    return ""


def test_celebration_starting_durations_are_present_and_no_longer_fixed_hours():
    docs = _documents_by_code()
    assert "2 hours" in _section_text(docs["party_boat_celebration"], "Duration")
    assert "1 hour" not in _section_text(docs["party_boat_celebration"], "Duration")
    assert "30 minutes" in _section_text(docs["houseboat_celebration"], "Duration")
    assert "30 minutes" in _section_text(docs["pontoon_celebration"], "Duration")
    assert "2 hours" in _section_text(docs["jetty_gazebo"], "Duration")
    assert "2 hours" in _section_text(docs["floating_gazebo"], "Duration")
    for code in ("party_boat_celebration", "houseboat_celebration", "pontoon_celebration", "jetty_gazebo", "floating_gazebo"):
        duration = _section_text(docs[code], "Duration")
        assert "5 to 10 minutes" not in duration
        assert "after confirmation" in duration
        assert "not automatically included" in duration
        operating = _section_text(docs[code], "Operating Hours")
        assert "10:00 AM to 9:00 PM" in operating
        assert "subject to weather" in operating


def test_one_time_access_rides_are_explicitly_one_time_access():
    docs = _documents_by_code()
    for code in ("pontoon_boat_ride", "jet_ski_ride", "speed_boat_ride", "inflatable_sofa_ride"):
        access = _section_text(docs[code], "Access Type").casefold()
        assert "one-time access" in access
        assert "does not mean unlimited repeat use" in access
        duration = _section_text(docs[code], "Duration")
        assert "5 to 10 minutes" in duration
        assert "starting" not in duration.casefold()
        operating = _section_text(docs[code], "Operating Hours")
        assert "10:00 AM to 6:30 PM" in operating
        assert "subject to weather" in operating


def test_pontoon_boat_ride_remains_separate_from_pontoon_celebration():
    docs = _documents_by_code()
    assert "5 to 10 minutes" in _section_text(docs["pontoon_boat_ride"], "Duration")
    assert "one-time access" in _section_text(docs["pontoon_boat_ride"], "Access Type").casefold()
    assert "30 minutes" in _section_text(docs["pontoon_celebration"], "Duration")
    assert "One-Time Access" not in _section_text(docs["pontoon_celebration"], "Access Type")


def test_h2o_playpark_activities_are_marked_full_day_access_not_one_time():
    docs = _documents_by_code()
    for code in ("kayaking", "aqua_cycle", "water_bike", "bumper_boat", "kids_paddle_boat", "zorbing_ball", "kids_bumper_boat"):
        access = _section_text(docs[code], "Access Type")
        normalized_access = access.casefold().replace("playpark", "play park")
        assert all(term in normalized_access for term in ("h2o", "play park", "access"))
        assert "one-time access" not in access.casefold()
        assert "10:00 AM to 6:30 PM" in _section_text(docs[code], "Operating Hours")
        duration = _section_text(docs[code], "Duration")
        normalized_duration = duration.casefold().replace("playpark", "play park")
        assert all(term in normalized_duration for term in ("h2o", "play park", "access"))
        assert "10:00 am to 6:30 pm" in normalized_duration
        assert "does not mean" in duration
        assert "not separately confirmed" in duration
        assert "5 to 10 minutes" not in duration


def test_kayak_is_not_primary_one_time_access_and_water_bike_uses_full_day_access():
    docs = _documents_by_code()
    kayak_access = _section_text(docs["kayaking"], "Access Type")
    assert "one-time access" not in kayak_access.casefold()
    assert "h2o play park" in kayak_access.casefold()
    water_bike_duration = _section_text(docs["water_bike"], "Duration")
    assert "full-day h2o access" in water_bike_duration.casefold()
    assert "does not mean" in water_bike_duration
    assert "5 to 10 minutes" not in water_bike_duration
    assert "all day" not in water_bike_duration.casefold()


def test_general_document_has_ride_access_types_and_updated_party_boat_duration():
    docs = _documents_by_code()
    text = docs["raipur_general"].text
    assert "Ride Access Types" in text
    assert "One-Time Access" in text
    for ride in ("Pontoon Boat Ride", "Jet Ski Ride", "Speed Boat Ride", "Inflatable Sofa Ride"):
        assert ride in text
    assert "H2O Playpark" in text and "10:00 AM to 6:30 PM" in text
    for activity in ("Zorbing Ball", "Kids Bumper Boat", "Kids Paddle Boat", "Water Bike"):
        assert activity in text
    assert "Duration: 2 hours (starting)" in text
    assert "Duration: 1 hour" not in text


# --------------------------------------------------------------------------- #
# LangGraph routing assertions (fake-only)
# --------------------------------------------------------------------------- #

class _Locations:
    def __init__(self, _client): pass

    def get_location_by_code(self, _code):
        return {"id": "raipur-id", "metadata": {"location_name": "Entartica Sea World Raipur"}}


class _Services:
    def __init__(self, _client): pass

    def list_active_for_location(self, _location_id):
        return [
            {"name": "Pontoon Boat"}, {"name": "Kayak"}, {"name": "Speed Boat"}, {"name": "Jet Ski"},
            {"name": "Water Bike"}, {"name": "Pontoon Celebration"}, {"name": "Floating Gazebo"},
            {"name": "Jetty Gazebo"}, {"name": "Houseboat Celebration"}, {"name": "Party Boat Celebration"},
        ]


class _Contexts:
    def __init__(self, _client): self.records = {}

    def get_service_context(self, conversation_id, customer_id): return self.records.get((conversation_id, customer_id))

    def save_service_context(self, conversation_id, customer_id, record):
        self.records[(conversation_id, customer_id)] = record


class _Knowledge:
    def __init__(self): self.service_calls = []; self.venue_calls = []

    def answer_service_details(self, question, service_name, service_code, **kwargs):
        self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
        return KnowledgeDraft("Speed Boat is an approved Raipur water-ride experience.", "speed_boat_ride.md", 0.8, False, "Overview", 2, "document-speed-boat")

    def answer_venue_overview(self, question):
        self.venue_calls.append(question)
        return KnowledgeDraft(
            "Entartica Sea World Raipur is a water activity and celebration destination on Jhanjh Lake.",
            "raipur_general_information.md", 0.8, False, "About Entartica Raipur", 1, "document-venue",
        )


class _DurationKnowledge(_Knowledge):
    def __init__(self):
        super().__init__()
        self._durations = {
            "houseboat_celebration": (
                "Starting duration: 30 minutes. The duration may be extended on request, subject to confirmation from the Entartica sales team. Extension is not confirmed automatically.",
                "houseboat_celebration.md",
            ),
            "party_boat_celebration": (
                "Starting duration: 2 hours. The duration may be extended on request, subject to confirmation from the Entartica sales team. Extension is not confirmed automatically.",
                "party_boat_celebration.md",
            ),
        }

    def answer_service_details(self, question, service_name, service_code, **kwargs):
        self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
        if kwargs.get("detail_mode") == "duration" and service_code in self._durations:
            text, source = self._durations[service_code]
            return KnowledgeDraft(text, source, 0.8, False, "Duration", 1, f"document-{service_code}", ("Duration",))
        return super().answer_service_details(question, service_name, service_code, **kwargs)


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
        router_revision="raipur-router-access-type-test", raipur_conversation_context_ttl_minutes=120,
        conversation_session_ttl_minutes=30,
    )
    return module.RaipurInboundOrchestrator(object(), settings, knowledge_provider=knowledge)


def _process(orchestrator, text, context=None, *, customer_id="customer-id", conversation_id="conversation-id"):
    return orchestrator.process(
        _message(text), customer={"id": customer_id}, conversation={"id": conversation_id},
        source_message_id="message-id", current_state=context,
    )


@pytest.mark.parametrize("question", [
    "What is H2O Playpark?",
    "What are the H2O Playpark timings?",
    "Which activities are included in H2O Playpark?",
    "What is the H2O play park?",
])
def test_h2o_playpark_questions_use_deterministic_answer_without_rag(monkeypatch, question):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), question)
    assert result.detected_intent == "h2o_playpark"
    assert result.safe_metadata["selected_route"] == "answer_venue_knowledge"
    assert result.safe_metadata["graph_answer_source"] == "h2o_playpark"
    assert result.safe_metadata["response_mode"] == "h2o_playpark"
    assert not knowledge.service_calls and not knowledge.venue_calls
    assert "10:00 AM to 6:30 PM" in result.draft_text
    assert "Kayak" in result.draft_text and "Zorbing Ball" in result.draft_text
    assert "do not each run all day" in result.draft_text
    assert "price" not in result.draft_text.casefold()
    assert "confirmed automatically" not in result.draft_text.casefold()
    assert "+91 9429691418" in result.draft_text and "sales@entartica.com" in result.draft_text


def test_h2o_playpark_hinglish_answer_keeps_access_hours(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "H2O Playpark kya hai?")
    assert result.safe_metadata["graph_answer_source"] == "h2o_playpark"
    assert "10:00 AM" in result.draft_text and "6:30 PM" in result.draft_text
    assert "Entartica team" in result.draft_text


def test_h2o_playpark_price_question_is_still_sales_handover(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "What is the H2O Playpark price?")
    assert result.human_handover_required
    assert result.safe_metadata["selected_route"] == "handover_to_sales"
    assert not knowledge.service_calls and not knowledge.venue_calls
    assert "sales@entartica.com" in result.draft_text


def test_houseboat_extension_request_routes_to_duration_and_needs_sales_confirmation(monkeypatch):
    knowledge = _DurationKnowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "Can we extend Houseboat Celebration?")
    assert result.safe_metadata["service_code"] == "houseboat_celebration"
    assert result.safe_metadata["topic"] == "duration"
    assert result.safe_metadata["selected_route"] == "answer_service_knowledge"
    assert knowledge.service_calls[-1][3] == "duration"
    assert "30 minutes" in result.draft_text
    assert "subject to confirmation" in result.draft_text
    assert "sales team" in result.draft_text
    assert "not confirmed automatically" in result.draft_text


def test_party_boat_extension_request_routes_to_duration_with_starting_2_hours(monkeypatch):
    knowledge = _DurationKnowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "Can we extend Party Boat Celebration to three hours?")
    assert result.safe_metadata["service_code"] == "party_boat_celebration"
    assert result.safe_metadata["topic"] == "duration"
    assert "2 hours" in result.draft_text
    assert "subject to confirmation" in result.draft_text


def test_party_boat_three_hour_booking_request_is_sales_handover_not_auto_confirmation(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "Can I book Party Boat for three hours?")
    assert result.human_handover_required and result.detected_intent == "booking"
    assert result.safe_metadata["selected_route"] == "handover_to_sales"
    assert not knowledge.service_calls and not knowledge.venue_calls
    assert "sales@entartica.com" in result.draft_text
    assert "confirmed" not in result.draft_text.casefold()
