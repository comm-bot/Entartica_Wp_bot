"""Fake-only coverage for durable, safe Raipur service follow-up context."""

from datetime import UTC, datetime, timedelta

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService
from app.services.raipur_inbound_orchestrator import _context_from_record, _context_to_record


class _Knowledge:
    def __init__(self, details: bool = False) -> None:
        self.details = details
        self.calls = 0

    def answer(self, _: str) -> KnowledgeDraft:
        self.calls += 1
        return KnowledgeDraft(None)

    def answer_service_details(self, _question: str, name: str) -> KnowledgeDraft:
        self.calls += 1
        return KnowledgeDraft(f"{name} approved detail", "approved.docx", 0.8, not self.details)


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"name": "Floating Gazebo", "slug": "floating-gazebo", "is_active": True}, {"name": "Jet Ski", "slug": "jet-ski", "is_active": True}]


class _Bookings:
    def create_idempotent(self, record): return record, True


class _Availability:
    def check(self, _): return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class _Drafts:
    def create_outbound_draft(self, **_): return {}, False


def _service(details: bool = False):
    knowledge = _Knowledge(details)
    return RaipurConversationService(
        knowledge=knowledge,
        bookings=BookingEnquiryService(_Bookings(), _Availability(), _Services()),
        drafts=_Drafts(), services=_Services(), location={"id": "raipur"},
    ), knowledge


def _message(text: str) -> NormalizedInboundMessage:
    return NormalizedInboundMessage(
        external_message_id="id", customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111", message_type="text",
        content=text, received_at=datetime.now(UTC),
    )


def _process(service, text, state=None):
    return service.process(_message(text), customer={"id": "customer"}, conversation={"id": "conversation", "location_id": "raipur"}, source_message_id="id", current_state=state)


def test_detail_followups_use_active_service_context_in_english_and_hinglish():
    service, knowledge = _service(details=False)
    selected = _process(service, "Floating Gazebo")
    english = _process(service, "Tell me more", selected.context)
    hinglish = _process(service, "Iske baare mein batao", selected.context)

    assert english.reason_code == "service_detail_unavailable"
    assert hinglish.reason_code == "service_detail_unavailable"
    assert "Floating Gazebo" in english.draft_text and "team assistance" in english.draft_text
    assert "Floating Gazebo" in hinglish.draft_text and "team assistance" in hinglish.draft_text
    # The standalone active celebration selection is now a grounded detail
    # route, followed by the two context-preserving detail follow-ups.
    assert knowledge.calls == 3


def test_context_resolves_price_and_availability_without_inventing_a_result():
    service, _ = _service()
    selected = _process(service, "Jet Ski")
    price = _process(service, "Price kya hai", selected.context)
    availability = _process(service, "Kal available hai?", selected.context)

    assert price.human_handover_required and "price" not in price.draft_text.casefold()
    assert availability.human_handover_required
    assert "currently appears available" not in availability.draft_text.casefold()


def test_explicit_service_replaces_context_and_missing_context_clarifies():
    service, _ = _service()
    first = _process(service, "Floating Gazebo")
    switched = _process(service, "What about Jet Ski?", first.context)
    missing = _process(service, "Tell me more")

    assert switched.context.last_service_name == "Jet Ski"
    assert missing.reason_code == "clarification_required"


def test_serialized_context_is_structured_and_expired_context_is_not_used():
    service, _ = _service()
    selected = _process(service, "Jet Ski")
    record = _context_to_record(selected.context)
    active, expired = _context_from_record(record, 120)
    record["updated_at"] = (datetime.now(UTC) - timedelta(minutes=121)).isoformat()
    stale, stale_expired = _context_from_record(record, 120)

    assert active.last_service_name == "Jet Ski" and not expired
    assert stale is None and stale_expired
    assert "content" not in record and "answer" not in record
