"""Shadow-only structured customer-understanding regressions."""
from __future__ import annotations

from datetime import date

import pytest

from app.services.booking_enquiries import BookingDetails
from app.services.raipur.customer_understanding import (
    CustomerUnderstandingService,
    compact_understanding_context,
)
from app.services.raipur.response_models import ConversationContext
from app.services.raipur.sales_state import SalesStage
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


def _context(*, pending=None, celebration=False, guests=None, planned=None, service=None):
    return ConversationContext(
        BookingDetails(None, service[0] if service else None, planned, None, None, None, guests),
        pending_field=pending,
        last_service_name=service[0] if service else None,
        last_service_code=service[1] if service else None,
        active_entity_name="celebration" if celebration else None,
        pending_action="celebration_sales" if celebration else None,
        sales_stage=SalesStage.QUALIFYING if celebration else SalesStage.DISCOVERY,
    )


CASES = {
    "I want to celebrate my birthday": dict(intent="celebration", occasion="birthday", confidence=.96),
    "birthday ke liye kuch special karna hai, around 12 log honge": dict(intent="celebration", occasion="birthday", guest_count=12, confidence=.96),
    "we are 12 people coming on 15 August for anniversary": dict(intent="celebration", occasion="anniversary", guest_count=12, planned_date_text="15 August", confidence=.96),
    "muje celebration karvana he": dict(intent="celebration", confidence=.9),
    "one special event": dict(intent="celebration", confidence=.82),
    "corporate event": dict(intent="celebration", occasion="corporate", confidence=.92),
    "client event": dict(intent="celebration", occasion="client event", confidence=.9),
    "couple": dict(intent="celebration", preference="couple", confidence=.85),
    "water fun": dict(intent="activity_discovery", preference="water_adventure", confidence=.8),
    "12": dict(intent="celebration", guest_count=12, confidence=.98),
    "13/08/2026": dict(intent="celebration", planned_date_text="13/08/2026", confidence=.98),
    "Tell me about Jet Ski": dict(intent="service_question", service_mention="Jet Ski", topic="overview", confidence=.98),
    "Kayaking ka timing?": dict(intent="service_question", service_mention="Kayaking", topic="operating_hours", confidence=.98),
    "Party Boat ka duration kya hai?": dict(intent="service_question", service_mention="Party Boat", topic="duration", confidence=.98),
    "celebration price kya hai?": dict(intent="pricing", restricted_intent="pricing", confidence=.99),
    "book karna hai": dict(intent="booking", restricted_intent="booking", confidence=.99),
    "where is Entartica Raipur?": dict(intent="location", confidence=.99),
    "thank you": dict(intent="acknowledgement", confidence=.99),
    "hi": dict(intent="greeting", confidence=.99),
    "who is the prime minister of Japan?": dict(intent="general", confidence=.96),
    "birthday, 12 people, 15 August": dict(intent="celebration", occasion="birthday", guest_count=12, planned_date_text="15 August", confidence=.96),
    "anniversary for 8 guests tomorrow": dict(intent="celebration", occasion="anniversary", guest_count=8, planned_date_text="tomorrow", confidence=.93),
    "family ke saath aa rahe hain, 6 log hain": dict(intent="family_discovery", guest_count=6, preference="family", confidence=.9),
}


def _fake_extract(message, context):
    canonical = next(key for key in CASES if key.casefold() == message.casefold())
    value = dict(CASES[canonical])
    value.setdefault("language", "hinglish" if any(token in message.casefold() for token in (" kar", "kya", "log", "saath", "muje")) else "en")
    return value


@pytest.mark.parametrize(
    "message,context,expected",
    (
        ("I want to celebrate my birthday", None, {"intent": "celebration", "occasion": "birthday"}),
        ("birthday ke liye kuch special karna hai, around 12 log honge", None, {"intent": "celebration", "occasion": "birthday", "guest_count": 12}),
        ("we are 12 people coming on 15 August for anniversary", None, {"occasion": "anniversary", "guest_count": 12, "planned_date_text": "15 August"}),
        ("muje celebration karvana he", None, {"intent": "celebration"}),
        ("one special event", _context(celebration=True), {"intent": "celebration"}),
        ("corporate event", None, {"intent": "celebration", "occasion": "corporate"}),
        ("client event", _context(celebration=True), {"intent": "celebration", "occasion": "client event"}),
        ("couple", _context(pending="celebration_preference", celebration=True), {"preference": "couple"}),
        ("water fun", _context(pending="celebration_preference", celebration=True), {"preference": "water_adventure", "service_code": None}),
        ("12", _context(pending="total_guests", celebration=True), {"guest_count": 12}),
        ("13/08/2026", _context(pending="preferred_date", celebration=True, guests=12), {"planned_date_text": "13/08/2026", "guest_count": None}),
        ("Tell me about Jet Ski", None, {"intent": "service_question", "service_code": "jet_ski_ride", "topic": "overview"}),
        ("Kayaking ka timing?", None, {"service_code": "kayaking", "topic": "operating_hours"}),
        ("Party Boat ka duration kya hai?", None, {"service_code": "party_boat_celebration", "topic": "duration"}),
        ("celebration price kya hai?", None, {"restricted_intent": "pricing"}),
        ("book karna hai", None, {"restricted_intent": "booking"}),
        ("where is Entartica Raipur?", None, {"intent": "location", "service_code": None}),
        ("thank you", None, {"intent": "acknowledgement"}),
        ("hi", None, {"intent": "greeting"}),
        ("who is the prime minister of Japan?", None, {"intent": "general", "service_code": None}),
    ),
)
def test_representative_structured_meanings(message, context, expected):
    result = CustomerUnderstandingService(_fake_extract).understand(message, context)
    for field, value in expected.items():
        assert getattr(result, field) == value


@pytest.mark.parametrize("message", ("birthday, 12 people, 15 August", "anniversary for 8 guests tomorrow", "family ke saath aa rahe hain, 6 log hain"))
def test_multiple_current_message_facts_are_kept(message):
    result = CustomerUnderstandingService(_fake_extract).understand(message)
    expected = CASES[message]
    assert result.guest_count == expected["guest_count"]
    if "planned_date_text" in expected:
        assert result.planned_date_text == expected["planned_date_text"]


@pytest.mark.parametrize(
    "message,language",
    (("I want a birthday celebration", "en"), ("mujhe birthday celebration karna hai", "hinglish"), ("मुझे जन्मदिन मनाना है", "hi")),
)
def test_equivalent_celebration_meaning_supports_three_languages(message, language):
    result = CustomerUnderstandingService(
        lambda *_: {"intent": "celebration", "occasion": "birthday", "language": language, "confidence": .95}
    ).understand(message)
    assert result.intent == "celebration" and result.occasion == "birthday"
    assert result.language == language


def test_compact_context_is_interpretive_only_and_not_copied_to_output():
    context = _context(
        pending="preferred_date", celebration=True, guests=12,
        planned=None, service=("Party Boat Celebration", "party_boat_celebration"),
    )
    seen = {}

    def extractor(_message, compact):
        seen.update(compact)
        return {"intent": "celebration", "planned_date_text": "15 August", "confidence": .95}

    result = CustomerUnderstandingService(extractor).understand("15 August", context)
    assert seen == compact_understanding_context(context)
    assert seen["known_guest_count"] == 12
    assert result.planned_date_text == "15 August"
    assert result.guest_count is None
    assert result.service_code is None


def test_unknown_model_service_is_never_accepted_as_a_canonical_code():
    result = CustomerUnderstandingService(
        lambda *_: {"intent": "service_question", "service_mention": "Yacht", "confidence": .8}
    ).understand("Tell me about the Yacht")
    assert result.service_code is None


@pytest.mark.parametrize("failure", (RuntimeError("timeout"), {"intent": "not-an-intent"}))
def test_extraction_failure_returns_safe_unknown(failure):
    def extractor(*_args):
        if isinstance(failure, Exception):
            raise failure
        return failure

    result = CustomerUnderstandingService(extractor).understand("birthday party")
    assert result.intent == "unknown" and result.service_code is None and result.confidence == 0


def _graph_state(message):
    return {
        "message_id": "m", "conversation_id": "c", "customer_id": "u",
        "customer_message": message, "normalized_message": message.casefold(), "language": "en",
        "location_code": "raipur", "previous_service_code": None, "previous_topic": None,
        "intent": None, "entity_type": "unknown", "service_code": None, "topic": None,
        "use_previous_service": False, "requires_handover": False, "handover_reason": None,
        "selected_route": None, "answer_source": None, "validation_errors": [],
        "plan_consistency_repaired": False, "invocation_id": "i", "draft_response": None,
        "validation_status": "pending", "error": None, "route": None,
    }


def test_shadow_understanding_is_opt_in_and_never_changes_the_route():
    service = CustomerUnderstandingService(_fake_extract)
    enabled = RaipurLangGraphWorkflow(customer_understanding=service, understanding_shadow_enabled=True)
    disabled = RaipurLangGraphWorkflow(customer_understanding=service, understanding_shadow_enabled=False)
    runtime = {"current_state": None}
    enabled_plan = enabled.plan_message({**_graph_state("I want to celebrate my birthday"), "_runtime": runtime})
    disabled_plan = disabled.plan_message({**_graph_state("I want to celebrate my birthday"), "_runtime": runtime})
    assert enabled_plan["intent"] == disabled_plan["intent"] == "celebration_service_list"
    assert enabled_plan["selected_route"] == disabled_plan["selected_route"] == "answer_catalogue"
    assert enabled_plan["customer_understanding_shadow"]["intent"] == "celebration"
    assert "customer_understanding_shadow" not in disabled_plan
