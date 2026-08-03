"""Offline guards against leaking knowledge-authoring instructions."""

from types import SimpleNamespace

from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.rag.knowledge import KnowledgeSection
from app.services.raipur_answers import RaipurAnswer, clean_customer_evidence, compose_customer_response
from scripts.ingest_raipur_knowledge import _chunks


DAYCATION = '''## Suggested Chatbot Response

**When a guest asks: "Tell me about the Daycation Package at Entartica Raipur"**

The Daycation Package at Entartica Sea World, Raipur offers a full-day experience without an overnight stay. It typically includes day-use Club Room access for up to four guests, H2O Play Park access, selected boating experiences, and a food voucher. Current inclusions, pricing, and availability should be confirmed with the Entartica team.'''


def candidate(content, *, allowed=True, code="daycation_package"):
    return {
        "content": content,
        "source_filename": "active/services/daycation_package.md",
        "confidence": 0.8,
        "metadata": {
            "location_code": "raipur",
            "service_code": code,
            "customer_facing": True,
            "is_active": True,
            "approval_status": "approved",
            "retrieval_priority": "service_specific",
            "customer_output_allowed": allowed,
        },
    }


def provider(rows):
    settings = SimpleNamespace(raipur_knowledge_min_confidence=.65)
    return RaipurKnowledgeProvider(
        object(), settings,
        embed_query_fn=lambda *_: [1],
        retrieve_candidates_fn=lambda *_args, **_kwargs: rows,
        answer_generator=lambda row, low_confidence: RaipurAnswer(row["content"], False, row["score"], (row["source_filename"],)),
    )


def test_final_answer_removes_internal_labels_and_preserves_approved_daycation_facts():
    answer = compose_customer_response(DAYCATION, question="Can you give me details about daycation package in raipur")
    assert answer is not None
    assert "when a guest asks" not in answer.casefold()
    assert "suggested chatbot response" not in answer.casefold()
    assert "full-day experience" in answer
    assert "Club Room" in answer
    assert "H2O Play Park" in answer


def test_markdown_internal_variants_are_removed_without_removing_facts():
    content = "**Sample Chatbot Response:**\n*Customer asks: What is Aqua Cycle?*\nThe Aqua Cycle is a pedal-powered water activity."
    cleaned = clean_customer_evidence(content)
    assert cleaned == "The Aqua Cycle is a pedal-powered water activity."
    assert compose_customer_response(content, question="Tell me about Aqua Cycle") == cleaned


def test_provider_keeps_exact_service_filter_and_rejects_disallowed_chunk():
    blocked = candidate("Suggested Chatbot Response\nWhen a guest asks: Daycation?", allowed=False)
    allowed = candidate(DAYCATION)
    result = provider([blocked, allowed]).answer_service_details(
        "Tell me about Daycation Package", "Daycation Package", "daycation_package"
    )
    assert result.text and "full-day experience" in result.text
    assert "suggested chatbot response" not in result.text.casefold()
    assert result.source_filename == "active/services/daycation_package.md"


def test_ingestion_chunk_marks_example_section_as_non_customer_output():
    document = SimpleNamespace(
        metadata={"location_code": "raipur"},
        sections=(KnowledgeSection("Suggested Chatbot Response", None, DAYCATION),),
    )
    chunk = _chunks(document)[0]
    assert chunk["metadata"]["section_type"] == "example_response"
    assert chunk["metadata"]["customer_output_allowed"] is False
    assert "when a guest asks" not in chunk["content"].casefold()
    assert "full-day experience" in chunk["content"]


def test_pricing_and_availability_questions_remain_controlled():
    assert compose_customer_response(DAYCATION, question="What is the Daycation price?") is None
    assert compose_customer_response(DAYCATION, question="Is Daycation available tomorrow?") is None


def test_other_service_example_wrapper_is_also_cleaned():
    content = "## Suggested Chatbot Response\n**When a guest asks: Tell me about Jet Ski**\nThe Jet Ski Ride is self-driven after a safety briefing."
    answer = compose_customer_response(content, question="Tell me about Jet Ski")
    assert answer == "The Jet Ski Ride is self-driven after a safety briefing."


def test_capacity_fact_is_selected_before_introductory_evidence():
    content = (
        "The Kayaking experience is a calm water activity. "
        "Guests should follow the safety briefing. "
        "Each kayak accommodates up to two participants."
    )

    answer = compose_customer_response(content, question="Kayak me kitne log beth sakte hain?")

    assert answer is not None
    assert answer.startswith("Each kayak accommodates up to two participants.")


def test_service_overview_can_keep_more_than_two_approved_sentences():
    content = (
        "The Staycation Combo is an overnight Raipur experience. "
        "It combines accommodation and approved activities. "
        "Guests can enjoy the venue throughout their stay. "
        "Inclusions should be confirmed with the Entartica team."
    )

    answer = compose_customer_response(content, question="Staycation ke bare mein batao")

    assert answer is not None
    assert "Inclusions should be confirmed" in answer
