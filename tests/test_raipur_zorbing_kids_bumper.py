"""Zorbing Ball and Kids Bumper Boat: offline routing, manifest, and catalogue tests.

These tests use only local documents and fake repositories.  No external API
or database is called.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from app.rag.raipur_ingestion import build_plan
from app.services.raipur.service_resolver import resolve_service
from app.services.raipur.h2o_handler import _ACTIVITIES, h2o_playpark_answer
from app.services.raipur_langgraph import RaipurLangGraphWorkflow
from app.services.raipur.response_models import KnowledgeDraft

ROOT = Path(__file__).resolve().parents[1]


def _section_text(document, heading):
    wanted = re.sub(r"[^a-z0-9]+", " ", heading.casefold()).strip()
    for section in document.sections:
        if re.sub(r"[^a-z0-9]+", " ", section.heading.casefold()).strip() == wanted:
            return section.text
    return ""


def _state(message: str):
    return {
        "message_id": "message", "conversation_id": "conversation", "customer_id": "customer",
        "customer_message": message, "normalized_message": message.casefold(), "language": "en",
        "location_code": "raipur", "previous_service_code": None, "intent": "unknown",
        "entity_type": "unknown", "service_code": None, "topic": None, "use_previous_service": False,
        "requires_handover": False, "handover_reason": None, "answer_source": "none",
        "draft_response": None, "validation_status": "pending", "error": None, "route": "",
    }


class _Conversation:
    def process(self, *_args, **_kwargs):
        return SimpleNamespace(response_valid=True, draft_text="Approved customer response")


def _plan(workflow, message):
    return workflow.plan_message({**_state(message), "_runtime": {"current_state": None}})


# --------------------------------------------------------------------------- #
# Document and manifest assertions
# --------------------------------------------------------------------------- #

def test_new_service_documents_are_eligible_and_approved_in_the_manifest():
    plan, errors = build_plan(ROOT)
    assert not errors, errors
    rows = {row.document.metadata["service_code"]: row for row in plan if row.document is not None}
    for code in ("zorbing_ball", "kids_bumper_boat"):
        assert rows[code].status == "eligible"
        metadata = rows[code].document.metadata
        assert metadata["location_code"] == "raipur"
        assert metadata["knowledge_type"] == "service"
        assert metadata["service_category"] == "water_ride"
        assert metadata["catalogue_status"] == "active"
        assert metadata["approval_status"] == "approved"
        assert metadata["customer_facing"] is True


def test_new_docs_use_full_day_access_and_no_individual_session_duration():
    plan, errors = build_plan(ROOT)
    assert not errors, errors
    docs = {row.document.metadata["service_code"]: row.document for row in plan if row.document is not None}
    for code in ("zorbing_ball", "kids_bumper_boat"):
        access = _section_text(docs[code], "Access Type").casefold()
        assert "h2o play park access" in access
        assert "full-day h2o access" in access
        assert "one-time access" not in access
        assert _section_text(docs[code], "H2O Playpark Access Hours") == ""
        assert "10:00 AM to 6:30 PM" in _section_text(docs[code], "Operating Hours")
        duration = _section_text(docs[code], "Duration")
        assert "full-day h2o access" in duration.casefold()
        assert "does not mean" in duration
        assert "not separately confirmed" in duration
        assert "5 to 10 minutes" not in docs[code].text
        assert "all day" not in docs[code].text.casefold()


def test_h2o_playpark_catalogue_includes_all_approved_activities():
    answer = h2o_playpark_answer("en")
    for activity in ("Kayak", "Aqua Cycle", "Bumper Boat", "Zorbing Ball", "Kids Bumper Boat", "Kids Paddle Boat", "Water Bike"):
        assert activity in _ACTIVITIES
        assert activity in answer
    assert "10:00 AM to 6:30 PM" in answer


# --------------------------------------------------------------------------- #
# Deterministic service resolution
# --------------------------------------------------------------------------- #

def test_zorbing_ball_resolution_covers_official_name_and_aliases():
    assert resolve_service("What is Zorbing Ball?").service_code == "zorbing_ball"
    assert resolve_service("Tell me about zorbing.").service_code == "zorbing_ball"
    assert resolve_service("zorb ball").service_code == "zorbing_ball"


def test_kids_bumper_boat_resolution_never_collapses_into_bumper_boat():
    assert resolve_service("What is Bumper Boat?").service_code == "bumper_boat"
    assert resolve_service("What is Kids Bumper Boat?").service_code == "kids_bumper_boat"
    for phrase in ("Tell me about children bumper boat.", "kid bumper boat", "kids bumperboat"):
        assert resolve_service(phrase).service_code == "kids_bumper_boat"


# --------------------------------------------------------------------------- #
# LangGraph routing (fake-only)
# --------------------------------------------------------------------------- #

def test_zorbing_overview_routes_to_service_knowledge():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    plan = _plan(workflow, "Tell me about Zorbing Ball.")
    assert (plan["intent"], plan["service_code"], plan["topic"], plan["selected_route"]) == (
        "service_overview", "zorbing_ball", "overview", "answer_service_knowledge",
    )


def test_zorbing_timings_map_to_operating_hours_and_duration_to_duration():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    timings = _plan(workflow, "What are the Zorbing Ball timings?")
    duration = _plan(workflow, "How long is Zorbing Ball?")
    assert (timings["intent"], timings["service_code"], timings["topic"], timings["selected_route"]) == (
        "service_topic", "zorbing_ball", "operating_hours", "answer_service_knowledge",
    )
    assert (duration["intent"], duration["service_code"], duration["topic"], duration["selected_route"]) == (
        "service_topic", "zorbing_ball", "duration", "answer_service_knowledge",
    )
    assert duration["requires_handover"] is False


def test_kids_bumper_boat_routes_overview_to_overview_and_duration_to_duration():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    overview = _plan(workflow, "Tell me about Kids Bumper Boat.")
    duration = _plan(workflow, "How long is Kids Bumper Boat?")
    assert (overview["intent"], overview["service_code"], overview["topic"]) == (
        "service_overview", "kids_bumper_boat", "overview",
    )
    assert (duration["intent"], duration["service_code"], duration["topic"]) == (
        "service_topic", "kids_bumper_boat", "duration",
    )


def test_zorbing_availability_and_kids_bumper_booking_are_human_handover():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    availability = _plan(workflow, "Is Zorbing Ball available today?")
    booking = _plan(workflow, "Can I book Kids Bumper Boat?")
    assert availability["requires_handover"] is True
    assert workflow.route({**_state("Is Zorbing Ball available today?"), **availability}) == "handover_to_sales"
    assert booking["requires_handover"] is True
    assert workflow.route({**_state("Can I book Kids Bumper Boat?"), **booking}) == "handover_to_sales"


class _ZorbingKnowledge:
    def __init__(self):
        self.calls = []

    def answer_service_details(self, question, service_name, service_code, **kwargs):
        self.calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
        if kwargs.get("detail_mode") == "duration":
            return KnowledgeDraft(
                "This activity is included in H2O Playpark full-day access from 10:00 AM to 6:30 PM. "
                "The access window does not mean one continuous activity session. "
                "Individual turn or session duration is not separately confirmed.",
                "active/services/zorbing_ball.md", 0.9, False, "Duration",
                1, "zorbing_ball", ("Duration",),
            )
        return KnowledgeDraft(
            "H2O Playpark access is available from 10:00 AM to 6:30 PM, subject to weather and operational conditions.",
            "active/services/zorbing_ball.md", 0.9, False, "Operating Hours",
            1, "zorbing_ball", ("Operating Hours",),
        )


def test_zorbing_duration_question_uses_duration_knowledge():
    knowledge = _ZorbingKnowledge()
    workflow = RaipurLangGraphWorkflow(_Conversation(), knowledge=knowledge)
    result = workflow.invoke(
        _state("How long is Zorbing Ball?"),
        message=SimpleNamespace(content="How long is Zorbing Ball?"),
        customer={"id": "customer"}, conversation={"id": "conversation"}, source_message_id="message",
    )
    assert result.safe_metadata["service_code"] == "zorbing_ball"
    assert result.safe_metadata["topic"] == "duration"
    assert knowledge.calls == []
    assert "full-day access" in result.draft_text
    assert "not separately confirmed" not in result.draft_text.casefold()
    assert "does not mean" not in result.draft_text
    assert "5 to 10 minutes" not in result.draft_text.casefold()
