"""Tests for controlled local extraction and Raipur-only retrieval plumbing."""

from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock
from zipfile import ZipFile

from app.rag.knowledge import (
    chunk_hash,
    chunk_text,
    extract_approved_docx,
    faq_question,
    faq_topic,
    section_chunks,
)
from app.rag.raipur_ingestion import build_plan
from app.services.knowledge_intent import classify_knowledge_intent
from app.services.knowledge_evidence import lexical_evidence
from app.services.raipur_answers import generate_raipur_answer
from scripts import ingest_raipur_knowledge as celebration_ingestion
from scripts import test_raipur_retrieval as retrieval
from scripts import evaluate_raipur_retrieval as evaluation
from scripts import cleanup_development_unanswered as cleanup
from scripts import test_raipur_answers as answer_script


ROOT = Path(__file__).resolve().parents[1]


def _docx(path: Path, paragraph: str) -> None:
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body><w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p></w:body></w:document>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)


def test_canonical_manifest_documents_have_required_active_metadata() -> None:
    plan, errors = build_plan(ROOT)
    documents = [row.document for row in plan if row.document is not None]

    assert not errors
    assert len(documents) == 23
    for document in documents:
        assert document.metadata["location_code"] == "raipur"
        assert document.metadata["approval_status"] == "approved"
        assert document.metadata["customer_facing"] is True
        assert document.metadata["catalogue_status"] == "active"


def test_rejected_document_status_refuses_local_ingestion(tmp_path) -> None:
    document_path = tmp_path / "document.docx"
    _docx(document_path, "Document Status: Pending Approval")

    try:
        extract_approved_docx(document_path, "faq")
    except ValueError as error:
        assert str(error) == "Knowledge document has a rejected approval status."
    else:
        raise AssertionError("Expected rejected approval status to be refused.")


def test_chunks_are_deterministic_and_hashed_without_logging_content() -> None:
    text = "one two three " * 300
    chunks = chunk_text(text, maximum_characters=100)

    assert len(chunks) > 1
    assert chunks == chunk_text(text, maximum_characters=100)
    assert all(len(chunk_hash(chunk)) == 64 for chunk in chunks)


def test_duplicate_canonical_document_skips_embedding_calls() -> None:
    plan, _errors = build_plan(ROOT)
    document = next(row.document for row in plan if row.document and row.document.source_file == "active/faq/raipur_celebration_faq.md")
    query = MagicMock(); query.select.return_value = query; query.eq.return_value = query; query.execute.return_value = MagicMock(data=[{"id": "doc-id", "document_version": f"{document.checksum}:raipur_unified_v1", "is_active": True}])
    client = MagicMock(); client.table.return_value = query
    assert celebration_ingestion.ingest_document(client, document, MagicMock(), embedder=lambda *_: (_ for _ in ()).throw(AssertionError("must not embed duplicates"))) == ("unchanged", 0)


def test_retrieval_excludes_other_locations_and_allows_approved_global() -> None:
    documents_query = MagicMock()
    documents_query.select.return_value = documents_query
    documents_query.eq.return_value = documents_query
    documents_query.or_.return_value = documents_query
    documents_query.execute.return_value = MagicMock(data=[
        {"id": "raipur", "source_file": "raipur.docx", "metadata": {"location_code": "raipur", "source_filename": "raipur.docx", "document_category": "faq"}},
        {"id": "global", "source_file": "global.docx", "metadata": {"location_code": "global", "global_approved": True, "source_filename": "global.docx", "document_category": "policy"}},
        {"id": "other", "source_file": "other.docx", "metadata": {"location_code": "delhi", "source_filename": "other.docx", "document_category": "faq"}},
    ])
    chunks_query = MagicMock()
    chunks_query.select.return_value = chunks_query
    chunks_query.in_.return_value = chunks_query
    chunks_query.execute.return_value = MagicMock(data=[
        {"knowledge_document_id": "raipur", "content": "Raipur excerpt", "embedding": "[1,0]"},
        {"knowledge_document_id": "global", "content": "Global excerpt", "embedding": "[0.8,0.2]"},
        {"knowledge_document_id": "other", "content": "Other excerpt", "embedding": "[1,0]"},
    ])
    client = MagicMock()
    client.table.side_effect = lambda table: documents_query if table == "knowledge_documents" else chunks_query

    candidates = retrieval.retrieve_candidates(client, [1.0, 0.0], limit=5)
    results = retrieval.accepted_results(candidates, minimum_similarity=0.65, limit=5)

    assert [result["source_filename"] for result in results] == ["raipur.docx", "global.docx"]


def test_similarity_threshold_excludes_below_accepts_equal_and_above() -> None:
    candidates = [
        {"score": 0.636, "source_filename": "below.docx"},
        {"score": 0.65, "source_filename": "equal.docx"},
        {"score": 0.9, "source_filename": "above.docx"},
    ]

    accepted = retrieval.accepted_results(candidates, minimum_similarity=0.65, limit=5)

    assert [result["source_filename"] for result in accepted] == ["above.docx", "equal.docx"]
    assert retrieval.accepted_results([], minimum_similarity=0.65, limit=5) == []


def test_diagnostic_mode_never_records_questions_or_prints_content(monkeypatch, capsys) -> None:
    settings = MagicMock(embedding_configuration_is_valid=lambda: True, knowledge_min_similarity=0.65, knowledge_top_k=5)
    monkeypatch.setattr(retrieval, "Settings", lambda: settings)
    monkeypatch.setattr(retrieval, "get_supabase_client", lambda: MagicMock())
    monkeypatch.setattr(retrieval, "embed_texts", lambda texts, settings: [[1.0, 0.0]])
    monkeypatch.setattr(retrieval, "retrieve_candidates", lambda client, embedding, limit: [
        {"source_filename": "safe.docx", "category": "faq", "score": 0.636, "excerpt": "private content"}
    ])
    monkeypatch.setattr(retrieval, "record_unanswered_question", lambda *args: (_ for _ in ()).throw(AssertionError("must not record")))
    monkeypatch.setattr(sys, "argv", ["test_raipur_retrieval.py", "--question", "private question", "--diagnostic"])

    assert retrieval.main() == 0
    output = capsys.readouterr().out
    assert "intent=unknown" in output
    assert "final_acceptance=no" in output
    assert "private question" not in output
    assert "private content" not in output
    assert "minimum_similarity" not in output


def test_deterministic_intents_use_preferred_categories() -> None:
    assert classify_knowledge_intent("Where is Raipur located?").preferred_categories == ("location_information",)
    assert classify_knowledge_intent("What activities are available?").preferred_categories == ("services",)
    assert classify_knowledge_intent("Is advance booking required?").preferred_categories == ("booking_policy",)
    assert classify_knowledge_intent("What safety rules apply to children?").preferred_categories == ("safety_guidelines",)
    assert classify_knowledge_intent("Show FAQ").preferred_categories == ("faq",)
    assert classify_knowledge_intent("Tell me something unrelated").intent == "unknown"
    unsupported = classify_knowledge_intent("What services are available in Indore?")
    assert unsupported.intent == "unsupported_location"
    assert unsupported.human_handover_required is True


def test_intent_routing_normalizes_punctuation_and_common_approved_phrases() -> None:
    assert classify_knowledge_intent("How can I book?").intent == "booking"
    assert classify_knowledge_intent("What is the price?").intent == "booking"
    assert classify_knowledge_intent("How can I get a quotation?").intent == "booking"
    assert classify_knowledge_intent("What are the operating timings?").intent == "location"
    assert classify_knowledge_intent("What water sports are available?").intent == "services"
    assert classify_knowledge_intent("What can families do?").intent == "services"
    assert classify_knowledge_intent("Are life jackets provided?").intent == "safety"


def test_faq_metadata_uses_the_question_not_the_injected_general_heading() -> None:
    plan, _errors = build_plan(ROOT)
    document = next(row.document for row in plan if row.document and row.document.source_file == "active/faq/raipur_celebration_faq.md")
    first_chunk = next(chunk for chunk in section_chunks(document) if "?" in chunk.text)

    assert faq_question(first_chunk).endswith("?")
    assert faq_question(first_chunk) == first_chunk.section_heading


def test_preferred_category_wins_over_higher_scoring_faq_and_fallback_is_safe() -> None:
    location_intent = classify_knowledge_intent("Where is Raipur located?")
    candidates = [
        {"category": "faq", "score": 0.627, "source_filename": "faq.docx"},
        {"category": "location_information", "score": 0.5, "source_filename": "location.docx"},
    ]
    decision = retrieval.select_category_aware_result(candidates, intent=location_intent, minimum_similarity=0.367, limit=5)
    assert decision.selected is not None
    assert decision.selected["category"] == "location_information"
    assert decision.preferred_category_match is True

    booking_intent = classify_knowledge_intent("Is advance booking required?")
    fallback = retrieval.select_category_aware_result(
        [{"category": "booking_policy", "score": 0.3}, {"category": "faq", "score": 0.5}],
        intent=booking_intent,
        minimum_similarity=0.367,
        limit=5,
    )
    assert fallback.selected == {"category": "faq", "score": 0.5}


def test_unsupported_location_never_selects_raipur_candidate() -> None:
    decision = retrieval.select_category_aware_result(
        [{"category": "services", "score": 0.9, "source_filename": "raipur_services.docx"}],
        intent=classify_knowledge_intent("What services are available in Indore?"),
        minimum_similarity=0.367,
        limit=5,
    )
    assert decision.selected is None
    assert decision.low_confidence is True
    assert decision.human_handover_required is True


def test_lexical_evidence_uses_phrases_keywords_synonyms_and_rejects_category_only() -> None:
    intent = classify_knowledge_intent("What activities are available at Raipur?")
    evidence = lexical_evidence("What activities are available at Raipur?", "Available activity options include boating.", intent, 0.30)
    assert evidence.has_sufficient_evidence is True
    assert evidence.reason_code in {"sufficient_phrase_match", "sufficient_keyword_match"}
    weak = lexical_evidence("What activities are available at Raipur?", "General information.", intent, 0.30)
    assert weak.has_sufficient_evidence is False
    assert weak.reason_code == "no_lexical_match"
    assert lexical_evidence("weather in Delhi", "weather information", classify_knowledge_intent("weather in Delhi"), .30).reason_code == "unsupported_location"


def test_raipur_answer_is_source_grounded_or_handed_to_human() -> None:
    answer = generate_raipur_answer({"content": "Approved policy.", "source_filename": "policy.docx", "score": .7}, low_confidence=False)
    assert answer.answer == "Approved policy."
    assert answer.source_filenames == ("policy.docx",)
    assert generate_raipur_answer(None, low_confidence=True).human_handover_required is True


def test_structured_faq_answer_strips_internal_metadata_and_rejects_empty_answer() -> None:
    content = """## What is Houseboat Celebration?
Intent: service_detail
Service: Houseboat Celebration
Automatic Reply Allowed: Yes
Human Handover Required: No
Answer:
Houseboat Celebration is offered at Jhanjh Lake for special occasions.
Source Reference:
internal-reference
"""
    answer = generate_raipur_answer({"content": content, "source_filename": "faq.md", "score": .8}, low_confidence=False)
    assert answer.answer == "Houseboat Celebration is offered at Jhanjh Lake for special occasions."
    assert all(label not in answer.answer for label in ("Intent:", "Service:", "Automatic Reply", "Human Handover", "Source Reference"))
    empty = generate_raipur_answer({"content": "What is Houseboat Celebration?\nIntent: service_detail\nAnswer:\nSource Reference: internal", "source_filename": "faq.md", "score": .8}, low_confidence=False)
    assert empty.answer is None and empty.human_handover_required is True


class _AnswerSettings:
    knowledge_min_similarity = 0.65
    knowledge_top_k = 5
    knowledge_lexical_min_score = 0.30

    def embedding_configuration_is_valid(self) -> bool:
        return True


def test_raipur_answer_script_is_directly_importable_from_project_root() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "test_raipur_answers.py"), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--question" in completed.stdout


def test_local_answers_are_grounded_for_services_booking_and_safety(monkeypatch) -> None:
    candidates = {
        "What activities are available at Raipur?": {
            "category": "services", "score": .70, "content": "Available activities include boating.", "source_filename": "raipur_services.docx"
        },
        "Is submitting an enquiry a confirmed booking?": {
            "category": "booking_policy", "score": .70, "content": "An enquiry is not a booking confirmation.", "source_filename": "raipur_booking_policy.docx"
        },
        "What safety rules apply?": {
            "category": "safety_guidelines", "score": .70, "content": "Safety rules include life jacket guidance.", "source_filename": "raipur_safety_guidelines.docx"
        },
    }
    monkeypatch.setattr(answer_script, "retrieve_candidates", lambda *_args, **_kwargs: [candidates[current_question]])

    for current_question, expected_source in (
        ("What activities are available at Raipur?", "raipur_services.docx"),
        ("Is submitting an enquiry a confirmed booking?", "raipur_booking_policy.docx"),
        ("What safety rules apply?", "raipur_safety_guidelines.docx"),
    ):
        answer, decision, reason = answer_script.local_answer_for_question(
            current_question,
            settings=_AnswerSettings(),  # type: ignore[arg-type]
            client=MagicMock(),
            embedder=lambda _questions, _settings: [[1.0, 0.0]],
        )
        assert answer.human_handover_required is False
        assert answer.source_filenames == (expected_source,)
        assert decision.selected is not None
        assert reason == "accepted"


def test_local_answer_handover_for_unrelated_other_location_low_confidence_and_missing_result(monkeypatch) -> None:
    monkeypatch.setattr(answer_script, "retrieve_candidates", lambda *_args, **_kwargs: [])
    for question, expected_reason in (
        ("What flights are available tomorrow?", "no_raipur_candidate"),
        ("What activities are available in Indore?", "unsupported_location"),
    ):
        answer, _decision, reason = answer_script.local_answer_for_question(
            question,
            settings=_AnswerSettings(),  # type: ignore[arg-type]
            client=MagicMock(),
            embedder=lambda _questions, _settings: [[1.0, 0.0]],
        )
        assert answer.human_handover_required is True
        assert answer.answer is None
        assert reason == expected_reason

    monkeypatch.setattr(
        answer_script,
        "retrieve_candidates",
        lambda *_args, **_kwargs: [{
            "category": "services", "score": .64, "content": "Available activities include boating.",
            "source_filename": "raipur_services.docx",
        }],
    )
    answer, decision, reason = answer_script.local_answer_for_question(
        "What activities are available at Raipur?",
        settings=_AnswerSettings(),  # type: ignore[arg-type]
        client=MagicMock(),
        embedder=lambda _questions, _settings: [[1.0, 0.0]],
    )
    assert decision.diagnostic_candidate is not None
    assert answer.human_handover_required is True
    assert reason == "low_confidence"
    assert generate_raipur_answer({"content": "", "source_filename": "safe.docx", "score": .7}, low_confidence=False).human_handover_required is True
    assert generate_raipur_answer(None, low_confidence=False).human_handover_required is True


def test_answer_script_output_is_safe_and_has_no_channel_or_chat_dependencies(monkeypatch, capsys) -> None:
    answer = generate_raipur_answer(
        {"content": "Approved answer.", "source_filename": "C:/private/raipur_services.docx", "score": .7},
        low_confidence=False,
    )
    monkeypatch.setattr(answer_script, "Settings", _AnswerSettings)
    monkeypatch.setattr(answer_script, "get_supabase_client", lambda: MagicMock())
    monkeypatch.setattr(answer_script, "local_answer_for_question", lambda *_args, **_kwargs: (answer, MagicMock(), "accepted"))
    monkeypatch.setattr(sys, "argv", ["test_raipur_answers.py", "--question", "private question"])

    assert answer_script.main() == 0
    output = capsys.readouterr().out
    assert "raipur_services.docx" in output
    assert "C:/private" not in output
    assert "private question" not in output
    source = (ROOT / "scripts" / "test_raipur_answers.py").read_text(encoding="utf-8").casefold()
    assert "app.integrations.exotel" not in source
    assert "chat.completions" not in source
    assert "send_whatsapp" not in source


def test_unanswered_question_is_recorded_once_without_logging_question_content() -> None:
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.maybe_single.return_value = query
    query.insert.return_value = query
    query.execute.side_effect = [MagicMock(data=None), MagicMock(data=[{"id": "question-id"}]), MagicMock(data={"id": "question-id"})]
    client = MagicMock()
    client.table.return_value = query

    assert retrieval.record_unanswered_question(client, "private question") is True
    assert retrieval.record_unanswered_question(client, "private question") is False
    assert query.insert.call_count == 1


def test_threshold_recommendation_requires_separation() -> None:
    recommended, insufficient = evaluation.recommend_threshold([0.7, 0.8, 0.9], [0.4], [0.5])
    assert recommended == 0.501
    assert insufficient is False

    recommended, insufficient = evaluation.recommend_threshold([0.55, 0.6], [0.64], [0.63])
    assert recommended is None
    assert insufficient is True


def test_cleanup_is_confirmation_gated_and_scoped_to_development_origin(monkeypatch, capsys) -> None:
    query = MagicMock()
    query.delete.return_value = query
    query.eq.return_value = query
    query.execute.return_value = MagicMock(data=[])
    client = MagicMock()
    client.table.return_value = query
    monkeypatch.setattr(cleanup, "get_supabase_client", lambda: client)
    monkeypatch.setattr(sys, "argv", ["cleanup_development_unanswered.py"])

    assert cleanup.main() == 2
    client.table.assert_not_called()
    monkeypatch.setattr(sys, "argv", ["cleanup_development_unanswered.py", "--confirm"])
    assert cleanup.main() == 0
    query.eq.assert_called_once_with("record_origin", "development_retrieval_test")
    assert "deleted_development_records=0" in capsys.readouterr().out
