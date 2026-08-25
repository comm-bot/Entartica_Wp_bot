"""Product evaluation dataset coverage and deterministic scoring."""
from app.evaluation.raipur_conversation_dataset import (
    SCENARIOS,
    EvaluationOutcome,
    evaluate_single_turn_routes,
    evaluation_summary,
)
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


def test_dataset_has_at_least_fifty_diverse_scenarios_and_required_multiturn_flows():
    assert len(SCENARIOS) >= 50
    assert len({scenario.scenario_id for scenario in SCENARIOS}) == len(SCENARIOS)
    categories = {scenario.category for scenario in SCENARIOS}
    assert {"celebration", "family", "explicit_service", "duration", "timings", "location", "restricted", "acknowledgement", "general", "multi_turn"} <= categories
    assert {"en", "hi", "hinglish"} <= {scenario.language for scenario in SCENARIOS}
    multi = {scenario.scenario_id for scenario in SCENARIOS if len(scenario.turns) > 1}
    assert {"birthday_multiturn", "guest_correction", "duration_interruption", "price_interruption", "location_interruption"} <= multi


def test_scoring_reports_semantic_rates_and_generic_fallback_rate():
    summary = evaluation_summary([
        EvaluationOutcome(True, True, True, None, True, True, False),
        EvaluationOutcome(False, None, False, True, None, None, True),
    ])
    assert summary["total_scenarios"] == 2 and summary["passed"] == 1 and summary["failed"] == 1
    assert summary["intent_accuracy"] == 50.0
    assert summary["state_extraction_accuracy"] == 100.0
    assert summary["generic_fallback_rate"] == 50.0


def test_current_offline_routes_are_measured_without_changing_behavior():
    summary, failures = evaluate_single_turn_routes(RaipurLangGraphWorkflow())
    assert summary["total_scenarios"] >= 50
    assert summary["generic_fallback_rate"] >= 0
    # Understanding-assisted cases remain visible in the route-only slice.
    assert "celebration_typo" in failures
    assert "venue_timings" not in failures
