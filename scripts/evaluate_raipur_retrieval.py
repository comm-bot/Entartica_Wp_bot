"""Safe, no-write calibration evaluation for the Raipur knowledge corpus."""

from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.services.knowledge_intent import classify_knowledge_intent
from scripts.ingest_raipur_knowledge import embed_texts
from scripts.test_raipur_retrieval import _safe_source_filename, retrieve_candidates, select_category_aware_result


POSITIVE_TESTS = (
    ("Where is Entartica Raipur located?", ("location_information",)),
    ("What activities are available at Raipur?", ("services", "faq")),
    ("What are the operating timings?", ("location_information", "faq")),
    ("Is advance booking required?", ("booking_policy", "faq")),
    ("What safety rules apply?", ("safety_guidelines",)),
    ("Can children participate?", ("safety_guidelines", "faq")),
    ("How can I get the price?", ("booking_policy", "faq")),
    ("Is submitting an enquiry a confirmed booking?", ("booking_policy", "faq")),
    ("What happens during bad weather?", ("safety_guidelines", "booking_policy", "faq")),
)
NEGATIVE_TESTS = (
    "What is the weather in Delhi?",
    "What flights are available tomorrow?",
    "What services are available in Indore?",
    "Who is the Prime Minister?",
    "Tell me about railway tickets.",
)


def _expected_label(categories: tuple[str, ...]) -> str:
    return "_or_".join(categories)


def recommend_threshold(correct: list[float], incorrect: list[float], negative: list[float]) -> tuple[float | None, bool]:
    """Recommend only when one threshold can accept a majority and reject non-matches."""

    if not correct:
        return None, True
    maximum_negative = max(negative, default=0.0)
    candidate = min(1.0, maximum_negative + 0.001)
    accepted_correct = sum(score >= candidate for score in correct)
    if candidate <= 1 and accepted_correct >= math.ceil(len(correct) / 2):
        return candidate, any(score >= candidate for score in incorrect)
    return None, True


def strategy_metrics(rows: list[dict[str, Any]], semantic: float, lexical: float, higher: float, strategy: str) -> dict[str, int]:
    """Evaluate preserved candidates only; never mutates production acceptance."""
    accepted_positive = accepted_negative = unsupported_rejected = 0
    for row in rows:
        candidate = row.get("candidate")
        unsupported = row.get("unsupported", False)
        if unsupported:
            unsupported_rejected += 1
            accepted = False
        elif candidate is None:
            accepted = False
        else:
            score = row["score"] if row["score"] is not None else -1.0
            lexical_score = row["lexical"] if row["lexical"] is not None else -1.0
            base = row["preferred"] and score >= semantic
            lexical_ok = lexical_score >= lexical
            high_path = row["preferred"] and row["high"] and score >= higher
            accepted = base and lexical_ok if strategy == "strict" else (base and lexical_ok) or high_path
        if row["positive"]: accepted_positive += int(accepted)
        else: accepted_negative += int(accepted)
    return {"positive_accepted": accepted_positive, "negative_accepted": accepted_negative, "false_positives": accepted_negative, "false_negatives": 9 - accepted_positive, "unsupported_rejected": unsupported_rejected}


def main() -> int:
    settings = Settings()
    if not settings.embedding_configuration_is_valid():
        print("evaluation_refused embedding_configuration_incomplete=true")
        return 1
    client = get_supabase_client()
    correct_scores: list[float] = []
    incorrect_positive_scores: list[float] = []
    negative_scores: list[float] = []
    false_acceptance_count = 0
    false_rejection_count = 0
    rows: list[dict[str, Any]] = []
    try:
        test_number = 0
        for question, expected in POSITIVE_TESTS:
            test_number += 1
            intent = classify_knowledge_intent(question)
            candidates = retrieve_candidates(client, embed_texts([question], settings)[0], limit=20)
            decision = select_category_aware_result(
                candidates, intent=intent, minimum_similarity=0.0, limit=settings.knowledge_top_k,
                question=question, lexical_minimum=settings.knowledge_lexical_min_score
            )
            result = decision.selected or decision.diagnostic_candidate
            category = result["category"] if result else "unknown"
            source = _safe_source_filename(result["source_filename"]) if result else "unknown"
            score = result["score"] if result else 0.0
            match = category in expected
            rows.append({"candidate": result, "positive": True, "preferred": decision.preferred_category_match or match, "score": score if result else None, "lexical": decision.evidence.evidence_score if decision.evidence else None, "high": intent.confidence == "high", "unsupported": intent.human_handover_required, "category_match": match})
            threshold_accepted = decision.final_acceptance
            if match:
                correct_scores.append(score)
                false_rejection_count += int(not threshold_accepted)
            else:
                incorrect_positive_scores.append(score)
                false_acceptance_count += int(threshold_accepted)
            print(
                f"test_number={test_number} positive_or_negative=positive expected_category={_expected_label(expected)} "
                f"retrieved_category={category} sanitized_source={source} top_score={score:.3f} "
                f"category_match={'yes' if match else 'no'}"
            )
        for question in NEGATIVE_TESTS:
            test_number += 1
            intent = classify_knowledge_intent(question)
            candidates = [] if intent.human_handover_required else retrieve_candidates(
                client, embed_texts([question], settings)[0], limit=20
            )
            decision = select_category_aware_result(
                candidates, intent=intent, minimum_similarity=0.0, limit=settings.knowledge_top_k,
                question=question, lexical_minimum=settings.knowledge_lexical_min_score
            )
            result = decision.selected or decision.diagnostic_candidate
            category = result["category"] if result else "unknown"
            source = _safe_source_filename(result["source_filename"]) if result else "unknown"
            score = result["score"] if result else 0.0
            negative_scores.append(score)
            rows.append({"candidate": result, "positive": False, "preferred": decision.preferred_category_match, "score": score if result else None, "lexical": decision.evidence.evidence_score if decision.evidence else None, "high": intent.confidence == "high", "unsupported": intent.human_handover_required, "category_match": False})
            false_acceptance_count += int(decision.final_acceptance)
            print(
                f"test_number={test_number} positive_or_negative=negative expected_category=none "
                f"retrieved_category={category} sanitized_source={source} top_score={score:.3f} category_match=no"
            )
    except Exception as error:
        print(f"evaluation_failed error_class={type(error).__name__}")
        return 1
    recommended, insufficient = recommend_threshold(correct_scores, incorrect_positive_scores, negative_scores)
    global_threshold_insufficient = min(correct_scores, default=0.0) <= max(negative_scores, default=0.0)
    print(f"minimum_correct_positive_score={min(correct_scores, default=0.0):.3f}")
    print(f"maximum_incorrect_positive_score={max(incorrect_positive_scores, default=0.0):.3f}")
    print(f"maximum_negative_score={max(negative_scores, default=0.0):.3f}")
    print(f"false_acceptance_count={false_acceptance_count}")
    print(f"semantic_only_false_rejections={false_rejection_count}")
    print("recommended_threshold=" + (f"{recommended:.3f}" if recommended is not None else "insufficient_separation"))
    print(f"threshold_adjustment_insufficient={'yes' if global_threshold_insufficient else 'no'}")
    best: dict[str, tuple[dict[str, int], float, float, float]] = {}
    for strategy in ("strict", "lexical_support", "two_tier"):
        candidates = []
        for semantic in (.30,.35,.38,.383,.40,.45,.50,.55,.60,.65):
            for lexical in (0,.10,.15,.20,.25,.30):
                for higher in (.40,.45,.50,.55,.60,.65):
                    metrics = strategy_metrics(rows, semantic, lexical, higher, strategy)
                    candidates.append((metrics, semantic, lexical, higher))
        best[strategy] = max(candidates, key=lambda item: (item[0]["positive_accepted"], -item[0]["negative_accepted"], item[2], item[3]))
        metrics, semantic, lexical, higher = best[strategy]
        qualified = metrics["positive_accepted"] >= 8 and metrics["negative_accepted"] == 0 and sum(r["category_match"] for r in rows if r["positive"]) == 9
        print(f"strategy={strategy} semantic_threshold={semantic:.3f} lexical_threshold={lexical:.2f} higher_semantic_threshold={higher:.2f} positive_accepted={metrics['positive_accepted']} negative_accepted={metrics['negative_accepted']} false_positives={metrics['false_positives']} false_negatives={metrics['false_negatives']} unsupported_locations_rejected={metrics['unsupported_rejected']} qualified={'yes' if qualified else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
