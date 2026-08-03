"""Fake-only sales-contact routing regressions."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft, RaipurConversationService
from app.services.raipur_sales_contact import SalesContact


class Knowledge:
    def __init__(self, grounded: bool = False) -> None:
        self.grounded = grounded

    def answer(self, _question):
        return KnowledgeDraft("Jet Ski Ride is self-driven.", "jet_ski_ride.md", .8, False) if self.grounded else KnowledgeDraft(None)

    def answer_service_details(self, _question, _service_name, _service_code=None):
        return self.answer(_question)


class Services:
    def list_active_for_location(self, _location_id):
        return [{"name": "Jet Ski", "slug": "jet-ski", "is_active": True}]


class Repository:
    def create_idempotent(self, record):
        return record, True


class Availability:
    def check(self, _request):
        return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class Drafts:
    def create_outbound_draft(self, **_kwargs):
        return {}, False


CONTACT = SalesContact("+919429691418", "sales@entartica.com")


def service(*, grounded: bool = False):
    services = Services()
    return RaipurConversationService(
        knowledge=Knowledge(grounded),
        bookings=BookingEnquiryService(Repository(), Availability(), services),
        drafts=Drafts(),
        services=services,
        location={"id": "raipur"},
        persist_drafts=False,
        sales_contact=CONTACT,
    )


def process(question: str, *, grounded: bool = False, state=None):
    result = service(grounded=grounded).process(
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
        current_state=state,
    )
    return result


def assert_contact(text: str):
    assert "+91 94296 91418" in text
    assert "sales@entartica.com" in text
    assert "+919429691418" not in text


def test_contact_is_read_from_configuration_and_safely_formatted():
    configured = SalesContact.from_settings(SimpleNamespace(entartica_sales_phone="+919429691418", entartica_sales_email="sales@entartica.com"))
    assert configured.display_phone == "+91 94296 91418"
    assert configured.details() == "📞 Call: +91 94296 91418\n✉️ Email: sales@entartica.com"


def test_unknown_question_escalates_to_approved_contact_fallback_after_one_clarification():
    first = process("Explain underwater music rules")
    second = process("I still need the answer", state=first.context)
    assert first.safe_metadata["response_mode"] == "clarification_question"
    assert second.safe_metadata["response_mode"] == "approved_safe_fallback"
    assert_contact(second.draft_text)


def test_direct_human_requests_pricing_booking_and_complaints_include_controlled_contact_handover():
    for question in ("Connect me to sales", "What is the Jet Ski price?", "I want to confirm booking", "I have a complaint"):
        result = process(question)
        assert result.human_handover_required
        assert_contact(result.draft_text)
        assert result.draft_text != "Yes, Jet Ski is offered at Entartica Raipur."


def test_hinglish_human_request_uses_hinglish_contact_response():
    result = process("Mujhe sales team se baat karni hai")
    assert "contact karne ke liye" in result.draft_text
    assert_contact(result.draft_text)


def test_grounded_rag_answer_does_not_immediately_handover():
    result = process("Can I drive Jet Ski myself?", grounded=True)
    assert result.safe_metadata["response_basis"] == "active_rag"
    assert not result.human_handover_required
    assert "sales@entartica.com" not in result.draft_text


def test_direct_contact_requests_override_service_and_booking_context_without_collecting_customer_details():
    stale_jetty_context = ConversationContext(
        BookingDetails("Customer", "Jetty Gazebo", None, None, None, None, None),
        pending_field="preferred_date",
        last_service_name="Jetty Gazebo",
        last_service_code="jetty_gazebo",
        pending_question_type="yes_no",
        pending_action="provide_service_details",
        pending_service_code="jetty_gazebo",
    )
    for question in (
        "Number send kro",
        "Team ka nmbr do",
        "Sales team ka number do",
        "Contact details bhejo",
        "I want to speak with a person",
        "Jetty Gazebo team ka number do",
    ):
        result = process(question, state=stale_jetty_context)
        assert result.detected_intent == "human_contact_request"
        assert result.safe_metadata["response_mode"] == "direct_contact_details"
        assert_contact(result.draft_text)
        assert result.draft_text.count("+91 94296 91418") == 1
        assert result.draft_text.count("sales@entartica.com") == 1
        assert "jetty gazebo" not in result.draft_text.casefold()
        assert "available nahi" not in result.draft_text.casefold()
        assert "share your own number" not in result.draft_text.casefold()
        assert result.next_required_field is None
        assert result.context.pending_field is None


def test_explicit_booking_uses_sales_handover_instead_of_collecting_details():
    result = process("I want to book Jet Ski")
    assert result.action == "general_human_handover"
    assert result.detected_intent == "booking"
    assert result.next_required_field is None
    assert result.safe_metadata["response_mode"] == "human_handover"
