"""Evaluation-guided fixes replayed through the production graph path."""
from app.evaluation.raipur_end_to_end_evaluation import run_end_to_end_evaluation
from app.services.raipur.customer_understanding import CustomerUnderstandingService
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


def _plan(message):
    workflow = RaipurLangGraphWorkflow()
    return workflow.plan_message({
        "normalized_message": message.casefold(), "previous_service_code": None,
        "previous_topic": None, "language": "en", "_runtime": {"current_state": None},
        "message_id": "test", "intent": None, "service_code": None, "topic": None,
    })


def test_kayak_aliases_resolve_to_one_canonical_service_overview():
    for message in ("What is kayaking?", "Tell me about kayak", "kayaking kya hai?", "what can I do in kayaking?"):
        plan = _plan(message)
        assert (plan["service_code"], plan["selected_route"]) == ("kayaking", "answer_service_knowledge")


def test_general_and_service_operating_hours_use_existing_timing_routes():
    general = _plan("What are your timings?")
    assert (general["intent"], general["topic"], general["selected_route"]) == ("venue_duration_timing", "operating_hours", "answer_venue_knowledge")
    for message, service in (
        ("What are Party Boat timings?", "party_boat_celebration"),
        ("When is Floating Gazebo available during the day?", "floating_gazebo"),
        ("Houseboat Celebration operating hours?", "houseboat_celebration"),
        ("Pontoon Celebration timing kya hai?", "pontoon_celebration"),
    ):
        plan = _plan(message)
        assert (plan["service_code"], plan["topic"], plan["selected_route"]) == (service, "operating_hours", "answer_service_knowledge")


def test_location_and_payment_remain_high_priority_deterministic_routes():
    location = _plan("Where is Entartica Raipur?")
    assert (location["intent"], location["selected_route"], location["understanding_invoked"]) == ("location", "answer_location", False)
    for message in ("How can I pay?", "payment kaise karu?", "I want to make payment", "where should I pay?"):
        payment = _plan(message)
        assert payment["intent"] == "payment" and payment["selected_route"] == "handover_to_sales"


def test_typo_and_family_language_activate_structured_understanding():
    outputs = {
        "muje selebration krvana he": {"intent":"celebration","language":"hinglish","confidence":.98},
        "coming with children": {"intent":"family_discovery","preference":"family","language":"en","confidence":.98},
    }
    workflow = RaipurLangGraphWorkflow(customer_understanding=CustomerUnderstandingService(lambda message, _context: outputs[message]))
    for message, expected in (("muje selebration krvana he", "celebration_service_list"), ("coming with children", "family_activity_discovery")):
        plan = workflow.plan_message({
            "normalized_message": message, "previous_service_code": None, "previous_topic": None,
            "language": "en", "_runtime": {"current_state": None}, "message_id": "test",
            "intent": None, "service_code": None, "topic": None,
        })
        assert plan["understanding_invoked"] is True and plan["intent"] == expected


def test_end_to_end_production_slice_is_green_and_has_only_expected_general_fallback():
    summary, failures = run_end_to_end_evaluation()
    assert failures == []
    assert summary["total_scenarios"] == 12 and summary["passed"] == 12
    assert summary["intent_accuracy"] == 100.0
    assert summary["state_extraction_accuracy"] == 100.0
    assert summary["correct_next_action"] == 100.0
    assert summary["restricted_policy_accuracy"] == 100.0
    assert summary["recommendation_correctness"] == 100.0
    assert summary["context_retention"] == 100.0
    assert summary["unexpected_entartica_fallback_rate"] == 0.0
    assert summary["expected_general_fallback_rate"] > 0
