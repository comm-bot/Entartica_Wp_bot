"""Phase 4.2 service confirmation and grounded sales-composition regressions."""
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from app.services.booking_enquiries import BookingDetails
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
from app.services.raipur.sales_response_composer import ResponseGoal, SalesResponseBrief, SalesResponseComposer
from app.services.raipur.sales_state import SalesStage
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


class _Knowledge:
    def answer_service_details(self, _question, service_name, _code, detail_mode="overview"):
        text = f"{service_name} offers a scenic on-water celebration experience."
        if detail_mode == "duration": text = f"{service_name} has a starting duration of 2 hours."
        return KnowledgeDraft(text, f"{service_name}.md", .9, False, "Experience Overview", 1)


class _Services:
    def list_active_for_location(self, _location):
        return [
            {"name":"Floating Gazebo","slug":"floating-gazebo","is_active":True},
            {"name":"Houseboat Celebration","slug":"houseboat-celebration","is_active":True},
            {"name":"Jetty Gazebo","slug":"jetty-gazebo","is_active":True},
            {"name":"Party Boat Celebration","slug":"party-boat-celebration","is_active":True},
            {"name":"Pontoon Celebration","slug":"pontoon-celebration","is_active":True},
        ]


def _state(message, language="en"):
    return {"message_id":"m","conversation_id":"c","customer_id":"u","customer_message":message,"normalized_message":message.casefold(),"language":language,"location_code":"raipur","previous_service_code":None,"previous_topic":None,"intent":None,"entity_type":"unknown","service_code":None,"topic":None,"use_previous_service":False,"requires_handover":False,"handover_reason":None,"selected_route":None,"answer_source":None,"validation_errors":[],"plan_consistency_repaired":False,"invocation_id":"i","draft_response":None,"validation_status":"pending","error":None,"route":None}


def _turn(workflow, message, context=None, language="en"):
    return workflow.invoke(_state(message, language), message=SimpleNamespace(content=message), customer={"id":"u"}, conversation={"id":"c","location_id":"raipur"}, source_message_id="m", current_state=context)


def _base_context(**changes):
    value = ConversationContext(BookingDetails(None, None, None, None, None, None, None, special_requirements_collected=False))
    return replace(value, **changes)


def test_fuzzy_service_clarification_clears_stale_party_boat_then_yes_opens_floating_overview():
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(), services=_Services())
    stale = _base_context(last_service_name="Party Boat Celebration", last_service_code="party_boat_celebration", active_topic="overview")
    clarification = _turn(workflow, "please tell me about flating gazebi", stale)
    assert clarification.context.pending_service_code == "floating_gazebo"
    assert clarification.context.last_service_code is None
    assert "floating gazebo" in clarification.draft_text.casefold()
    assert "party boat" not in clarification.draft_text.casefold()

    confirmed = _turn(workflow, "yes", clarification.context)
    assert confirmed.context.last_service_code == "floating_gazebo"
    assert confirmed.context.pending_service_code is None
    assert "floating gazebo" in confirmed.draft_text.casefold()
    assert confirmed.detected_intent == "service_overview"


@pytest.mark.parametrize("reply", ["yes", "yeah", "yep", "correct", "right", "that's right", "haan", "ha", "hanji", "ji", "yes that's it"])
def test_contextual_service_affirmations_confirm_only_the_pending_candidate(reply):
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(), services=_Services())
    pending = _base_context(pending_service_code="floating_gazebo", pending_question_type="yes_no", pending_action="provide_service_details")
    result = _turn(workflow, reply, pending)
    assert result.context.last_service_code == "floating_gazebo"
    assert result.context.pending_service_code is None


@pytest.mark.parametrize("reply", ["no", "nope", "nahi", "nahin", "not that one"])
def test_contextual_service_rejection_clears_candidate_without_selecting_it(reply):
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(), services=_Services())
    pending = _base_context(last_service_name="Party Boat Celebration", last_service_code="party_boat_celebration", pending_service_code="floating_gazebo", pending_question_type="yes_no", pending_action="provide_service_details")
    result = _turn(workflow, reply, pending)
    assert result.context.pending_service_code is None
    assert result.context.last_service_code == "party_boat_celebration"
    assert "floating gazebo" not in result.draft_text.casefold()


def test_composer_receives_bounded_approved_brief_and_no_raw_governance():
    seen = []
    composer = SalesResponseComposer(lambda brief: seen.append(brief) or "Party Boat Celebration is a lively on-water celebration 🎉")
    brief = SalesResponseBrief(ResponseGoal.SERVICE_OVERVIEW, "en", service_code="party_boat_celebration", service_name="Party Boat Celebration", approved_facts=("A lively on-water celebration.",))
    result = composer.compose(brief)
    assert result.valid and seen == [brief]
    supplied_evidence = repr((seen[0].approved_facts, seen[0].approved_options)).casefold()
    assert "yacht" not in supplied_evidence and "price" not in supplied_evidence and "availability" not in supplied_evidence
    assert "facts to verify" not in supplied_evidence and "source conflict" not in supplied_evidence

    unsafe = SalesResponseComposer(lambda _brief: "You can also book a Yacht today.").compose(brief)
    assert not unsafe.valid


def test_composer_failure_has_single_deterministic_fallback_and_sales_brief_tracks_state():
    briefs = []
    composer = SalesResponseComposer(lambda brief: briefs.append(brief) or None)
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(), services=_Services(), sales_response_composer=composer)
    context = _base_context(active_topic="celebration_catalogue", active_entity_type="catalogue", active_entity_name="celebration", pending_action="celebration_sales", pending_field="preferred_date", details=BookingDetails(None, None, None, None, None, None, 12, special_requirements_collected=False), pending_slots={"occasion":"birthday"}, sales_stage=SalesStage.QUALIFYING)
    result = _turn(workflow, "13/08/2026", context)
    assert result.draft_text
    assert result.safe_metadata["sales_composer_fallback"] is True
    assert len(briefs) == 1
    brief = briefs[0]
    assert brief.response_goal is ResponseGoal.ASK_PREFERENCE
    assert brief.known_guest_count == 12 and brief.known_date == date(2026, 8, 13).isoformat()
    assert brief.next_action == "ask_preference"


@pytest.mark.parametrize(("name", "code"), [
    ("Kayak", "kayaking"), ("Aqua Cycle", "aqua_cycle"), ("Bumper Boat", "bumper_boat"),
    ("Zorbing Ball", "zorbing_ball"), ("Water Bike", "water_bike"),
    ("Kids Bumper Boat", "kids_bumper_boat"), ("Kids Paddle Boat", "kids_paddle_boat"),
])
def test_h2o_duration_is_positive_full_day_access_for_every_catalogued_h2o_service(name, code):
    result = _turn(RaipurLangGraphWorkflow(knowledge=_Knowledge(), services=_Services()), f"How long can I access {name}?")
    value = result.draft_text.casefold()
    assert result.context.last_service_code == code
    assert "full-day access" in value and "10:00 am" in value and "6:30 pm" in value
    assert "isn't separately" not in value and "does not mean" not in value


def test_h2o_individual_turn_question_adds_only_relevant_caveat():
    result = _turn(RaipurLangGraphWorkflow(knowledge=_Knowledge(), services=_Services()), "How many minutes is one Zorbing Ball turn?")
    value = result.draft_text.casefold()
    assert "isn't separately listed" in value
    assert "full-day access" in value and "10:00 am" in value and "6:30 pm" in value


def test_general_world_question_uses_openai_fallback_but_entartica_unknown_does_not():
    class _Fallback:
        def __init__(self): self.questions = []
        def respond(self, **kwargs):
            self.questions.append(kwargs["question"])
            return SimpleNamespace(valid=True, text="Japan's prime minister is answered by the general model.")
    fallback = _Fallback()
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(), services=_Services(), conversational_fallback=fallback)
    general = _turn(workflow, "Who is the prime minister of Japan?")
    unknown = _turn(workflow, "Does Party Boat have air conditioning?")
    assert "general model" in general.draft_text and fallback.questions == ["Who is the prime minister of Japan?"]
    assert "general model" not in unknown.draft_text


def test_celebration_typo_gets_options_and_one_sales_question_through_composer():
    briefs = []
    def respond(brief):
        briefs.append(brief)
        return "Absolutely! Party Boat Celebration, Houseboat Celebration, Floating Gazebo, Jetty Gazebo, and Pontoon Celebration are lovely options. Approximately how many guests will join?"
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(), services=_Services(), sales_response_composer=SalesResponseComposer(respond))
    result = _turn(workflow, "i want to clebrate")
    assert result.safe_metadata["sales_composer_used"] is True
    assert briefs[0].response_goal is ResponseGoal.CELEBRATION_DISCOVERY
    assert len(briefs[0].approved_options) == 5
    assert "guests" in result.draft_text.casefold()
    assert result.draft_text.count("?") == 1
