"""Read-only, redacted Raipur knowledge-provider diagnostic."""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.integrations.supabase import get_supabase_client
from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.rag.retrieval import KnowledgeRetrievalError, embed_query, embed_texts, inspect_raipur_corpus, retrieve_candidates

QUESTION = "Where is the Raipur location?"


def _result(*, embedding_ok: bool, candidate_count: int, best_confidence: float | None,
            threshold: float, source_present: bool, provider_text_present: bool,
            provider_low_confidence: bool, stage: str, reason: str,
            embedding_facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "embedding_ok": embedding_ok, "candidate_count": candidate_count,
        "best_confidence": best_confidence, "configured_threshold": threshold,
        "source_present": source_present, "provider_text_present": provider_text_present,
        "provider_low_confidence": provider_low_confidence,
        "diagnostic_stage": stage, "reason": reason, **embedding_facts,
    }


def diagnose(settings: Any, client: Any, *, embed_fn: Callable = embed_query,
             retrieve_fn: Callable = retrieve_candidates,
             provider_factory: Callable = RaipurKnowledgeProvider,
             corpus_inspector: Callable = inspect_raipur_corpus) -> dict[str, Any]:
    """Run the fixed-question read path without printing retrieval data."""
    threshold = float(settings.raipur_knowledge_min_confidence)
    key = getattr(settings, "openai_api_key", None)
    key_present = bool(key and (key.get_secret_value() if hasattr(key, "get_secret_value") else key))
    model_present = isinstance(getattr(settings, "openai_embedding_model", None), str) and bool(settings.openai_embedding_model.strip())
    facts = {"api_key_present": key_present, "embedding_model_present": model_present,
             "embedding_client_created": False, "embedding_response_received": False,
             "embedding_vector_valid": False, "embedding_dimension": None,
             "stored_dimension": None, "dimension_match": False,
             "knowledge_documents_total": 0, "knowledge_documents_raipur": 0,
             "knowledge_documents_approved": 0, "knowledge_documents_active": 0,
             "knowledge_documents_eligible": 0, "knowledge_chunks_total": 0,
             "eligible_document_chunks": 0, "chunks_with_embedding": 0,
             "chunks_without_embedding": 0, "raw_candidate_count": 0,
             "best_raw_confidence": None, "filtered_candidate_count": 0}
    runtime_embed = embed_fn
    if embed_fn is embed_query:
        runtime_embed = lambda question, configured: embed_query(
            question, configured,
            embed_texts_fn=lambda texts, current: embed_texts(texts, current, diagnostics=facts),
        )
    try:
        embedding = runtime_embed(QUESTION, settings)
        facts["embedding_dimension"] = len(embedding)
        facts["embedding_vector_valid"] = True
    except KnowledgeRetrievalError as error:
        return _result(embedding_ok=False, candidate_count=0, best_confidence=None,
                       threshold=threshold, source_present=False, provider_text_present=False,
                       provider_low_confidence=True, stage="embedding_failed", reason=str(error), embedding_facts=facts)
    except Exception:
        return _result(embedding_ok=False, candidate_count=0, best_confidence=None,
                       threshold=threshold, source_present=False, provider_text_present=False,
                       provider_low_confidence=True, stage="embedding_failed", reason="embedding_request_failed", embedding_facts=facts)
    try:
        facts.update(corpus_inspector(client, embedding))
    except Exception:
        return _result(embedding_ok=True, candidate_count=0, best_confidence=None,
                       threshold=threshold, source_present=False, provider_text_present=False,
                       provider_low_confidence=True, stage="retrieval_failed", reason="retrieval_failed", embedding_facts=facts)
    if facts["stored_dimension"] is not None and not facts["dimension_match"]:
        return _result(embedding_ok=False, candidate_count=0, best_confidence=None,
                       threshold=threshold, source_present=False, provider_text_present=False,
                       provider_low_confidence=True, stage="embedding_failed", reason="dimension_mismatch", embedding_facts=facts)
    try:
        candidates = retrieve_fn(client, embedding, limit=5)
    except Exception:
        return _result(embedding_ok=True, candidate_count=0, best_confidence=None,
                       threshold=threshold, source_present=False, provider_text_present=False,
                       provider_low_confidence=True, stage="retrieval_failed", reason="retrieval_failed", embedding_facts=facts)
    candidates = candidates if isinstance(candidates, list) else []
    valid = [row for row in candidates if isinstance(row, dict)]
    facts["filtered_candidate_count"] = len(valid)
    scores = [float(row["confidence"]) for row in valid if isinstance(row.get("confidence"), (int, float))]
    best = max(scores) if scores else None
    source_present = any(isinstance(row.get("source_filename"), str) and bool(row["source_filename"].strip()) for row in valid)
    if not valid:
        return _result(embedding_ok=True, candidate_count=0, best_confidence=None,
                       threshold=threshold, source_present=False, provider_text_present=False,
                       provider_low_confidence=True, stage="no_candidates", reason="no_candidates", embedding_facts=facts)
    if best is None or best < threshold:
        return _result(embedding_ok=True, candidate_count=len(valid), best_confidence=best,
                       threshold=threshold, source_present=source_present, provider_text_present=False,
                       provider_low_confidence=True, stage="below_threshold", reason="below_threshold", embedding_facts=facts)
    if not source_present:
        return _result(embedding_ok=True, candidate_count=len(valid), best_confidence=best,
                       threshold=threshold, source_present=False, provider_text_present=False,
                       provider_low_confidence=True, stage="source_missing", reason="source_missing", embedding_facts=facts)
    provider = provider_factory(client, settings, embed_query_fn=runtime_embed, retrieve_candidates_fn=retrieve_fn)
    try:
        draft = provider.answer(QUESTION)
    except Exception:
        return _result(embedding_ok=True, candidate_count=len(valid), best_confidence=best,
                       threshold=threshold, source_present=True, provider_text_present=False,
                       provider_low_confidence=True, stage="answer_generation_failed", reason="answer_generation_failed", embedding_facts=facts)
    text_present = isinstance(getattr(draft, "text", None), str) and bool(draft.text.strip())
    low = bool(getattr(draft, "low_confidence", True))
    if low or not text_present:
        return _result(embedding_ok=True, candidate_count=len(valid), best_confidence=best,
                       threshold=threshold, source_present=True, provider_text_present=False,
                       provider_low_confidence=True, stage="provider_low_confidence", reason="provider_low_confidence", embedding_facts=facts)
    return _result(embedding_ok=True, candidate_count=len(valid), best_confidence=best,
                   threshold=threshold, source_present=True, provider_text_present=True,
                   provider_low_confidence=False, stage="success", reason="success", embedding_facts=facts)


def print_result(result: dict[str, Any]) -> None:
    score = result["best_confidence"]
    print("mode=knowledge_diagnostic")
    print(f"embedding_ok={str(result['embedding_ok']).lower()}")
    print(f"candidate_count={result['candidate_count']}")
    print(f"best_confidence={score if score is not None else 'none'}")
    print(f"configured_threshold={result['configured_threshold']}")
    print(f"api_key_present={str(result['api_key_present']).lower()}")
    print(f"embedding_model_present={str(result['embedding_model_present']).lower()}")
    print(f"embedding_client_created={str(result['embedding_client_created']).lower()}")
    print(f"embedding_response_received={str(result['embedding_response_received']).lower()}")
    print(f"embedding_vector_valid={str(result['embedding_vector_valid']).lower()}")
    print(f"embedding_dimension={result['embedding_dimension'] if result['embedding_dimension'] is not None else 'none'}")
    print(f"stored_dimension={result['stored_dimension'] if result['stored_dimension'] is not None else 'none'}")
    print(f"dimension_match={str(result['dimension_match']).lower()}")
    for field in ("knowledge_documents_total", "knowledge_documents_raipur", "knowledge_documents_approved", "knowledge_documents_active", "knowledge_documents_eligible", "knowledge_chunks_total", "eligible_document_chunks", "chunks_with_embedding", "chunks_without_embedding", "raw_candidate_count"):
        print(f"{field}={result[field]}")
    raw_score = result["best_raw_confidence"]
    print(f"best_raw_confidence={raw_score if raw_score is not None else 'none'}")
    print(f"filtered_candidate_count={result['filtered_candidate_count']}")
    print(f"source_present={str(result['source_present']).lower()}")
    print(f"provider_text_present={str(result['provider_text_present']).lower()}")
    print(f"provider_low_confidence={str(result['provider_low_confidence']).lower()}")
    print(f"diagnostic_stage={result['diagnostic_stage']}")
    print(f"reason={result['reason']}")


def main() -> int:
    try:
        settings = get_settings()
        client = get_supabase_client()
        result = diagnose(settings, client)
    except Exception:
        result = _result(embedding_ok=False, candidate_count=0, best_confidence=None,
                         threshold=0.0, source_present=False, provider_text_present=False,
                         provider_low_confidence=True, stage="unknown", reason="unknown",
                         embedding_facts={"api_key_present": False, "embedding_model_present": False,
                                          "embedding_client_created": False, "embedding_response_received": False,
                                          "embedding_vector_valid": False, "embedding_dimension": None,
                                          "stored_dimension": None, "dimension_match": False,
                                          "knowledge_documents_total": 0, "knowledge_documents_raipur": 0,
                                          "knowledge_documents_approved": 0, "knowledge_documents_active": 0,
                                          "knowledge_documents_eligible": 0, "knowledge_chunks_total": 0,
                                          "eligible_document_chunks": 0, "chunks_with_embedding": 0,
                                          "chunks_without_embedding": 0, "raw_candidate_count": 0,
                                          "best_raw_confidence": None, "filtered_candidate_count": 0})
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
