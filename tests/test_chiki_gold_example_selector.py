"""GC-1 train-only deterministic gold-example selection contracts."""
from __future__ import annotations

from types import SimpleNamespace

import openai
import pytest
from pydantic import SecretStr

from app.services.raipur.gold_example_selector import GoldExampleSelector, TRAIN_PATH, compact_gold_examples, load_train_gold_examples
from app.prompts.raipur_system_prompt import RAIPUR_SYSTEM_PROMPT
from app.services.raipur.sales_response_composer import ResponseGoal, SalesResponseBrief, build_sales_response_composer


def _brief(goal, language="en", code=None, facts=(), next_action="answer_service", question=None):
    return SalesResponseBrief(goal, language, service_code=code, service_name=(code or "").replace("_", " ").title() or None, approved_facts=tuple(facts), next_action=next_action, next_question=question)


@pytest.mark.parametrize(("brief", "expected_goal"), [
    (_brief(ResponseGoal.CELEBRATION_DISCOVERY), "celebration_discovery"),
    (_brief(ResponseGoal.CELEBRATION_DISCOVERY, "hinglish"), "celebration_discovery"),
    (_brief(ResponseGoal.CELEBRATION_DISCOVERY, next_action="ask_guest_count"), "celebration_discovery"),
    (_brief(ResponseGoal.ASK_DATE), "ask_date"),
    (_brief(ResponseGoal.ASK_PREFERENCE), "ask_preference"),
    (_brief(ResponseGoal.SERVICE_RECOMMENDATION, code="party_boat_celebration"), "service_recommendation"),
    (_brief(ResponseGoal.SERVICE_OVERVIEW, code="party_boat_celebration"), "service_overview"),
    (_brief(ResponseGoal.SERVICE_OVERVIEW, code="floating_gazebo"), "service_overview"),
    (_brief(ResponseGoal.FACTUAL_ANSWER, code="zorbing_ball", facts=("Full-day access from 10:00 AM to 6:30 PM",)), "factual_answer"),
    (_brief(ResponseGoal.FACTUAL_ANSWER, code="zorbing_ball", facts=("Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM")), "factual_answer"),
    (_brief(ResponseGoal.FACTUAL_ANSWER, code="jet_ski_ride", facts=("Approximately 5–10 minutes",)), "factual_answer"),
    (_brief(ResponseGoal.FAMILY_DISCOVERY, "hinglish"), "family_discovery"),
    (_brief(ResponseGoal.FACTUAL_ANSWER, facts=("Requested detail unavailable; do not invent",), next_action="none"), "factual_answer"),
    (_brief(ResponseGoal.SERVICE_OVERVIEW, "hi", "pontoon_celebration"), "service_overview"),
    (_brief(ResponseGoal.SERVICE_MORE_DETAILS, code="party_boat_celebration"), "service_more_details"),
])
def test_selector_prioritizes_goal_and_language_across_required_scenarios(brief, expected_goal):
    selected = GoldExampleSelector().select(brief)
    assert 3 <= len(selected) <= 5
    assert selected[0].response_goal == expected_goal
    is_individual_turn = any("individual turn duration" in fact.casefold() for fact in brief.approved_facts)
    if not is_individual_turn and any(item.response_goal == expected_goal and item.language == brief.customer_language for item in load_train_gold_examples()):
        assert selected[0].language == brief.customer_language


def test_selector_uses_only_train_and_distinguishes_h2o_access_from_individual_turn():
    assert TRAIN_PATH.name == "train.jsonl" and len(load_train_gold_examples()) == 80
    access = GoldExampleSelector().select(_brief(ResponseGoal.FACTUAL_ANSWER, code="zorbing_ball", facts=("Full-day access from 10:00 AM to 6:30 PM",)))
    turn = GoldExampleSelector().select(_brief(ResponseGoal.FACTUAL_ANSWER, code="zorbing_ball", facts=("Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM")))
    assert access[0].intent_kind == "h2o_access"
    assert turn[0].intent_kind == "h2o_individual_turn"
    assert not any(item.case_id in {"h2o-turn-zorbing_ball", "h2o-turn-kayaking", "discovery-0"} for item in access + turn)


def test_compact_prompt_marks_examples_as_style_only_and_omits_training_envelope():
    compact = compact_gold_examples(GoldExampleSelector().select(_brief(ResponseGoal.SERVICE_OVERVIEW, code="floating_gazebo")))
    assert "EXAMPLE 1" in compact and "Ideal Chiki response:" in compact
    assert '"messages"' not in compact and '"metadata"' not in compact


def test_enabled_fewshot_adds_examples_without_an_extra_openai_call(monkeypatch):
    calls = []
    class _Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text="Floating Gazebo offers a scenic private celebration setting. Would you like its highlights?")
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: SimpleNamespace(responses=_Responses()))
    settings = SimpleNamespace(openai_api_key=SecretStr("test"), openai_chat_model="test-model", chiki_sales_fine_tuned_enabled=False, chiki_sales_gold_fewshot_enabled=True)
    brief = _brief(ResponseGoal.SERVICE_OVERVIEW, code="floating_gazebo", question="Would you like its highlights?")
    result = build_sales_response_composer(settings).compose(brief)
    assert result.valid and len(calls) == 1
    assert calls[0]["instructions"] == RAIPUR_SYSTEM_PROMPT
    assert "CURRENT CUSTOMER BRIEF" in calls[0]["input"]
    assert "only factual authority" in calls[0]["input"]
    assert "facts to verify" not in calls[0]["input"].casefold()


def test_selector_failure_falls_back_to_base_prompt_and_one_call(monkeypatch):
    calls = []
    class _Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text="Floating Gazebo is a scenic private celebration setting.")
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: SimpleNamespace(responses=_Responses()))
    monkeypatch.setattr(GoldExampleSelector, "select", lambda *_args: (_ for _ in ()).throw(OSError("unavailable")))
    settings = SimpleNamespace(openai_api_key=SecretStr("test"), openai_chat_model="test-model", chiki_sales_fine_tuned_enabled=False, chiki_sales_gold_fewshot_enabled=True)
    result = build_sales_response_composer(settings).compose(_brief(ResponseGoal.SERVICE_OVERVIEW, code="floating_gazebo"))
    assert result.valid and len(calls) == 1
    assert "CURRENT CUSTOMER BRIEF" not in calls[0]["input"]
