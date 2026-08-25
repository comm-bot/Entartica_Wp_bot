"""Explicitly opt-in runner for the paid current-composer holdout baseline."""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.evaluation.chiki_fine_tuning import (
    ALLOWED_SERVICE_NAMES,
    FORBIDDEN,
    UNSAFE_CLAIM,
    load_jsonl,
)
from app.rag.customer_ready_knowledge import contains_governance_language
from app.services.raipur.sales_response_composer import (
    CustomerFacts,
    ResponseGoal,
    SalesResponseBrief,
    build_sales_response_composer,
)

ROOT = Path(__file__).resolve().parents[1] / "data" / "fine_tuning" / "chiki_sales_v1"


def _brief(raw: dict[str, object]) -> SalesResponseBrief:
    values = dict(raw)
    customer_facts = values.pop("customer_facts", None)
    values["response_goal"] = ResponseGoal(values["response_goal"])
    for key in ("approved_facts", "approved_options", "recommended_service_codes", "restrictions"):
        values[key] = tuple(values.get(key) or ())
    if customer_facts:
        values["customer_facts"] = CustomerFacts(
            **{key: tuple(value) if isinstance(value, list) else value for key, value in customer_facts.items()}
        )
    return SalesResponseBrief(**values)


def _checks(brief: dict[str, object], answer: str, *, composer_valid: bool) -> dict[str, bool]:
    supplied = json.dumps(brief, ensure_ascii=False).casefold()
    supplied_names = set(brief.get("approved_options") or ())
    if brief.get("service_name"):
        supplied_names.add(str(brief["service_name"]))
    unsupported_names = [
        name for name in ALLOWED_SERVICE_NAMES
        if name.casefold() in answer.casefold()
        and not any(name.casefold() in supplied_name.casefold() for supplied_name in supplied_names)
    ]
    unsupported_numbers = [number for number in re.findall(r"\b\d+(?::\d+)?\b", answer) if number not in supplied]
    expected_service = brief.get("service_name")
    question = brief.get("next_question")
    if question:
        keywords = [word for word in re.findall(r"[a-z0-9]+", str(question).casefold()) if len(word) >= 4]
        question_ok = answer.count("?") == 1 and (not keywords or any(word in answer.casefold() for word in keywords[-4:]))
    else:
        question_ok = answer.count("?") == 0
    governance = bool(FORBIDDEN.search(answer) or contains_governance_language(answer))
    unsafe = bool(UNSAFE_CLAIM.search(answer))
    language = brief.get("customer_language")
    language_ok = (
        language == "en"
        or (language == "hinglish" and bool(re.search(r"\b(?:hai|hain|aap|ke|ki|kar|karein|liye|khaas)\b", answer, re.I)))
        or (language == "hi" and bool(re.search(r"[\u0900-\u097f]", answer)))
    )
    return {
        "factual_grounding": composer_valid and not unsupported_numbers,
        "service_name_accuracy": composer_valid and (not expected_service or str(expected_service).casefold() in answer.casefold()),
        "next_action_compliance": composer_valid and question_ok,
        "next_question_compliance": composer_valid and question_ok,
        "unsupported_service_names_free": not unsupported_names,
        "unsupported_numeric_facts_free": not unsupported_numbers,
        "price_hallucination_free": not bool(re.search(r"(?:₹|\binr\b|\brs\.?\s*\d|\bprice\s+is\b)", answer, re.I)),
        "availability_hallucination_free": not bool(re.search(r"\b(?:available|slot)\s+(?:now|today|tomorrow)\b", answer, re.I)),
        "booking_confirmation_hallucination_free": not bool(re.search(r"\b(?:booking|payment)\s+(?:is\s+)?confirmed\b", answer, re.I)),
        "governance_leakage_free": not governance,
        "language_match": composer_valid and language_ok,
        "concise_response": composer_valid and len(answer) <= 900,
        "composer_validation_passed": composer_valid,
        "unsupported_claims_free": not unsafe and not unsupported_names and not unsupported_numbers,
    }


def _percent(outputs: list[dict[str, object]], key: str) -> float:
    return round(100 * sum(bool(row["deterministic_validation"][key]) for row in outputs) / len(outputs), 2)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


def _write_review(outputs: list[dict[str, object]]) -> None:
    lines = [
        "# Current Composer Baseline Review",
        "",
        "Subjective scoring status: **HUMAN REVIEW REQUIRED**. No automated judge was used.",
        "",
        "Rubric for each reviewer field: 1 = poor, 3 = acceptable, 5 = excellent.",
        "",
    ]
    for row in outputs:
        lines.extend([
            f"## {row['example_id']}", "",
            f"**Scenario:** {row['response_goal']} ({row['language']})", "",
            f"**Structured brief summary:** `{json.dumps(row['brief_summary'], ensure_ascii=False)}`", "",
            "**Current composer output:**", "", str(row["generated_response"] or "[NO VALID PRODUCTION OUTPUT]"), "",
            "**Gold response:**", "", str(row["gold_response"]), "",
            f"**Objective checks:** `{json.dumps(row['deterministic_validation'], sort_keys=True)}`", "",
            "**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5", "",
            "**Reviewer notes:** HUMAN REVIEW REQUIRED", "",
        ])
    (ROOT / "baseline_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-external-openai-calls", action="store_true")
    args = parser.parse_args()
    if not args.allow_external_openai_calls:
        raise SystemExit("Refusing external calls. Re-run with --allow-external-openai-calls after approval.")
    settings = Settings(chiki_sales_fine_tuned_enabled=False)
    if settings.chiki_sales_fine_tuned_enabled:
        raise SystemExit("Fine-tuned model must remain disabled for the base baseline.")
    if not settings.openai_api_key or not settings.openai_chat_model:
        raise SystemExit("OPENAI_API_KEY and OPENAI_CHAT_MODEL are required.")

    composer = build_sales_response_composer(settings)
    outputs: list[dict[str, object]] = []
    for row in load_jsonl(ROOT / "holdout.jsonl"):
        raw = json.loads(row["messages"][1]["content"])
        started = time.perf_counter()
        result = composer.compose(_brief(raw))
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        answer = result.text or ""
        outputs.append({
            "example_id": row["metadata"]["case_id"],
            "response_goal": raw["response_goal"],
            "language": raw["customer_language"],
            "service_code": raw.get("service_code"),
            "model_used": settings.openai_chat_model,
            "generated_response": answer,
            "latency_ms": latency_ms,
            "deterministic_validation": _checks(raw, answer, composer_valid=result.valid),
            "composer_result": result.reason,
            "brief_summary": {
                "service_name": raw.get("service_name"),
                "approved_facts": raw.get("approved_facts"),
                "approved_options": raw.get("approved_options"),
                "next_action": raw.get("next_action"),
                "next_question": raw.get("next_question"),
            },
            "gold_response": row["messages"][2]["content"],
        })

    output_path = ROOT / "baseline_outputs.jsonl"
    output_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in outputs), encoding="utf-8")
    _write_review(outputs)
    latencies = [float(row["latency_ms"]) for row in outputs]
    summary = {
        "model": settings.openai_chat_model,
        "fine_tuned": False,
        "calls_completed": len(outputs),
        "factual_grounding": _percent(outputs, "factual_grounding"),
        "service_name_accuracy": _percent(outputs, "service_name_accuracy"),
        "next_action_compliance": _percent(outputs, "next_action_compliance"),
        "next_question_compliance": _percent(outputs, "next_question_compliance"),
        "unsupported_claim_rate": round(100 - _percent(outputs, "unsupported_claims_free"), 2),
        "governance_leakage_rate": round(100 - _percent(outputs, "governance_leakage_free"), 2),
        "language_match": _percent(outputs, "language_match"),
        "conciseness": _percent(outputs, "concise_response"),
        "average_latency_ms": round(statistics.mean(latencies), 2),
        "p50_latency_ms": _percentile(latencies, .50),
        "p95_latency_ms": _percentile(latencies, .95),
        "sales_tone_review": "HUMAN REVIEW REQUIRED",
    }
    (ROOT / "current_composer_baseline.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
