"""Controlled Raipur-only embedding retrieval; it never calls chat or WhatsApp APIs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from dataclasses import dataclass
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.rag.location_filter import is_document_available_for_location
from app.services.knowledge_intent import KnowledgeIntentResult, classify_knowledge_intent
from app.services.knowledge_evidence import EvidenceResult, lexical_evidence
from scripts.ingest_raipur_knowledge import embed_texts


def _rows(response: object) -> list[dict[str, Any]]:
    data = getattr(response, "data", None) if response is not None else None
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _vector(value: Any) -> list[float] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if isinstance(value, list) and all(isinstance(item, (int, float)) for item in value):
        return [float(item) for item in value]
    return None


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1.0
    denominator = math.sqrt(sum(item * item for item in left)) * math.sqrt(sum(item * item for item in right))
    return sum(first * second for first, second in zip(left, right, strict=True)) / denominator if denominator else -1.0


def record_unanswered_question(client: Any, question: str) -> bool:
    """Store a low-confidence question once, without connection to the webhook."""

    existing = (
        client.table("unanswered_questions")
        .select("id")
        .eq("question", question)
        .eq("status", "open")
        .eq("record_origin", "development_retrieval_test")
        .maybe_single()
        .execute()
    )
    if _rows(existing):
        return False
    client.table("unanswered_questions").insert(
        {"question": question, "status": "open", "record_origin": "development_retrieval_test"}
    ).execute()
    return True


def retrieve_candidates(
    client: Any,
    question_embedding: list[float],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Retrieve Raipur/global candidates without making an acceptance decision."""

    documents_response = (
        client.table("knowledge_documents")
        .select("id,source_file,metadata")
        .eq("is_active", True)
        .or_("metadata->>location_code.eq.raipur,metadata->>location_code.eq.global")
        .execute()
    )
    documents = [
        document for document in _rows(documents_response)
        if isinstance(document.get("metadata"), dict)
        and is_document_available_for_location(document["metadata"], "raipur")
        and isinstance(document.get("id"), str)
    ]
    if not documents:
        return []
    document_map = {document["id"]: document for document in documents}
    chunks_response = (
        client.table("knowledge_chunks")
        .select("knowledge_document_id,content,embedding,metadata")
        .in_("knowledge_document_id", list(document_map))
        .execute()
    )
    ranked: list[dict[str, Any]] = []
    for chunk in _rows(chunks_response):
        document_id = chunk.get("knowledge_document_id")
        embedding = _vector(chunk.get("embedding"))
        if document_id not in document_map or embedding is None:
            continue
        score = _cosine(question_embedding, embedding)
        if score < -0.5 or not isinstance(chunk.get("content"), str):
            continue
        document = document_map[document_id]
        metadata = document["metadata"]
        ranked.append({
            "source_filename": metadata.get("source_filename", document.get("source_file", "unknown")),
            "category": metadata.get("document_category", "unknown"),
            "score": score,
            # Kept in-memory for the local, source-grounded answer check.  It is
            # deliberately never included in diagnostic output.
            "content": chunk["content"],
            "excerpt": chunk["content"][:180].replace("\n", " "),
        })
    return sorted(ranked, key=lambda item: item["score"], reverse=True)[:limit]


def accepted_results(
    candidates: list[dict[str, Any]], *, minimum_similarity: float, limit: int
) -> list[dict[str, Any]]:
    """Return only candidates that meet the configured confidence threshold."""

    return [
        result for result in sorted(candidates, key=lambda item: item["score"], reverse=True)
        if result["score"] >= minimum_similarity
    ][:limit]


@dataclass(frozen=True)
class RetrievalDecision:
    intent: KnowledgeIntentResult
    selected: dict[str, Any] | None
    low_confidence: bool
    evidence: EvidenceResult | None = None
    diagnostic_candidate: dict[str, Any] | None = None
    semantic_candidate_found: bool = False
    location_allowed: bool = True
    semantic_threshold_passed: bool = False
    lexical_evidence_passed: bool = False
    final_acceptance: bool = False

    @property
    def human_handover_required(self) -> bool:
        return self.intent.human_handover_required

    @property
    def preferred_category_match(self) -> bool:
        return bool(self.selected and self.selected["category"] in self.intent.preferred_categories)


def select_category_aware_result(
    candidates: list[dict[str, Any]], *, intent: KnowledgeIntentResult, minimum_similarity: float, limit: int,
    question: str | None = None, lexical_minimum: float = 0.0
) -> RetrievalDecision:
    """Use preferred categories first without changing any raw similarity score."""

    if intent.human_handover_required:
        return RetrievalDecision(intent, None, True, diagnostic_candidate=None, location_allowed=False)
    preferred = [candidate for candidate in candidates if candidate["category"] in intent.preferred_categories]
    accepted_preferred = accepted_results(preferred, minimum_similarity=minimum_similarity, limit=limit)
    if accepted_preferred:
        return _with_evidence(intent, accepted_preferred[0], question, lexical_minimum)
    fallback = [candidate for candidate in candidates if candidate["category"] in intent.fallback_categories]
    accepted_fallback = accepted_results(fallback, minimum_similarity=minimum_similarity, limit=limit)
    if accepted_fallback:
        return _with_evidence(intent, accepted_fallback[0], question, lexical_minimum)
    candidate = preferred[0] if preferred else (fallback[0] if fallback else None)
    return RetrievalDecision(intent, None, True, diagnostic_candidate=candidate, semantic_candidate_found=bool(candidate), location_allowed=True)

def _with_evidence(intent: KnowledgeIntentResult, candidate: dict[str, Any], question: str | None, minimum: float) -> RetrievalDecision:
    semantic_passed = candidate["score"] >= minimum
    if question is None: return RetrievalDecision(intent, candidate if semantic_passed else None, not semantic_passed, diagnostic_candidate=candidate, semantic_candidate_found=True, semantic_threshold_passed=semantic_passed, final_acceptance=semantic_passed)
    evidence=lexical_evidence(question, candidate.get("content", ""), intent, minimum)
    accepted = semantic_passed and evidence.has_sufficient_evidence
    return RetrievalDecision(intent, candidate if accepted else None, not accepted, evidence, candidate, True, True, semantic_passed, evidence.has_sufficient_evidence, accepted)


def _safe_source_filename(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value) if isinstance(value, str) else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument("--diagnostic", action="store_true", help="Show safe candidate scores without writing unanswered questions.")
    parser.add_argument("--min-score", type=float, help="Development-only threshold override between zero and one.")
    parser.add_argument("--no-record-unanswered", action="store_true", help="Do not write a development unanswered-question record.")
    args = parser.parse_args()
    settings = Settings()
    if not settings.embedding_configuration_is_valid():
        print("retrieval_refused embedding_configuration_incomplete=true")
        return 1
    minimum_similarity = args.min_score if args.min_score is not None else settings.knowledge_min_similarity
    if not 0 <= minimum_similarity <= 1:
        print("retrieval_refused invalid_minimum_similarity=true")
        return 2
    client = get_supabase_client()
    try:
        intent = classify_knowledge_intent(args.question)
        candidates = [] if intent.human_handover_required else retrieve_candidates(
            client, embed_texts([args.question], settings)[0], limit=20
        )
        decision = select_category_aware_result(
            candidates, intent=intent, minimum_similarity=minimum_similarity, limit=settings.knowledge_top_k,
            question=args.question, lexical_minimum=settings.knowledge_lexical_min_score
        )
        if args.diagnostic:
            selected = decision.selected or decision.diagnostic_candidate
            selected_category = selected["category"] if selected else "none"
            selected_source = _safe_source_filename(selected["source_filename"]) if selected else "none"
            selected_score = selected["score"] if selected else 0.0
            evidence_score = decision.evidence.evidence_score if decision.evidence else 0.0
            reason = decision.evidence.reason_code if decision.evidence else "no_lexical_match"
            print(
                f"intent={intent.intent} preferred_categories={','.join(intent.preferred_categories) or 'none'} "
                f"selected_category={selected_category} source_filename={selected_source} "
                f"raw_similarity_score={selected_score:.3f} "
                f"preferred_category_match={'yes' if decision.preferred_category_match else 'no'} "
                f"lexical_evidence_score={evidence_score:.3f} reason_code={reason} "
                f"semantic_threshold_passed={'yes' if decision.semantic_threshold_passed else 'no'} "
                f"lexical_threshold_passed={'yes' if decision.lexical_evidence_passed else 'no'} "
                f"final_acceptance={'yes' if decision.final_acceptance else 'no'}"
            )
            return 0
        results = [decision.selected] if decision.selected else []
        low_confidence = decision.low_confidence
        recorded = (
            record_unanswered_question(client, args.question)
            if low_confidence and not decision.human_handover_required and not args.no_record_unanswered
            else False
        )
    except Exception as error:
        print(f"retrieval_failed error_class={type(error).__name__}")
        return 1
    print(
        "retrieval_configuration "
        f"minimum_similarity={minimum_similarity:.2f} top_k={settings.knowledge_top_k}"
    )
    for result in results:
        print(f"result source_filename={result['source_filename']} category={result['category']} similarity_score={result['score']:.3f} excerpt={result['excerpt']}")
    print(
        f"retrieval_complete result_count={len(results)} low_confidence={low_confidence} "
        f"human_handover_required={decision.human_handover_required} unanswered_recorded={recorded}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
