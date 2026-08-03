"""Offline regressions for full-question exact-service RAG routing."""

from datetime import UTC, datetime

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService


class Knowledge:
    def __init__(self) -> None:
        self.detail_calls: list[tuple[str, str, str | None]] = []
        self.calls = 0

    def answer(self, _question: str) -> KnowledgeDraft:
        self.calls += 1
        return KnowledgeDraft(None)

    def answer_service_details(self, question: str, service_name: str, service_code: str | None = None) -> KnowledgeDraft:
        self.detail_calls.append((question, service_name, service_code))
        value = question.casefold()
        if "drive" in value or "myself" in value:
            answer, heading = "Yes. The Jet Ski Ride is self-driven, so guests control the Jet Ski within the designated riding area after the required safety briefing. Current participation requirements should still be confirmed with Entartica staff.", "Can guests drive the Jet Ski themselves?"
        elif "swim" in value:
            answer, heading = "Swimming ability is generally not required for the Jet Ski Ride. Guests are typically fitted with a life jacket before entering the water. Current requirements should be confirmed with Entartica staff.", "Is swimming ability required?"
        elif "pregnan" in value:
            answer, heading = "The Jet Ski Ride is generally not recommended during pregnancy. Current eligibility should be confirmed with Entartica staff before the experience.", "Is the Jet Ski Ride suitable during pregnancy or for guests with health conditions?"
        elif "fall" in value:
            answer, heading = "If a rider falls, the engine generally stops using the engine cut-off lanyard. A water safety team is typically on standby to respond.", "What happens if a rider falls off?"
        elif "how many" in value or "capacity" in value:
            answer, heading = "Each Jet Ski typically accommodates one rider at a time, depending on the equipment model.", "How many people can ride one Jet Ski?"
        elif "how long" in value or "duration" in value:
            answer, heading = "Jet Ski sessions generally last around 5 to 10 minutes, depending on the operating schedule.", "How long is a session?"
        elif "difference" in value:
            answer, heading = "The Jet Ski Ride is self-driven, while Water Bike is a different water activity. The current experience details should be confirmed with Entartica staff.", "Comparison with Similar Experiences"
        else:
            answer, heading = "Jet Ski is an approved Raipur water-ride experience with service details available from approved knowledge.", "Definition"
        return KnowledgeDraft(answer, "active/services/jet_ski_ride.md", 0.8, False, heading, 1)


class Services:
    def list_active_for_location(self, _location_id: str):
        return [
            {"id": "jet", "name": "Jet Ski", "slug": "jet-ski", "is_active": True},
            {"id": "water-bike", "name": "Water Bike", "slug": "water-bike", "is_active": True},
        ]


class Bookings:
    def create_idempotent(self, record):
        return record, True


class Availability:
    def check(self, _request):
        return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class Drafts:
    def create_outbound_draft(self, **_kwargs):
        raise AssertionError("draft persistence is disabled")


def process(question: str):
    knowledge = Knowledge()
    services = Services()
    service = RaipurConversationService(
        knowledge=knowledge,
        bookings=BookingEnquiryService(Bookings(), Availability(), services),
        drafts=Drafts(),
        services=services,
        location={"id": "raipur"},
        persist_drafts=False,
    )
    result = service.process(
        NormalizedInboundMessage(
            external_message_id="message",
            customer_whatsapp_number="+910000000000",
            business_whatsapp_number="+911111111111",
            message_type="text",
            content=question,
            received_at=datetime(2026, 7, 29, tzinfo=UTC),
        ),
        customer={"id": "customer"},
        conversation={"id": "conversation", "location_id": "raipur"},
        source_message_id="message",
    )
    return result, knowledge


def assert_exact_rag(question: str, intent: str, topic: str, answer_terms: tuple[str, ...]):
    result, knowledge = process(question)
    assert result.detected_intent == intent
    assert result.safe_metadata["response_basis"] == "active_rag"
    assert result.safe_metadata["retrieval_service_code"] == "jet_ski_ride"
    assert result.safe_metadata["question_topic"] == topic
    assert result.safe_metadata["source_filename"] == "active/services/jet_ski_ride.md"
    assert knowledge.detail_calls == [(result.safe_metadata["retrieval_query"], "Jet Ski", "jet_ski_ride")]
    assert all(term in result.draft_text.casefold() for term in answer_terms)
    assert result.draft_text != "Yes, Jet Ski is offered at Entartica Raipur."
    assert knowledge.calls == 0


def test_service_existence_uses_exact_service_overview_route():
    result, knowledge = process("Do you offer Jet Ski?")
    assert result.detected_intent == "service_overview"
    assert result.safe_metadata["response_basis"] == "active_rag"
    assert "is offered at entartica raipur" not in result.draft_text.casefold()
    assert knowledge.detail_calls == [("do you offer jet ski?", "Jet Ski", "jet_ski_ride")]


@pytest.mark.parametrize(
    ("question", "intent", "topic", "answer_terms"),
    [
        ("Can I drive Jet Ski myself?", "service_operation_question", "self_driving", ("self-driven", "control")),
        ("LP can I drive jet ski myself ?", "service_operation_question", "self_driving", ("self-driven", "control")),
        ("Do I need to know how to swim to ride a Jet Ski??", "participation_eligibility", "swimming_requirement", ("swimming", "life jacket")),
        ("Can pregnent women ride Jet Ski?", "participation_eligibility", "pregnancy", ("pregnancy", "not recommended")),
        ("What happens if I fall from Jet Ski?", "service_detail", "fall_safety", ("engine", "lanyard")),
        ("How many people can ride one Jet Ski?", "service_detail", "capacity", ("one rider",)),
        ("How long is the Jet Ski ride?", "service_detail", "duration", ("5 to 10 minutes",)),
        ("What is the difference between Jet Ski and Water Bike?", "service_detail", "service_comparison", ("water bike", "self-driven")),
    ],
)
def test_specific_service_questions_use_complete_normalized_question_for_exact_rag(question, intent, topic, answer_terms):
    assert_exact_rag(question, intent, topic, answer_terms)


def test_restricted_price_and_live_availability_use_controlled_workflows_not_service_confirmation():
    price, price_knowledge = process("What is the Jet Ski price?")
    availability, availability_knowledge = process("Is Jet Ski available tomorrow?")
    assert price.human_handover_required and price.detected_intent == "pricing"
    assert availability.human_handover_required and availability.detected_intent == "availability"
    assert price.draft_text != "Yes, Jet Ski is offered at Entartica Raipur."
    assert availability.draft_text != "Yes, Jet Ski is offered at Entartica Raipur."
    assert price_knowledge.detail_calls == [] and availability_knowledge.detail_calls == []


def test_unknown_information_uses_a_safe_response_not_silence():
    result, knowledge = process("Please explain the underwater music rules")
    assert result.draft_text
    assert result.safe_metadata["response_mode"] in {"clarification_question", "approved_safe_fallback"}
    assert knowledge.detail_calls == []
