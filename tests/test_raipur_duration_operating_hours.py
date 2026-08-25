"""Raipur duration and operating-hours knowledge matrix.

These tests encode the approved final behaviour:

* H2O Playpark activities have no individually confirmed session duration.
  Their duration answer is the full-day access window; timing questions map
  to ``operating_hours`` and duration questions map to ``duration``.
* One-Time Access rides keep the approved 5 to 10 minute duration.
* Celebrations have starting durations (30 minutes to 2 hours) and operate
  from 10:00 AM to 9:00 PM.
* Venue-level duration/timing questions (no specific service) use a
  deterministic venue answer.

All tests are offline: local documents and fake repositories only.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.rag.raipur_ingestion import build_plan
from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.services.raipur.service_resolver import resolve_service
from app.services.raipur.topic_resolver import resolve_topic
from app.services.raipur_answers import RaipurAnswer
from app.services.raipur_langgraph import RaipurLangGraphWorkflow
from app.services.raipur.response_models import KnowledgeDraft
from app.services.raipur_services import normalize_service_text

ROOT = Path(__file__).resolve().parents[1]

H2O_CODES = (
    "kayaking", "aqua_cycle", "water_bike", "bumper_boat",
    "kids_paddle_boat", "zorbing_ball", "kids_bumper_boat",
)
CELEBRATION_CODES = (
    "party_boat_celebration", "houseboat_celebration",
    "pontoon_celebration", "jetty_gazebo", "floating_gazebo",
)
ONE_TIME_CODES = ("pontoon_boat_ride", "jet_ski_ride", "speed_boat_ride", "inflatable_sofa_ride")


def _section_text(document, heading):
    wanted = re.sub(r"[^a-z0-9]+", " ", heading.casefold()).strip()
    for section in document.sections:
        if re.sub(r"[^a-z0-9]+", " ", section.heading.casefold()).strip() == wanted:
            return section.text
    return ""


def _documents_by_code():
    plan, errors = build_plan(ROOT)
    assert not errors, errors
    return {row.document.metadata["service_code"]: row.document for row in plan if row.document is not None}


# --------------------------------------------------------------------------- #
# Document matrix
# --------------------------------------------------------------------------- #

def test_h2o_playpark_docs_use_approved_duration_and_operating_hours():
    docs = _documents_by_code()
    for code in H2O_CODES:
        access = _section_text(docs[code], "Access Type").casefold()
        normalized_access = access.replace("playpark", "play park")
        assert all(term in normalized_access for term in ("h2o", "play park", "access"))
        assert "one-time access" not in access
        duration = _section_text(docs[code], "Duration")
        normalized_duration = duration.casefold().replace("playpark", "play park")
        assert all(term in normalized_duration for term in ("h2o", "play park", "access"))
        assert "10:00 am to 6:30 pm" in normalized_duration
        assert "does not mean" in duration
        assert "not separately confirmed" in duration
        operating = _section_text(docs[code], "Operating Hours")
        assert "10:00 AM to 6:30 PM" in operating
        assert "subject to weather" in operating


def test_h2o_playpark_docs_have_no_legacy_access_hours_heading():
    docs = _documents_by_code()
    for code in H2O_CODES:
        assert _section_text(docs[code], "H2O Playpark Access Hours") == ""


def test_h2o_playpark_docs_never_claim_five_to_ten_minutes():
    docs = _documents_by_code()
    for code in H2O_CODES:
        text = docs[code].text.casefold()
        assert "5 to 10 minutes" not in text
        assert "5\u201310 minutes" not in text
        assert "5-10 minutes" not in text


def test_celebration_docs_keep_starting_durations_and_add_operating_hours():
    docs = _documents_by_code()
    expected = {
        "party_boat_celebration": "2 hours",
        "houseboat_celebration": "30 minutes",
        "pontoon_celebration": "30 minutes",
        "jetty_gazebo": "2 hours",
        "floating_gazebo": "2 hours",
    }
    for code in CELEBRATION_CODES:
        duration = _section_text(docs[code], "Duration")
        assert expected[code] in duration
        assert "5 to 10 minutes" not in duration
        assert "after confirmation" in duration
        assert "not automatically included" in duration
        operating = _section_text(docs[code], "Operating Hours")
        assert "10:00 AM to 9:00 PM" in operating
        assert "subject to weather" in operating


def test_one_time_ride_docs_keep_five_to_ten_minute_duration():
    docs = _documents_by_code()
    for code in ONE_TIME_CODES:
        access = _section_text(docs[code], "Access Type").casefold()
        assert "one-time access" in access
        assert "does not mean unlimited repeat use" in access
        duration = _section_text(docs[code], "Duration")
        assert "5 to 10 minutes" in duration
        assert "full-day access" not in duration
        operating = _section_text(docs[code], "Operating Hours")
        assert "10:00 AM to 6:30 PM" in operating
        assert "subject to weather" in operating


def test_general_document_distinguishes_h2o_full_day_from_one_time_durations():
    docs = _documents_by_code()
    text = docs["raipur_general"].text
    non_motorised = text.split("### Non-Motorised Water Activities", 1)[1].split("### Celebration Experiences", 1)[0]
    for activity in ("Aqua Cycle", "Water Bike", "Kayaking", "Bumper Boat", "Kids Paddle Boat", "Aqua Roller", "Zorbing Ball"):
        line = next(line.strip() for line in non_motorised.splitlines() if line.strip().startswith(f"- **{activity}"))
        assert "5 to 10" not in line
    pontoon_line = next(line.strip() for line in non_motorised.splitlines() if line.strip().startswith("- **Pontoon Boat Ride"))
    assert "5 to 10" in pontoon_line
    h2o_section = text.split("**H2O Playpark**", 1)[1].split("## Operating Hours", 1)[0]
    assert "does not mean" in h2o_section
    assert "not separately confirmed" in h2o_section
    assert "5 to 10 minutes" not in h2o_section
    faq_answer = text.split("### How long do water sport sessions last?", 1)[1].split("### What should guests wear?", 1)[0]
    assert "5 to 10 minutes" in faq_answer
    assert "full-day access" in faq_answer and "10:00 AM to 6:30 PM" in faq_answer
    assert "celebration" in faq_answer.casefold()


# --------------------------------------------------------------------------- #
# Topic resolution matrix
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("What is the duration of Party Boat?", "duration"),
        ("How long is Party Boat Celebration?", "duration"),
        ("What is the duration of Bumper Boat?", "duration"),
        ("How long is Kayaking?", "duration"),
        ("Party Boat ka duration kitna hai?", "duration"),
        ("Party Boat kitni der ka hai?", "duration"),
        ("Kayak ka duration kya hai?", "duration"),
        ("Kayak kitni der ke liye hai?", "duration"),
        ("Jet Ski kitne minute ki hai?", "duration"),
        ("\u092a\u093e\u0930\u094d\u091f\u0940 \u092c\u094b\u091f \u0915\u093f\u0924\u0928\u0940 \u0926\u0947\u0930 \u0915\u0940 \u0939\u0948?", "duration"),
        ("\u0915\u092f\u093e\u0915 \u0915\u093f\u0924\u0928\u0940 \u0926\u0947\u0930 \u0915\u0947 \u0932\u093f\u090f \u0939\u0948?", "duration"),
        ("\u091c\u0947\u091f \u0938\u094d\u0915\u0940 \u0915\u093f\u0924\u0928\u0947 \u092e\u093f\u0928\u091f \u0915\u0940 \u0939\u0948?", "duration"),
        ("What is the duartion of Jet Ski?", "duration"),
        ("What is the durtion of Jet Ski?", "duration"),
        ("Party Boat timing?", "operating_hours"),
        ("What are the operating hours of Jet Ski?", "operating_hours"),
        ("Party Boat ka timing kya hai?", "operating_hours"),
        ("Party Boat kab se kab tak chalta hai?", "operating_hours"),
        ("Kayak ka timing kya hai?", "operating_hours"),
        ("Celebration kab se kab tak available hai?", "operating_hours"),
        ("\u092a\u093e\u0930\u094d\u091f\u0940 \u092c\u094b\u091f \u0915\u093e \u0938\u092e\u092f \u0915\u094d\u092f\u093e \u0939\u0948?", "operating_hours"),
        ("\u092a\u093e\u0930\u094d\u091f\u0940 \u092c\u094b\u091f \u0915\u093f\u0924\u0928\u0947 \u092c\u091c\u0947 \u0938\u0947 \u0915\u093f\u0924\u0928\u0947 \u092c\u091c\u0947 \u0924\u0915 \u0939\u0948?", "operating_hours"),
        ("\u0915\u092f\u093e\u0915 \u0915\u093e \u0938\u092e\u092f \u0915\u094d\u092f\u093e \u0939\u0948?", "operating_hours"),
        ("\u091c\u0932 \u0917\u0924\u093f\u0935\u093f\u0927\u093f\u092f\u093e\u0901 \u0915\u093f\u0924\u0928\u0947 \u092c\u091c\u0947 \u0924\u0915 \u091a\u0932\u0924\u0940 \u0939\u0948\u0902?", "operating_hours"),
        ("\u0938\u0947\u0932\u093f\u092c\u094d\u0930\u0947\u0936\u0928 \u0938\u0947\u0935\u093e\u090f\u0901 \u0915\u093f\u0924\u0928\u0947 \u092c\u091c\u0947 \u0924\u0915 \u091a\u0932\u0924\u0940 \u0939\u0948\u0902?", "operating_hours"),
        ("Zorbing Ball kab tak chalta hai?", "operating_hours"),
        ("What are the opening hours of Raipur?", "operating_hours"),
        ("What are the closing hours of Raipur?", "operating_hours"),
        ("What time does Entartica open?", "operating_hours"),
        ("What time does Entartica close?", "operating_hours"),
        ("Raipur ka timing kya hai?", "operating_hours"),
        ("kab se kab tak open hai?", "operating_hours"),
        ("कितने बजे खुलता है?", "operating_hours"),
        ("रायपुर का समय क्या है?", "operating_hours"),
    ],
)
def test_duration_and_timing_topics_resolve_across_languages_and_typos(question, topic):
    result = resolve_topic(question)
    assert result.matched
    assert result.topic == topic


# --------------------------------------------------------------------------- #
# Service normalization and resolution matrix
# --------------------------------------------------------------------------- #

def test_normalize_service_text_corrects_known_typos():
    assert normalize_service_text("party baot") == "party boat"
    assert normalize_service_text("kayk") == "kayak"
    assert normalize_service_text("aqua cyle") == "aqua cycle"
    assert normalize_service_text("bumber") == "bumper"
    assert normalize_service_text("bumber boat") == "bumper boat"


def test_service_resolution_covers_common_typos():
    assert resolve_service("Tell me about party baot").service_code == "party_boat_celebration"
    assert resolve_service("kayk ka duration kya hai").service_code == "kayaking"
    assert resolve_service("aqua cyle ki details").service_code == "aqua_cycle"
    assert resolve_service("bumber boat").service_code == "bumper_boat"


# --------------------------------------------------------------------------- #
# LangGraph routing (fake-only)
# --------------------------------------------------------------------------- #

class _Conversation:
    def process(self, *_args, **_kwargs):
        return SimpleNamespace(response_valid=True, draft_text="Approved customer response")


def _state(message: str, previous_service_code=None, previous_topic=None):
    return {
        "message_id": "message", "conversation_id": "conversation", "customer_id": "customer",
        "customer_message": message, "normalized_message": message.casefold(), "language": "en",
        "location_code": "raipur", "previous_service_code": previous_service_code,
        "previous_topic": previous_topic, "intent": "unknown",
        "entity_type": "unknown", "service_code": None, "topic": None, "use_previous_service": False,
        "requires_handover": False, "handover_reason": None, "answer_source": "none",
        "draft_response": None, "validation_status": "pending", "error": None, "route": "",
    }


def _plan(workflow, message, previous_service_code=None, previous_topic=None):
    return workflow.plan_message({**_state(message, previous_service_code, previous_topic), "_runtime": {"current_state": None}})


def test_h2o_duration_questions_map_to_duration_topic():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    cases = (
        ("How long is Zorbing Ball?", "zorbing_ball"),
        ("What is the duration of Kids Bumper Boat?", "kids_bumper_boat"),
        ("Kayak kitni der ki hai?", "kayaking"),
        ("Water Bike ka duration kya hai?", "water_bike"),
    )
    for message, code in cases:
        plan = _plan(workflow, message)
        assert (plan["intent"], plan["service_code"], plan["topic"], plan["selected_route"]) == (
            "service_topic", code, "duration", "answer_service_knowledge",
        )
        assert plan["requires_handover"] is False


def test_h2o_timing_questions_map_to_operating_hours_topic():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    cases = (
        ("What are the Zorbing Ball timings?", "zorbing_ball"),
        ("Kids Bumper Boat kab tak chalta hai?", "kids_bumper_boat"),
        ("Kayak ka timing kya hai?", "kayaking"),
    )
    for message, code in cases:
        plan = _plan(workflow, message)
        assert (plan["intent"], plan["service_code"], plan["topic"], plan["selected_route"]) == (
            "service_topic", code, "operating_hours", "answer_service_knowledge",
        )


def test_celebration_timing_questions_map_to_operating_hours():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    plan = _plan(workflow, "What are the Party Boat Celebration timings?")
    assert (plan["intent"], plan["service_code"], plan["topic"], plan["selected_route"]) == (
        "service_topic", "party_boat_celebration", "operating_hours", "answer_service_knowledge",
    )


def test_venue_level_duration_and_timing_questions_route_deterministically():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    cases = (
        ("How long do water rides last at Entartica Raipur?", "duration"),
        ("What are the ride timings?", "operating_hours"),
        ("How long do the activities last?", "duration"),
        ("What are the operating hours of the rides?", "operating_hours"),
    )
    for message, topic in cases:
        plan = _plan(workflow, message)
        assert (plan["intent"], plan["service_code"], plan["topic"], plan["selected_route"]) == (
            "venue_duration_timing", None, topic, "answer_venue_knowledge",
        )
        assert plan["use_previous_service"] is False


def test_venue_level_duration_question_overrides_previous_service_context():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    plan = _plan(workflow, "How long do the water rides last?", previous_service_code="jet_ski_ride")
    assert (plan["intent"], plan["service_code"], plan["topic"], plan["use_previous_service"]) == (
        "venue_duration_timing", None, "duration", False,
    )


def test_service_duration_followup_is_not_treated_as_venue_level():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    plan = _plan(workflow, "How long is it?", previous_service_code="jet_ski_ride")
    assert (plan["intent"], plan["service_code"], plan["topic"], plan["use_previous_service"]) == (
        "contextual_service_followup", "jet_ski_ride", "duration", True,
    )


def test_general_venue_timing_questions_route_deterministically():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    cases = (
        ("what is the opening hours of raipur?", "operating_hours"),
        ("what is the timing of raipur?", "operating_hours"),
        ("Raipur timings", "operating_hours"),
        ("what time does Entartica open?", "operating_hours"),
        ("what time does Entartica close?", "operating_hours"),
        ("Raipur ka timing kya hai?", "operating_hours"),
        ("kab se kab tak open hai?", "operating_hours"),
        ("रायपुर का समय क्या है?", "operating_hours"),
        ("कितने बजे खुलता है?", "operating_hours"),
    )
    for message, topic in cases:
        plan = _plan(workflow, message)
        assert (plan["intent"], plan["service_code"], plan["topic"], plan["selected_route"]) == (
            "venue_duration_timing", None, topic, "answer_venue_knowledge",
        )
        assert plan["use_previous_service"] is False
        assert plan["requires_handover"] is False


def test_venue_timing_confirmation_questions_route_deterministically():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    cases = (
        "isnt it 10 AM to 6:30 PM",
        "is it 10 to 6:30?",
        "timing is 10 AM to 6:30 PM right?",
        "10 se 6:30 tak hai na?",
        "क्या समय 10 से 6:30 है?",
    )
    for message in cases:
        plan = _plan(workflow, message, previous_topic="operating_hours")
        assert (plan["intent"], plan["service_code"], plan["topic"], plan["selected_route"]) == (
            "venue_timing_confirmation", None, "operating_hours", "answer_venue_knowledge",
        )
        assert plan["use_previous_service"] is False
        assert plan["requires_handover"] is False


def test_venue_timing_confirmation_without_prior_timing_turn_stays_safe():
    workflow = RaipurLangGraphWorkflow(_Conversation())
    plan = _plan(workflow, "isnt it 10 AM to 6:30 PM")
    assert plan["intent"] not in {"venue_timing_confirmation", "venue_duration_timing"}


def test_h2o_duration_answer_uses_duration_knowledge_and_never_operating_hours():
    class H2ODurationKnowledge:
        def __init__(self):
            self.calls = []

        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            return KnowledgeDraft(
                "This activity is included in H2O Playpark full-day access from 10:00 AM to 6:30 PM. "
                "The access window does not mean one continuous activity session. "
                "Individual turn or session duration is not separately confirmed.",
                "active/services/water_bike.md", 0.9, False, "Duration",
                1, "water_bike", ("Duration",),
            )

    knowledge = H2ODurationKnowledge()
    workflow = RaipurLangGraphWorkflow(_Conversation(), knowledge=knowledge)
    result = workflow.invoke(
        _state("How long is the Water Bike?"),
        message=SimpleNamespace(content="How long is the Water Bike?"),
        customer={"id": "customer"}, conversation={"id": "conversation"}, source_message_id="message",
    )
    assert result.safe_metadata["service_code"] == "water_bike"
    assert result.safe_metadata["topic"] == "duration"
    assert result.safe_metadata["selected_section_heading"] == "Duration"
    assert knowledge.calls == []
    assert "full-day access" in result.draft_text
    assert "does not mean" not in result.draft_text
    assert "5 to 10 minutes" not in result.draft_text.casefold()


# --------------------------------------------------------------------------- #
# Provider retrieval matrix
# --------------------------------------------------------------------------- #

def _settings():
    return SimpleNamespace(raipur_knowledge_min_confidence=.65)


def _candidate(score=.8, **extra):
    value = {
        'content': 'approved grounded text', 'source_filename': 'raipur.md', 'confidence': score,
        'metadata': {
            'location_code': 'raipur', 'customer_facing': True, 'is_active': True,
            'approval_status': 'approved', 'retrieval_priority': 'service_specific',
        },
    }
    value.update(extra)
    return value


def _provider(rows):
    return RaipurKnowledgeProvider(
        object(), _settings(),
        embed_query_fn=lambda q, s: [1],
        retrieve_candidates_fn=lambda c, v, limit: rows,
        answer_generator=lambda r, low_confidence: RaipurAnswer(r['content'], False, r['score'], (r['source_filename'],)),
    )


def test_provider_returns_h2o_duration_section_for_duration_and_operating_hours_for_timing():
    metadata = {
        'location_code': 'raipur', 'service_code': 'water_bike', 'customer_facing': True,
        'is_active': True, 'approval_status': 'approved', 'retrieval_priority': 'service_specific',
    }
    rows = [
        _candidate(.99, content='Water sports and ride activities generally operate between 10:00 AM and 6:30 PM, subject to weather and operational conditions.', metadata=metadata | {'section_heading': 'Operating Hours'}),
        _candidate(.70, content='This activity is included in H2O Playpark full-day access from 10:00 AM to 6:30 PM. The access window does not mean one continuous activity session. Individual turn or session duration is not separately confirmed.', metadata=metadata | {'section_heading': 'Duration'}),
    ]
    provider = _provider(rows)
    duration = provider.answer_service_details('How long is Water Bike?', 'Water Bike', 'water_bike', detail_mode='duration')
    timing = provider.answer_service_details('What are the Water Bike timings?', 'Water Bike', 'water_bike', detail_mode='operating_hours')
    assert duration.section_heading == 'Duration'
    assert 'full-day access' in duration.text and 'does not mean' not in duration.text
    assert '5 to 10 minutes' not in duration.text
    assert timing.section_heading == 'Operating Hours'
    assert '10:00 AM' in timing.text and '6:30 PM' in timing.text
    assert 'full-day access' not in timing.text
