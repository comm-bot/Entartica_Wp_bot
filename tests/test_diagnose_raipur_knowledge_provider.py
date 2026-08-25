from types import SimpleNamespace

from app.services.raipur.response_models import KnowledgeDraft
from scripts.diagnose_raipur_knowledge_provider import diagnose, print_result


SETTINGS = SimpleNamespace(raipur_knowledge_min_confidence=0.65)


def _embed(question, settings): return [1.0, 0.0]
def _corpus(client, embedding):
    return {"knowledge_documents_total": 1, "knowledge_documents_raipur": 1,
            "knowledge_documents_approved": 1, "knowledge_documents_active": 1,
            "knowledge_documents_eligible": 1, "knowledge_chunks_total": 1,
            "eligible_document_chunks": 1, "chunks_with_embedding": 1,
            "chunks_without_embedding": 0, "stored_dimension": 2,
            "dimension_match": True, "raw_candidate_count": 1,
            "best_raw_confidence": 0.8, "filtered_candidate_count": 1}
def _row(score=0.8, source="approved.docx"):
    return {"confidence": score, "source_filename": source, "content": "approved", "metadata": {"location_code": "raipur", "approval_status": "approved"}}


def test_embedding_and_retrieval_failures_are_safe():
    failed_embedding = diagnose(SETTINGS, object(), embed_fn=lambda *_: (_ for _ in ()).throw(RuntimeError("secret")))
    assert failed_embedding["diagnostic_stage"] == "embedding_failed"
    failed_retrieval = diagnose(SETTINGS, object(), embed_fn=_embed, retrieve_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private")), corpus_inspector=_corpus)
    assert failed_retrieval["diagnostic_stage"] == "retrieval_failed"


def test_no_candidates_below_threshold_and_missing_source():
    assert diagnose(SETTINGS, object(), embed_fn=_embed, retrieve_fn=lambda *_args, **_kwargs: [], corpus_inspector=_corpus)["diagnostic_stage"] == "no_candidates"
    assert diagnose(SETTINGS, object(), embed_fn=_embed, retrieve_fn=lambda *_args, **_kwargs: [_row(0.5)], corpus_inspector=_corpus)["diagnostic_stage"] == "below_threshold"
    assert diagnose(SETTINGS, object(), embed_fn=_embed, retrieve_fn=lambda *_args, **_kwargs: [_row(0.8, "")], corpus_inspector=_corpus)["diagnostic_stage"] == "source_missing"


def test_provider_low_confidence_and_success_are_safe(capsys):
    class LowProvider:
        def __init__(self, *args, **kwargs): pass
        def answer(self, question): return KnowledgeDraft(None, None, None, True)
    low = diagnose(SETTINGS, object(), embed_fn=_embed, retrieve_fn=lambda *_args, **_kwargs: [_row()], provider_factory=LowProvider, corpus_inspector=_corpus)
    assert low["diagnostic_stage"] == "provider_low_confidence"
    class GoodProvider:
        def __init__(self, *args, **kwargs): pass
        def answer(self, question): return KnowledgeDraft("private answer", "private.docx", 0.8, False)
    success = diagnose(SETTINGS, object(), embed_fn=_embed, retrieve_fn=lambda *_args, **_kwargs: [_row()], provider_factory=GoodProvider, corpus_inspector=_corpus)
    assert success["diagnostic_stage"] == "success" and success["provider_text_present"]
    print_result(success)
    output = capsys.readouterr().out
    assert "private answer" not in output and "private.docx" not in output and "mode=knowledge_diagnostic" in output
