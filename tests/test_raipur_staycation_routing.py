"""Fake-only Staycation overview, ranking, and follow-up regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_answers import RaipurAnswer
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft, RaipurConversationService


class _Knowledge:
    def __init__(self) -> None:
        self.detail_queries: list[tuple[str, str, str | None]] = []
        self.generic_calls = 0

    def answer(self, _question: str) -> KnowledgeDraft:
        self.generic_calls += 1
        return KnowledgeDraft(None)

    def answer_service_details(self, question: str, name: str, code: str | None = None) -> KnowledgeDraft:
        self.detail_queries.append((question, name, code))
        return KnowledgeDraft(
            "Staycation Combo is an overnight resort package with accommodation and breakfast. "
            "It typically includes H2O Play Park access and selected boat activity passes; current inclusions require team confirmation.",
            "staycation_combo.md",
            0.8,
            False,
            "Definition",
            3,
        )


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"name": "Staycation Combo", "slug": "staycation-combo", "is_active": True}]

    def find_active_by_customer_text(self, _location_id, _text):
        return None


class _Bookings:
    def create_idempotent(self, row):
        return row, True


class _Availability:
    def check(self, _request):
        return AvailabilityResult("verification_required")


class _Drafts:
    def create_outbound_draft(self, **_kwargs):
        return {}, False


def _service(knowledge: _Knowledge) -> RaipurConversationService:
    services = _Services()
    return RaipurConversationService(
        knowledge=knowledge,
        bookings=BookingEnquiryService(_Bookings(), _Availability(), services),
        drafts=_Drafts(),
        services=services,
        persist_drafts=False,
    )


def _message(text: str) -> NormalizedInboundMessage:
    return NormalizedInboundMessage(
        external_message_id="staycation-message",
        customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111",
        message_type="text",
        content=text,
        received_at=datetime.now(UTC),
    )


def _process(service, text: str, state=None):
    return service.process(
        _message(text),
        customer={"id": "customer"},
        conversation={"id": "conversation", "location_id": "raipur"},
        source_message_id="staycation-message",
        current_state=state,
    )


def test_staycation_overview_uses_exact_service_rag_and_persists_context():
    knowledge = _Knowledge()
    result = _process(_service(knowledge), "I want to know about Staycation?")

    assert result.detected_intent == "service_overview"
    assert result.reason_code == "approved_service_detail"
    assert result.context.last_service_name == "Staycation Combo"
    assert result.context.last_service_code == "staycation_combo"
    assert knowledge.generic_calls == 0
    assert knowledge.detail_queries == [("i want to know about staycation?", "Staycation Combo", "staycation_combo")]
    assert "is offered at" not in result.draft_text.casefold()
    assert "overnight" in result.draft_text.casefold()


def test_existence_question_uses_exact_staycation_overview_and_saves_context():
    knowledge = _Knowledge()
    result = _process(_service(knowledge), "Do you offer Staycation?")

    assert result.detected_intent == "service_overview"
    assert result.context.last_service_code == "staycation_combo"
    assert result.reason_code == "approved_service_detail"
    assert knowledge.detail_queries == [("do you offer staycation?", "Staycation Combo", "staycation_combo")]
    assert "is offered at entartica raipur" not in result.draft_text.casefold()


def test_staycation_pronoun_and_inclusion_followups_use_contextual_exact_retrieval():
    knowledge = _Knowledge()
    service = _service(knowledge)
    selected = ConversationContext(
        BookingDetails(None, "Staycation Combo", None, None, None, None, None),
        last_service_name="Staycation Combo",
        last_service_code="staycation_combo",
    )
    more = _process(service, "Can I know more about it", selected)
    breakfast = _process(service, "Is breakfast included?", more.context)

    assert more.context.last_service_code == breakfast.context.last_service_code == "staycation_combo"
    assert all(name == "Staycation Combo" and code == "staycation_combo" for _, name, code in knowledge.detail_queries)
    assert knowledge.detail_queries[0][0].startswith("Provide additional approved details about Staycation Combo.")
    assert knowledge.detail_queries[1][0].startswith("Provide additional approved details about Staycation Combo.")


def _candidate(score, heading, content):
    return {
        "content": content,
        "source_filename": "staycation_combo.md",
        "confidence": score,
        "metadata": {
            "location_code": "raipur",
            "service_code": "staycation_combo",
            "customer_facing": True,
            "is_active": True,
            "approval_status": "approved",
            "retrieval_priority": "service_specific",
            "section_heading": heading,
        },
    }


def test_staycation_overview_reranks_definition_before_higher_similarity_comparison():
    rows = [
        _candidate(.95, "Comparison with Similar Packages", "The Daycation Package is a same-day option."),
        _candidate(.70, "Definition", "Staycation Combo is an overnight resort package with accommodation and breakfast."),
        _candidate(.69, "What Is Typically Included", "H2O Play Park access and selected boat activity passes are typically included."),
    ]
    provider = RaipurKnowledgeProvider(
        object(),
        SimpleNamespace(raipur_knowledge_min_confidence=.65),
        embed_query_fn=lambda _question, _settings: [1],
        retrieve_candidates_fn=lambda _client, _vector, limit: rows,
        answer_generator=lambda row, low_confidence: RaipurAnswer(row["content"], False, row["score"], (row["source_filename"],)),
    )

    result = provider.answer_service_details("Can you provide details about Staycation?", "Staycation Combo", "staycation_combo")

    assert result.section_heading == "Definition"
    assert result.text and result.text.casefold().startswith("staycation")
    assert not result.text.casefold().startswith("the daycation")


def test_staycation_pricing_remains_deterministic_handover():
    result = _process(_service(_Knowledge()), "What is the price of Staycation?")
    assert result.detected_intent == "pricing"
    assert result.human_handover_required
