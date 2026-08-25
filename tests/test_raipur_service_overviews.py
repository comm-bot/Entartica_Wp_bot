"""Reusable exact-service overview and context-routing regressions."""

from __future__ import annotations

from datetime import UTC, datetime
import re

import pytest

from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_answers import RaipurAnswer
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService


_SERVICES = (
    ("Staycation Combo", "staycation-combo", "staycation_combo", "I want to learn about Staycation"),
    ("Daycation Package", "daycation-package", "daycation_package", "I want to learn about Daycation"),
    ("Jet Ski", "jet-ski", "jet_ski_ride", "I want to learn about Jet Ski"),
    ("Kayak", "kayak", "kayaking", "I want to learn about Kayaking"),
    ("Floating Gazebo", "floating-gazebo", "floating_gazebo", "I want to learn about Floating Gazebo"),
)


class _Knowledge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def answer(self, _question: str) -> KnowledgeDraft:
        return KnowledgeDraft(None)

    def answer_service_details(self, question: str, name: str, code: str | None = None) -> KnowledgeDraft:
        self.calls.append((question, name, code))
        return KnowledgeDraft(f"{name} approved overview.", f"{code}.md", .8, False, "Definition", 3)


class _TopicKnowledge(_Knowledge):
    def __init__(self) -> None:
        super().__init__()
        self.topic_calls: list[tuple[str, str, str | None, str]] = []

    def answer_service_details(self, question: str, name: str, code: str | None = None, *, detail_mode: str = "overview", **_kwargs) -> KnowledgeDraft:
        self.calls.append((question, name, code))
        self.topic_calls.append((question, name, code, detail_mode))
        return KnowledgeDraft(
            f"{name} approved {detail_mode} information.",
            f"{code}.md",
            .8,
            False,
            detail_mode.replace("_", " ").title(),
            1,
        )


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"name": name, "slug": slug, "is_active": True} for name, slug, _, _ in _SERVICES]


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


def _process(service: RaipurConversationService, text: str, state=None):
    message = NormalizedInboundMessage(
        external_message_id="service-overview-message",
        customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111",
        message_type="text",
        content=text,
        received_at=datetime.now(UTC),
    )
    return service.process(message, customer={"id": "customer"}, conversation={"id": "conversation", "location_id": "raipur"}, source_message_id="service-overview-message", current_state=state)


@pytest.mark.parametrize(("name", "slug", "code", "question"), _SERVICES)
def test_every_named_service_uses_its_own_overview_and_persists_context(name, slug, code, question):
    knowledge = _Knowledge()
    result = _process(_service(knowledge), question)

    assert result.detected_intent == "service_overview"
    assert result.context.last_service_name == name
    assert result.context.last_service_code == slug.replace("-", "_")
    assert result.draft_text.startswith(name)
    assert "is offered at" not in result.draft_text.casefold()
    assert knowledge.calls == [(question.casefold(), name, code)]


def test_pronoun_followup_uses_existing_service_and_new_named_service_replaces_it():
    knowledge = _Knowledge()
    service = _service(knowledge)
    first = _process(service, "Tell me about Staycation")
    followup = _process(service, "Tell me more about it", first.context)
    switched = _process(service, "Tell me about Jet Ski", followup.context)

    assert followup.context.last_service_code == "staycation_combo"
    assert knowledge.calls[1][1:] == ("Staycation Combo", "staycation_combo")
    assert knowledge.calls[1][0].startswith("Provide additional approved details about Staycation Combo.")
    assert switched.context.last_service_code == "jet_ski"
    assert switched.draft_text.startswith("Jet Ski")


def test_contextual_more_information_and_everything_use_exact_service_retrieval():
    knowledge = _Knowledge()
    service = _service(knowledge)
    selected = _process(service, "I want to learn about Staycation")
    more = _process(service, "Can you provide more information on this", selected.context)
    everything = _process(service, "Everything", more.context)

    assert more.detected_intent == "service_more_details"
    assert more.context.last_service_code == "staycation_combo"
    assert knowledge.calls[1][0].startswith("Provide additional approved details about Staycation Combo.")
    assert everything.detected_intent == "service_full_overview"
    assert everything.reason_code == "approved_service_full_overview"
    assert everything.context.last_service_code == "staycation_combo"


@pytest.mark.parametrize(
    ("question", "name", "code", "topic"),
    (
        ("Kayak me kitne log beth sakte hain?", "Kayak", "kayaking", "capacity"),
        ("Jet Ski ride kitni der ki hoti hai?", "Jet Ski", "jet_ski_ride", "duration"),
        ("Kayak ke liye swimming aana zaruri hai?", "Kayak", "kayaking", "swimming_requirement"),
        ("Floating Gazebo mein kya included hai?", "Floating Gazebo", "floating_gazebo", "inclusions"),
        ("Jet Ski kaun kar sakta hai?", "Jet Ski", "jet_ski_ride", "eligibility"),
        ("Floating Gazebo kab tak chalta hai?", "Floating Gazebo", "floating_gazebo", "operating_hours"),
        ("Staycation Combo ke safety rules kya hain?", "Staycation Combo", "staycation_combo", "safety"),
        ("Kayak kaise chalta hai?", "Kayak", "kayaking", "how_it_works"),
    ),
)
def test_named_multilingual_topic_question_uses_exact_service_rag_before_confirmation(question, name, code, topic):
    knowledge = _TopicKnowledge()
    result = _process(_service(knowledge), question)

    assert result.safe_metadata["response_basis"] == "active_rag"
    assert result.safe_metadata["retrieval_service_code"] == code
    assert result.safe_metadata["question_topic"] == topic
    assert result.context.active_topic == topic
    assert result.context.active_entity_name == name
    assert len(knowledge.topic_calls) == 1
    assert knowledge.topic_calls[0][1:] == (name, code, topic)
    assert "is offered at" not in result.draft_text.casefold()


def test_contextual_topic_follow_up_retains_the_exact_selected_service():
    knowledge = _TopicKnowledge()
    service = _service(knowledge)
    selected = _process(service, "Tell me about Kayak")
    result = _process(service, "Kitni der ki hoti hai?", selected.context)

    assert result.safe_metadata["response_basis"] == "active_rag"
    assert result.context.last_service_name == "Kayak"
    assert result.context.active_topic == "duration"
    assert knowledge.topic_calls[-1][1:] == ("Kayak", "kayaking", "duration")


@pytest.mark.parametrize(
    ("question", "name", "code"),
    (
        ("Staycation hota kya he?", "Staycation Combo", "staycation_combo"),
        ("Staycation k bare me kuch batao", "Staycation Combo", "staycation_combo"),
        ("Info of staycation", "Staycation Combo", "staycation_combo"),
        ("Do you offer Staycation?", "Staycation Combo", "staycation_combo"),
        ("Do you have Jet Ski?", "Jet Ski", "jet_ski_ride"),
        ("Kayaking service hai kya?", "Kayak", "kayaking"),
        ("Floating Gazebo details.", "Floating Gazebo", "floating_gazebo"),
        ("Tell me about Daycation.", "Daycation Package", "daycation_package"),
    ),
)
def test_named_service_information_and_presence_questions_always_use_exact_overview(question, name, code):
    knowledge = _TopicKnowledge()
    result = _process(_service(knowledge), question)

    assert result.detected_intent == "service_overview"
    assert result.safe_metadata["response_basis"] == "active_rag"
    assert result.safe_metadata["retrieval_service_code"] == code
    assert result.context.last_service_name == name
    assert result.context.active_topic == "service_overview"
    assert knowledge.topic_calls[0][1:] == (name, code, "overview")
    assert not re.fullmatch(r"yes, .+ is (?:offered|available) at entartica raipur\.", result.draft_text.casefold())


def test_live_availability_is_not_replaced_by_static_service_overview():
    knowledge = _TopicKnowledge()
    result = _process(_service(knowledge), "Is Staycation available tomorrow?")

    assert result.detected_intent == "availability"
    assert result.human_handover_required
    assert knowledge.topic_calls == []


def _candidate(score, heading, content):
    return {
        "content": content,
        "source_filename": "jet_ski_ride.md",
        "confidence": score,
        "metadata": {
            "location_code": "raipur", "service_code": "jet_ski_ride", "customer_facing": True,
            "is_active": True, "approval_status": "approved", "retrieval_priority": "service_specific",
            "section_heading": heading,
        },
    }


def test_topic_specific_question_prioritizes_its_service_section():
    rows = [
        _candidate(.95, "Comparison with Similar Services", "Other service comparison."),
        _candidate(.70, "Definition", "Jet Ski is an approved service overview."),
        _candidate(.60, "What Is Included", "Approved inclusion information."),
    ]
    provider = RaipurKnowledgeProvider(
        object(), type("Settings", (), {"raipur_knowledge_min_confidence": .65})(),
        embed_query_fn=lambda _question, _settings: [1],
        retrieve_candidates_fn=lambda _client, _vector, limit: rows,
        answer_generator=lambda row, low_confidence: RaipurAnswer(row["content"], False, row["score"], (row["source_filename"],)),
    )

    result = provider.answer_service_details("What is included with Jet Ski?", "Jet Ski", "jet_ski_ride")

    assert result.section_heading == "What Is Included"
    assert result.text and result.text.startswith("Approved inclusion information.")
    assert "comparison" not in result.text.casefold()


def test_capacity_topic_prefers_capacity_heading_over_higher_scoring_definition():
    rows = [
        _candidate(.95, "Definition", "Definition evidence."),
        _candidate(.70, "Capacity", "Capacity evidence."),
        _candidate(.69, "Frequently Asked Questions", "FAQ evidence."),
    ]
    provider = RaipurKnowledgeProvider(
        object(), type("Settings", (), {"raipur_knowledge_min_confidence": .65})(),
        embed_query_fn=lambda _question, _settings: [1],
        retrieve_candidates_fn=lambda _client, _vector, limit: rows,
        answer_generator=lambda row, low_confidence: RaipurAnswer(row["content"], False, row["score"], (row["source_filename"],)),
    )

    result = provider.answer_service_details("Kayak me kitne log beth sakte hain?", "Jet Ski", "jet_ski_ride", detail_mode="capacity")

    assert result.section_heading == "Capacity"
    assert result.text and result.text.startswith("Capacity evidence.")


def test_full_overview_uses_multiple_exact_service_sections():
    rows = [
        _candidate(.8, heading, f"Approved section {index}.")
        for index, heading in enumerate(("Definition", "Experience Type", "General Experience", "Suitable For", "Key Characteristics", "What Is Included", "Comparison with Similar Services"), 1)
    ]
    seen: list[str] = []
    provider = RaipurKnowledgeProvider(
        object(), type("Settings", (), {"raipur_knowledge_min_confidence": .65})(),
        embed_query_fn=lambda _question, _settings: [1],
        retrieve_candidates_fn=lambda _client, _vector, limit: rows,
        answer_generator=lambda row, low_confidence: seen.append(row["content"]) or RaipurAnswer(row["content"], False, row["score"], (row["source_filename"],)),
    )

    result = provider.answer_service_details("Everything", "Jet Ski", "jet_ski_ride", full_overview=True)

    assert result.text is not None
    assert not seen  # raw section prose is no longer sent to the old answer generator
    assert "Approved section" in result.text
    assert "Approved section 7" not in result.text


def test_more_details_prefers_additional_operational_section_over_definition_or_booking():
    rows = [
        _candidate(.95, "Frequently Asked Questions — How Do I Book?", "Booking FAQ."),
        _candidate(.90, "Definition", "Definition evidence."),
        _candidate(.70, "How It Generally Works", "Operation evidence."),
        _candidate(.69, "Safety and Participation", "Safety evidence."),
    ]
    provider = RaipurKnowledgeProvider(
        object(), type("Settings", (), {"raipur_knowledge_min_confidence": .65})(),
        embed_query_fn=lambda _question, _settings: [1],
        retrieve_candidates_fn=lambda _client, _vector, limit: rows,
        answer_generator=lambda row, low_confidence: RaipurAnswer(row["content"], False, row["score"], (row["source_filename"],)),
    )

    result = provider.answer_service_details("Provide more details about it", "Jet Ski", "jet_ski_ride", detail_mode="more_details")

    assert result.section_heading == "How It Generally Works"
    assert result.text and "Operation evidence." in result.text
    assert "Booking FAQ" not in result.text
    assert "Booking FAQ" not in result.text
