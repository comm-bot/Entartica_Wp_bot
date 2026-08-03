"""Fake-only eligibility routing regressions for exact Raipur service knowledge."""

from datetime import UTC, datetime
import logging

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_automatic_replies import _safe_intent, eligible_for_automatic_reply
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService, _eligibility_response_addresses_subject


class _Knowledge:
    def __init__(self) -> None:
        self.detail_calls: list[tuple[str, str, str | None]] = []
        self.calls = 0

    def answer(self, _question: str) -> KnowledgeDraft:
        self.calls += 1
        return KnowledgeDraft(None)

    def answer_service_details(self, question: str, service_name: str, service_code: str | None = None) -> KnowledgeDraft:
        self.detail_calls.append((question, service_name, service_code))
        value = question.casefold()
        if any(term in value for term in ("pregnant", "pregnancy", "pregnent")):
            text = "Jet Ski Ride is generally not recommended during pregnancy. Current participation eligibility must be confirmed with Entartica staff before the experience."
            heading = "Is the Jet Ski Ride suitable during pregnancy or for guests with health conditions?"
        elif any(term in value for term in ("heart", "back")):
            text = "Jet Ski Ride participation for heart conditions or back problems must be confirmed with Entartica staff before the experience."
            heading = "Is the Jet Ski Ride suitable during pregnancy or for guests with health conditions?"
        elif "swimming" in value:
            text = "Swimming requirements for Jet Ski Ride must be confirmed with Entartica staff before the experience."
            heading = "Participation Requirements"
        else:
            text = "Child participation in Jet Ski Ride depends on the applicable safety requirements and staff assessment."
            heading = "Participation Requirements"
        return KnowledgeDraft(text, "jet_ski_ride.md", 0.8, False, heading)


class _Services:
    def list_active_for_location(self, _location_id: str):
        return [{"id": "jet", "name": "Jet Ski", "slug": "jet-ski", "is_active": True}]


class _Bookings:
    def create_idempotent(self, record):
        return record, True


class _Availability:
    def check(self, _request):
        return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class _Drafts:
    def create_outbound_draft(self, **_kwargs):
        raise AssertionError("draft persistence is disabled for this unit test")


def _service() -> tuple[RaipurConversationService, _Knowledge]:
    knowledge = _Knowledge()
    services = _Services()
    return (
        RaipurConversationService(
            knowledge=knowledge,
            bookings=BookingEnquiryService(_Bookings(), _Availability(), services),
            drafts=_Drafts(),
            services=services,
            location={"id": "raipur"},
            persist_drafts=False,
        ),
        knowledge,
    )


def _result(question: str):
    service, knowledge = _service()
    message = NormalizedInboundMessage(
        external_message_id="test-message",
        customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111",
        message_type="text",
        content=question,
        received_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
    result = service.process(
        message,
        customer={"id": "customer"},
        conversation={"id": "conversation", "location_id": "raipur"},
        source_message_id="test-message",
    )
    return result, knowledge


@pytest.mark.parametrize(
    "question",
    (
        "Can pregnent women ride jet ski?",
        "Can pregnant women ride Jet Ski?",
        "Pregnancy mein Jet Ski kar sakte hain?",
        "Is Jet Ski suitable during pregnancy?",
        "Can heart patients ride Jet Ski?",
        "Back problem hai, Jet Ski allowed hai?",
        "Is swimming required for Jet Ski?",
        "Can children ride Jet Ski?",
    ),
)
def test_eligibility_questions_use_exact_service_rag_before_catalogue_confirmation(question):
    result, knowledge = _result(question)

    assert result.detected_intent == "participation_eligibility"
    assert result.reason_code == "approved_service_eligibility"
    assert result.safe_metadata["response_basis"] == "active_rag"
    assert result.safe_metadata["rag_used"] is True
    assert result.safe_metadata["exact_service_chunk_match"] is True
    assert result.safe_metadata["source_filename"] == "jet_ski_ride.md"
    assert result.safe_metadata["retrieval_service_code"] == "jet_ski_ride"
    expected_query = question.replace("pregnent", "pregnant").replace("pregnency", "pregnancy").replace("pragnant", "pregnant").casefold()
    assert knowledge.detail_calls == [(expected_query, "Jet Ski", "jet_ski_ride")]
    assert "yes, jet ski is offered at entartica raipur" not in result.draft_text.casefold()
    assert "confirm" in result.draft_text.casefold() or "assessment" in result.draft_text.casefold()
    assert not result.booking_enquiry_created and not result.human_handover_required


def test_normal_service_offer_question_uses_exact_service_overview_route():
    result, knowledge = _result("Do you offer Jet Ski?")

    assert result.detected_intent == "service_overview"
    assert result.reason_code == "approved_service_detail"
    assert "is offered at entartica raipur" not in result.draft_text.casefold()
    assert knowledge.detail_calls == [("do you offer jet ski?", "Jet Ski", "jet_ski_ride")]


def test_eligibility_validator_rejects_generic_service_confirmation():
    assert not _eligibility_response_addresses_subject(
        "Yes, Jet Ski is offered at Entartica Raipur.",
        "Can pregnant women ride Jet Ski?",
    )
    assert _eligibility_response_addresses_subject(
        "Jet Ski Ride is generally not recommended during pregnancy. Please confirm participation eligibility with Entartica staff.",
        "Can pregnant women ride Jet Ski?",
    )


def test_eligibility_route_logs_original_and_normalized_query_trace(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    question = "Can pregnent women ride jet ski?"
    _result(question)

    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "detected_intent=participation_eligibility" in output
    assert "detected_service_code=jet_ski_ride" in output
    assert "retrieved_source_file=jet_ski_ride.md" in output
    assert f"original_message={question}" in output
    assert "normalized_message=can pregnant women ride jet ski?" in output
    assert "retrieval_query=can pregnant women ride jet ski?" in output
    assert "normalized_message=eligibility_query" not in output


def test_grounded_participation_response_uses_information_category_for_automatic_reply():
    result, _ = _result("Can pregnant women ride Jet Ski?")
    settings = type("Settings", (), {
        "raipur_automatic_reply_enabled": True,
        "exotel_outbound_enabled": True,
        "raipur_approved_draft_send_enabled": True,
        "raipur_automatic_reply_intents": ("information",),
    })()
    draft = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}

    assert eligible_for_automatic_reply(settings, result, draft) == (True, "eligible")
    equivalent = type("Result", (), {
        "action": "answer_information",
        "reason_code": "approved_service_eligibility",
        "detected_intent": "health_safety_eligibility",
    })()
    assert _safe_intent(equivalent) == "information"


def test_approved_controlled_eligibility_fallback_can_be_automatically_eligible():
    settings = type("Settings", (), {
        "raipur_automatic_reply_enabled": True,
        "exotel_outbound_enabled": True,
        "raipur_approved_draft_send_enabled": True,
        "raipur_automatic_reply_intents": ("information",),
    })()
    fallback = type("Result", (), {
        "action": "answer_information",
        "reason_code": "service_eligibility_unavailable",
        "detected_intent": "participation_eligibility",
        "response_valid": True,
        "human_handover_required": False,
        "draft_text": "Participation during pregnancy depends on the applicable safety requirements and staff assessment.",
        "safe_metadata": {
            "customer_response_sanitized": True,
            "response_basis": "clarification",
            "approved_safe_fallback": True,
            "eligibility_subject_addressed": True,
        },
    })()
    draft = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}

    assert eligible_for_automatic_reply(settings, fallback, draft) == (True, "eligible")
