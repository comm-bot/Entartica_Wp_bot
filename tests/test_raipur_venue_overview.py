"""Fake-only regressions for venue-level Raipur routing."""

from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft, RaipurConversationService


class _Knowledge:
    def __init__(self, result: KnowledgeDraft | None = None) -> None:
        self.calls: list[str] = []
        self.result = result or KnowledgeDraft(
            "Entartica Sea World Raipur is in Raipur, Chhattisgarh. It offers approved water activities and celebration experiences.",
            "raipur_general_information.md",
            0.8,
            False,
        )

    def answer(self, question: str) -> KnowledgeDraft:
        self.calls.append(question)
        return self.result

    def answer_service_details(self, question: str, service_name: str) -> KnowledgeDraft:
        self.calls.append(f"detail:{question}:{service_name}")
        return self.result


class _Bookings:
    def create_idempotent(self, record):
        return record, True


class _Availability:
    def check(self, _request):
        return AvailabilityResult("verification_required")


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"name": "Jet Ski", "slug": "jet-ski", "is_active": True}]

    def find_active_by_customer_text(self, _location_id, _text):
        return {"id": "jet-ski", "name": "Jet Ski", "slug": "jet-ski", "is_active": True}


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
        external_message_id="message",
        customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111",
        message_type="text",
        content=text,
        received_at=datetime.now(UTC),
    )


def _process(service: RaipurConversationService, text: str, state=None):
    return service.process(
        _message(text),
        customer={"id": "customer"},
        conversation={"id": "conversation", "location_id": "raipur"},
        source_message_id="message",
        current_state=state,
    )


def test_broad_entartica_raipur_overview_uses_general_knowledge_not_service_clarification():
    knowledge = _Knowledge()
    result = _process(_service(knowledge), "Can you provide me full information about this Entartica Raipur")

    assert knowledge.calls == ["Can you provide me full information about this Entartica Raipur"]
    assert result.detected_intent == "venue_overview"
    assert result.reason_code == "approved_knowledge"
    assert result.safe_metadata["response_basis"] == "active_rag"
    assert result.safe_metadata["venue_overview"] is True
    assert result.safe_metadata["source_filename"] == "raipur_general_information.md"
    assert "which raipur activity" not in result.draft_text.casefold()
    assert result.context.last_service_code is None
    assert result.context.active_topic == "entartica_raipur_overview"


def test_named_and_contextual_service_detail_still_use_exact_service_route():
    knowledge = _Knowledge()
    service = _service(knowledge)
    named = _process(service, "Information about Jet Ski")
    selected = ConversationContext(
        BookingDetails(None, "Jet Ski", None, None, None, None, None),
        last_service_name="Jet Ski",
        last_service_code="jet_ski_ride",
    )
    contextual = _process(service, "Information about", selected)

    assert named.detected_intent == "service_overview"
    assert contextual.detected_intent == "service_detail"
    assert all(call.startswith("detail:") for call in knowledge.calls)


def test_hinglish_venue_overview_and_general_question_do_not_prematurely_clarify():
    knowledge = _Knowledge()
    service = _service(knowledge)
    hinglish = _process(service, "Raipur Entartica ke bare mein batao")
    outside = _process(service, "What flights are available tomorrow?")

    assert hinglish.detected_intent == "venue_overview"
    assert outside.reason_code != "clarification_required"
    assert len(knowledge.calls) == 2


def test_typo_tolerant_raipur_information_request_uses_venue_overview():
    knowledge = _Knowledge()
    result = _process(_service(knowledge), "Canbyou provide info regarding Raipur information")

    assert result.detected_intent == "venue_overview"
    assert knowledge.calls == ["Canbyou provide info regarding Raipur information"]


def test_unknown_entartica_fact_remains_non_fabricated_after_generic_retrieval():
    knowledge = _Knowledge(KnowledgeDraft(None, None, None, True))
    result = _process(_service(knowledge), "What fuel does your Raipur boat consume?")

    assert knowledge.calls == ["What fuel does your Raipur boat consume?"]
    assert "fuel" not in result.draft_text.casefold()
    assert result.reason_code in {"clarification_required", "approved_safe_fallback"}
