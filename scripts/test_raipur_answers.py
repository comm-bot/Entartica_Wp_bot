"""Local Raipur answer check using retrieval only; no WhatsApp or chat calls."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.services.knowledge_intent import classify_knowledge_intent
from app.services.raipur_answers import RaipurAnswer, generate_raipur_answer
from scripts.ingest_raipur_knowledge import embed_texts
from scripts.test_raipur_retrieval import (
    RetrievalDecision,
    retrieve_candidates,
    select_category_aware_result,
)


def _safe_source_filename(value: object) -> str:
    """Return a filename-shaped identifier without exposing a path."""

    if not isinstance(value, str):
        return "unknown"
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(value).name) or "unknown"


def _reason_code(decision: RetrievalDecision, answer: RaipurAnswer) -> str:
    if decision.intent.human_handover_required:
        return "unsupported_location"
    if not decision.semantic_candidate_found:
        return "no_raipur_candidate"
    if not decision.semantic_threshold_passed:
        return "low_confidence"
    if not decision.lexical_evidence_passed:
        return decision.evidence.reason_code if decision.evidence else "insufficient_lexical_evidence"
    return "incomplete_source" if answer.human_handover_required else "accepted"


def local_answer_for_question(
    question: str,
    *,
    settings: Settings,
    client: Any,
    embedder: Callable[[list[str], Settings], list[list[float]]] = embed_texts,
) -> tuple[RaipurAnswer, RetrievalDecision, str]:
    """Resolve one question locally, without writes or customer-channel side effects."""

    intent = classify_knowledge_intent(question)
    candidates = [] if intent.human_handover_required else retrieve_candidates(
        client, embedder([question], settings)[0], limit=20
    )
    decision = select_category_aware_result(
        candidates,
        intent=intent,
        minimum_similarity=settings.knowledge_min_similarity,
        limit=settings.knowledge_top_k,
        question=question,
        lexical_minimum=settings.knowledge_lexical_min_score,
    )
    answer = generate_raipur_answer(decision.selected, low_confidence=decision.low_confidence)
    return answer, decision, _reason_code(decision, answer)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local, source-grounded Raipur answer check.")
    parser.add_argument("--question", required=True)
    args = parser.parse_args()

    settings = Settings()
    if not settings.embedding_configuration_is_valid():
        print("answer_result status=refused reason_code=embedding_configuration_incomplete human_handover_required=true")
        return 1

    try:
        answer, _decision, reason = local_answer_for_question(
            args.question, settings=settings, client=get_supabase_client()
        )
    except Exception as error:
        print(f"answer_result status=failed reason_code=local_retrieval_failed error_class={type(error).__name__}")
        return 1

    if answer.human_handover_required:
        print(f"answer_result status=handover reason_code={reason} human_handover_required=true")
        print("answer=Our team will assist you with this request.")
        return 0

    source = _safe_source_filename(answer.source_filenames[0])
    print(
        f"answer_result status=grounded source_filename={source} confidence={answer.confidence:.3f} "
        "human_handover_required=false reason_code=accepted"
    )
    print(f"answer={answer.answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
