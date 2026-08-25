"""Production-gated understanding merge and sales-progression tests."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from app.services.booking_enquiries import BookingDetails
from app.services.raipur.context_state import apply_customer_understanding, set_catalogue_context
from app.services.raipur.customer_understanding import CustomerUnderstanding, CustomerUnderstandingService
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
from app.services.raipur.sales_state import SalesStage
from app.services.raipur.sales_agent import SalesAgent
from app.services.raipur.sales_response_composer import SalesResponseComposer
from app.services.latency import LatencyTrace, latency_openai_call, use_latency_trace
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES
from app.services.raipur_langgraph import RaipurLangGraphWorkflow
from app.services.raipur_inbound_orchestrator import _context_from_record, _context_to_record


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"id": item.slug, "name": item.name, "is_active": True} for item in APPROVED_RAIPUR_SERVICES]


class _Knowledge:
    def answer_service_details(self, _question, service_name, service_code, **kwargs):
        topic = kwargs["detail_mode"]
        text = "Party Boat Celebration lasts 2 hours." if topic == "duration" else f"{service_name} is an approved service."
        heading = "Duration" if topic == "duration" else "Experience Overview"
        return KnowledgeDraft(text, f"{service_code}.md", .9, False, heading, 1, service_code, (heading,))


class _Fallback:
    def __init__(self): self.calls = 0
    def respond(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(valid=True, text="Please tell me what Raipur experience you would like.")


class _Extractor:
    def __init__(self): self.calls = []
    def __call__(self, message, context):
        self.calls.append((message, context))
        text = message.casefold()
        if "prime minister" in text:
            return {"intent": "general", "confidence": .98}
        if "private" in text:
            base = {"intent": "celebration", "preference": "private_intimate", "confidence": .97}
            if "anniversary" in text:
                base.update(occasion="anniversary", guest_count=8, planned_date_text="15 August")
            return base
        if "water fun" in text:
            return {"intent": "activity_discovery", "preference": "water_adventure", "confidence": .9}
        if "calm" in text or "relaxing" in text:
            return {"intent": "activity_discovery", "preference": "relaxed", "confidence": .93}
        if "actually 14" in text:
            return {"intent": "celebration", "guest_count": 14, "confidence": .98}
        if "birthday" in text:
            value = {"intent": "celebration", "occasion": "birthday", "confidence": .97}
            if "12" in text: value["guest_count"] = 12
            if "13/08/2026" in text: value["planned_date_text"] = "13/08/2026"
            return value
        return {"intent": "unknown", "confidence": 0}


def _context(*, guests=None, planned=None, pending=None, preference=None, activity=False):
    slots = {"occasion": "birthday"}
    if preference: slots["celebration_preference"] = preference
    context = ConversationContext(
        BookingDetails(None, None, planned, None, None, None, guests),
        pending_field=pending,
        active_topic="activity_catalogue" if activity else "celebration_catalogue",
        active_entity_type="catalogue",
        active_entity_name="activity" if activity else "celebration",
        pending_action=None if activity else "celebration_sales",
        pending_slots=slots,
        sales_stage=SalesStage.QUALIFYING,
    )
    return context


def _state(message, language="en"):
    return {
        "message_id": "m", "conversation_id": "c", "customer_id": "u",
        "customer_message": message, "normalized_message": message.casefold(), "language": language,
        "location_code": "raipur", "previous_service_code": None, "previous_topic": None,
        "intent": None, "entity_type": "unknown", "service_code": None, "topic": None,
        "use_previous_service": False, "requires_handover": False, "handover_reason": None,
        "selected_route": None, "answer_source": None, "validation_errors": [],
        "plan_consistency_repaired": False, "invocation_id": "i", "draft_response": None,
        "validation_status": "pending", "error": None, "route": None,
    }


def _turn(workflow, message, context=None, language="en"):
    return workflow.invoke(
        _state(message, language), message=SimpleNamespace(content=message),
        customer={"id": "u"}, conversation={"id": "c", "location_id": "raipur"},
        source_message_id="m", current_state=context,
    )


def _workflow(extractor=None, fallback=None, sales_agent=None, sales_composer=None):
    return RaipurLangGraphWorkflow(
        knowledge=_Knowledge(), services=_Services(), conversational_fallback=fallback,
        customer_understanding=CustomerUnderstandingService(extractor or _Extractor()),
        understanding_enabled=True,
        sales_agent=sales_agent,
        sales_response_composer=sales_composer,
    )


def test_multifact_celebration_uses_one_combined_agent_not_two_model_services():
    extractor = _Extractor(); agent_calls = []; composer_calls = []
    agent = SalesAgent(lambda brief: agent_calls.append(brief) or {
        "reply": "Party Boat Celebration is an approved option for your birthday. What date are you planning?",
        "intent": "celebration", "occasion": "birthday", "guest_count": 12,
        "preference": "lively_party", "language": "en", "confidence": .98,
        "asked_for": "preferred_date",
    })
    result = _turn(_workflow(
        extractor, sales_agent=agent,
        sales_composer=SalesResponseComposer(lambda brief: composer_calls.append(brief) or "unused"),
    ), "birthday celebration for 12 people, something lively")
    assert len(agent_calls) == 1 and extractor.calls == [] and composer_calls == []
    assert result.context.details.total_guests == 12
    assert result.context.pending_slots["occasion"] == "birthday"
    assert result.context.pending_slots["celebration_preference"] == "lively_party"
    assert result.safe_metadata["sales_agent_used"] is True


def test_activity_calm_preference_uses_one_combined_agent():
    extractor = _Extractor(); agent_calls = []; composer_calls = []
    agent = SalesAgent(lambda brief: agent_calls.append(brief) or {
        "reply": "Here are the approved water activity options for a calmer experience.",
        "intent": "activity_discovery", "preference": "relaxed",
        "language": "en", "confidence": .94,
    })
    result = _turn(_workflow(
        extractor, sales_agent=agent,
        sales_composer=SalesResponseComposer(lambda brief: composer_calls.append(brief) or "unused"),
    ), "I want something calm", set_catalogue_context(_context(), "activity").updated_context)
    assert len(agent_calls) == 1 and extractor.calls == [] and composer_calls == []
    assert result.context.pending_slots["preference"] == "relaxed"
    assert result.safe_metadata["sales_agent_used"] is True


def test_failed_combined_agent_uses_deterministic_response_without_model_cascade():
    extractor = _Extractor(); composer_calls = []
    result = _turn(_workflow(
        extractor, sales_agent=SalesAgent(lambda _brief: {"reply": "Rs 100 confirmed", "confidence": .9}),
        sales_composer=SalesResponseComposer(lambda brief: composer_calls.append(brief) or "unused"),
    ), "birthday celebration for 12 people, something lively")
    assert extractor.calls == [] and composer_calls == []
    assert result.safe_metadata["sales_agent_fallback"] is True
    assert "Floating Gazebo" in result.draft_text


def test_combined_route_records_one_logical_call_and_only_sales_agent_time():
    def respond(_brief):
        with latency_openai_call("sales_agent", "test-model"):
            return {
                "reply": "Party Boat Celebration is an approved birthday option.",
                "intent": "celebration", "occasion": "birthday", "guest_count": 12,
                "preference": "lively_party", "confidence": .98,
            }

    trace = LatencyTrace()
    with use_latency_trace(trace):
        _turn(_workflow(sales_agent=SalesAgent(respond)), "birthday celebration for 12 people, something lively")
    assert trace.counters["logical_openai_calls"] == 1
    assert trace.value("sales_agent") >= 0
    assert trace.value("customer_understanding") == 0
    assert trace.value("sales_response_composer") == 0


@pytest.mark.parametrize("message,preference", (("private", "private_intimate"), ("lively", "lively_party"), ("relaxed", "relaxed")))
def test_active_celebration_preference_uses_one_combined_agent(message, preference):
    extractor = _Extractor(); calls = []
    agent = SalesAgent(lambda _brief: calls.append(message) or {
        "reply": "Here are the approved celebration options that match what you shared.",
        "intent": "celebration", "preference": preference, "confidence": .96,
    })
    context = _context(guests=12, planned=date(2026, 8, 13), pending="celebration_preference")
    result = _turn(_workflow(extractor, sales_agent=agent), message, context)
    assert calls == [message] and extractor.calls == []
    assert result.context.pending_slots["celebration_preference"] == preference
    assert result.safe_metadata["sales_agent_used"] is True


def test_multifact_first_message_skips_guest_and_date_questions():
    result = _turn(_workflow(), "I want to celebrate my birthday with 12 people on 13/08/2026")
    assert result.context.pending_slots["occasion"] == "birthday"
    assert result.context.details.total_guests == 12
    assert result.context.details.preferred_date.isoformat() == "2026-08-13"
    assert result.context.pending_field == "celebration_preference"
    response = result.draft_text.casefold()
    assert "floating gazebo" in response and "private/intimate" in response
    assert "how many guests" not in response and "what date" not in response


def test_hinglish_multifact_shows_catalogue_and_asks_date_not_guests():
    result = _turn(_workflow(), "birthday ke liye kuch special karna hai, around 12 log honge", language="hinglish")
    assert result.context.pending_slots["occasion"] == "birthday"
    assert result.context.details.total_guests == 12
    assert result.context.pending_field == "preferred_date"
    assert "date" in result.draft_text.casefold()
    assert "kitne guests" not in result.draft_text.casefold()


def test_all_qualifiers_complete_without_duplicate_questions():
    result = _turn(_workflow(), "anniversary for 8 guests on 15 August, something private and intimate")
    assert result.context.pending_slots["occasion"] == "anniversary"
    assert result.context.pending_slots["celebration_preference"] == "private_intimate"
    assert result.context.details.total_guests == 8 and result.context.details.preferred_date is not None
    assert result.context.pending_field is None
    assert not any(term in result.draft_text.casefold() for term in ("how many guests", "what date", "would you prefer"))


def test_short_preference_and_guest_correction_merge_without_generic_fallback():
    fallback = _Fallback(); workflow = _workflow(fallback=fallback)
    preferred = _turn(workflow, "private and intimate", _context(guests=12, planned=date(2026, 8, 13), pending="celebration_preference"))
    assert preferred.context.pending_slots["celebration_preference"] == "private_intimate"
    assert preferred.context.pending_field is None and fallback.calls == 0

    corrected = _turn(workflow, "Actually 14 people", _context(guests=12, pending="preferred_date"))
    assert corrected.context.details.total_guests == 14
    assert corrected.context.pending_field == "preferred_date"
    assert fallback.calls == 0


def test_activity_catalogue_switch_clears_only_stale_celebration_routing_state():
    prior = _context(guests=23, planned=date(2026, 8, 13), pending="celebration_preference")
    switched = set_catalogue_context(prior, "activity").updated_context

    assert switched.active_topic == "activity_catalogue"
    assert switched.active_entity_name == "activity"
    assert switched.pending_action is None and switched.pending_field is None
    assert switched.details.total_guests == 23
    assert switched.details.preferred_date == date(2026, 8, 13)


def test_natural_calm_preference_is_extracted_and_used_for_activity_catalogue():
    result = _turn(
        _workflow(),
        "i am looking good and calm experience",
        set_catalogue_context(_context(), "activity").updated_context,
    )

    assert result.safe_metadata["understanding_invoked"] is True
    assert result.safe_metadata["customer_understanding"]["preference"] == "relaxed"
    assert result.context.pending_slots["preference"] == "relaxed"
    assert result.safe_metadata["graph_answer_source"] == "approved_activity_catalogue"
    assert "noted that preference" not in result.draft_text.casefold()


def test_interruption_and_restricted_policy_preserve_precedence_and_state():
    extractor = _Extractor(); workflow = _workflow(extractor)
    context = _context(guests=12, pending="preferred_date")
    duration = _turn(workflow, "How long is Party Boat Celebration?", context)
    assert "2 hours" in duration.draft_text
    assert duration.context.details.total_guests == 12
    assert duration.context.pending_slots["occasion"] == "birthday"

    pricing = _turn(workflow, "what will it cost?", context)
    booking = _turn(workflow, "I want to book", context)
    assert pricing.detected_intent == "pricing" and pricing.human_handover_required
    assert booking.detected_intent == "booking" and booking.human_handover_required
    assert extractor.calls == []


def test_natural_activity_preference_is_stored_without_inventing_service():
    fallback = _Fallback(); workflow = _workflow(fallback=fallback)
    result = _turn(workflow, "water fun chahiye", _context(activity=True), "hinglish")
    assert result.context.pending_slots["preference"] == "water_adventure"
    assert result.context.last_service_code is None
    assert result.detected_intent == "activity_service_list"
    assert result.safe_metadata["graph_answer_source"] == "approved_activity_catalogue"
    assert "noted that preference" not in result.draft_text.casefold()
    assert fallback.calls == 0


def test_unrelated_question_is_not_consumed_as_a_sales_slot():
    fallback = _Fallback(); workflow = _workflow(fallback=fallback)
    context = _context(guests=12, pending="celebration_preference")
    result = _turn(workflow, "Who is the prime minister of Japan?", context)
    assert result.context.pending_slots.get("celebration_preference") is None
    assert result.context.details.total_guests == 12
    assert result.detected_intent != "customer_understanding_update"


def test_central_merge_preserves_known_values_and_accepts_explicit_corrections():
    context = _context(guests=12, pending="preferred_date")
    date_only = apply_customer_understanding(
        context,
        CustomerUnderstanding(intent="celebration", planned_date_text="15 August", confidence=.9),
    )
    assert date_only.details.total_guests == 12 and date_only.details.preferred_date is not None
    corrected = apply_customer_understanding(
        date_only,
        CustomerUnderstanding(intent="celebration", guest_count=14, confidence=.9),
    )
    assert corrected.details.total_guests == 14


def test_merged_multifact_state_round_trips_through_webhook_persistence():
    merged = apply_customer_understanding(
        ConversationContext(BookingDetails(None, None, None, None, None, None, None)),
        CustomerUnderstanding(
            intent="celebration", occasion="birthday", guest_count=12,
            planned_date_text="13/08/2026", preference="private_intimate", confidence=.98,
        ),
    )
    restored, expired = _context_from_record(_context_to_record(merged), 120)
    assert expired is False
    assert restored.details.total_guests == 12
    assert restored.details.preferred_date.isoformat() == "2026-08-13"
    assert restored.pending_slots["occasion"] == "birthday"
    assert restored.pending_slots["celebration_preference"] == "private_intimate"


@pytest.mark.parametrize("message", (
    "Hi", "Where is Entartica Raipur?", "What is Raipur timing?",
    "Tell me about Jet Ski", "Party Boat duration?", "What is the price?",
))
def test_obvious_deterministic_fast_paths_do_not_call_understanding(message):
    extractor = _Extractor()
    workflow = _workflow(extractor)
    workflow.plan_message({**_state(message), "_runtime": {"current_state": None}})
    assert extractor.calls == []
