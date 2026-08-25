"""Offline contracts for the Chiki sales-composer dataset."""
import json
from pathlib import Path

from app.evaluation.chiki_fine_tuning import deterministic_output_metrics, holdout_evaluation_contract, load_jsonl, validate_dataset

ROOT = Path(__file__).resolve().parents[1] / "data" / "fine_tuning" / "chiki_sales_v1"


def test_dataset_is_valid_grounded_and_split_without_near_duplicate_leakage():
    result = validate_dataset(ROOT)
    assert result.valid, result.errors
    assert result.example_count == 120
    assert result.language_distribution == {"hi": 36, "en": 42, "hinglish": 42}
    assert {"celebration_discovery", "ask_date", "ask_preference", "service_recommendation", "service_overview", "service_more_details", "factual_answer", "activity_discovery", "family_discovery"} == set(result.goal_distribution)


def test_dataset_splits_manifest_and_chat_format_match_contract():
    assert {name: len(load_jsonl(ROOT / f"{name}.jsonl")) for name in ("train", "validation", "holdout")} == {"train":80,"validation":20,"holdout":20}
    manifest = json.loads((ROOT / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["validation_status"] == "passed_offline_validation"
    assert manifest["contains_customer_pii"] is False and manifest["external_upload"] is False
    assert manifest["h2o_examples"] == 14 and manifest["recommendation_examples"] == 12


def test_holdout_evaluation_contract_is_offline_and_has_required_metrics():
    contract = holdout_evaluation_contract()
    assert contract["external_evaluation"] is False
    assert {"sales_tone", "fact_grounding", "next_action_compliance", "conciseness", "language_match", "unsupported_claim_rate", "governance_leakage", "service_name_accuracy"} == set(contract["metrics"])


def test_holdout_reference_is_objectively_grounded_but_tone_remains_unscored():
    metrics = deterministic_output_metrics(load_jsonl(ROOT / "holdout.jsonl"))
    for key in ("factual_grounding", "service_name_accuracy", "next_question_compliance", "unsupported_claim_free", "governance_leakage_free", "language_match", "conciseness"):
        assert metrics[key] == 100.0
    assert metrics["sales_tone_quality"] == "requires_human_or_model_evaluation"


def test_package_duration_examples_are_in_learning_splits_not_added_to_holdout():
    cases = {split:{row["metadata"]["case_id"] for row in load_jsonl(ROOT/f"{split}.jsonl")} for split in ("train","validation","holdout")}
    assert "daycation-duration" in cases["train"]
    assert "staycation-duration" in cases["validation"]
    assert not ({"daycation-duration","staycation-duration"} & cases["holdout"])
