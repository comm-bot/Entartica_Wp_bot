"""Fake-only regressions for high-priority Raipur location, capacity, and booking routes."""

from datetime import UTC, datetime

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft, RaipurConversationService


class _Knowledge:
    def __init__(self):
        self.calls = []

    def answer(self, _question):
        return KnowledgeDraft(None)

    def answer_service_details(self, question, name, code=None, **_kwargs):
        self.calls.append((question, name, code, _kwargs.get("detail_mode")))
        return KnowledgeDraft(
            "The approved Speed Boat passenger capacity is four guests. It is a multi-passenger motorboat experience.",
            "speed_boat_ride.md",
            0.8,
            False,
            "Capacity",
            1,
        )


class _Services:
    rows = (
        ("Speed Boat", "speed-boat"),
        ("Jet Ski", "jet-ski"),
        ("Staycation Combo", "staycation-combo"),
        ("Kayak", "kayak"),
    )

    def list_active_for_location(self, _location_id):
        return [{"name": name, "slug": slug, "is_active": True} for name, slug in self.rows]


class _BookingRepository:
    def __init__(self):
        self.rows = []

    def create_idempotent(self, row):
        self.rows.append(row)
        return row, True


class _Availability:
    def check(self, _request):
        return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class _Drafts:
    def create_outbound_draft(self, **_kwargs):
        return {}, False


def _service():
    knowledge = _Knowledge()
    repository = _BookingRepository()
    services = _Services()
    return (
        RaipurConversationService(
            knowledge=knowledge,
            bookings=BookingEnquiryService(repository, _Availability(), services),
            drafts=_Drafts(),
            services=services,
            location={
                "id": "raipur",
                "name": "Entartica Sea World Raipur",
                "address": "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh",
                "metadata": {
                    "location_name": "Entartica Sea World Raipur",
                    "address_line": "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh",
                    "landmark": "Near MAYFAIR Resort",
                    "maps_url": "https://maps.example/raipur",
                },
            },
        ),
        knowledge,
        repository,
    )


def _message(text):
    return NormalizedInboundMessage(
        external_message_id="routing-test",
        customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111",
        message_type="text",
        content=text,
        received_at=datetime.now(UTC),
    )


def _process(service, text, state=None):
    return service.process(
        _message(text),
        customer={"id": "customer"},
        conversation={"id": "conversation", "location_id": "raipur"},
        source_message_id="routing-test",
        current_state=state,
    )


@pytest.mark.parametrize("question", (
    "What is the capacity of speed boat?",
    "Hat is the capacity of speed baot",
    "Speed boat me kitne log beth sakte hain?",
))
def test_speed_boat_capacity_uses_exact_capacity_evidence_first(question):
    service, knowledge, repository = _service()

    result = _process(service, question)

    assert result.context.last_service_name == "Speed Boat"
    assert result.safe_metadata["question_topic"] == "capacity"
    assert result.draft_text.startswith("The approved Speed Boat passenger capacity")
    assert "booking" not in result.draft_text.casefold()
    assert knowledge.calls[0][1] == "Speed Boat" and knowledge.calls[0][3] == "capacity"
    assert repository.rows == []


@pytest.mark.parametrize("question", ("What is the location of Raipur?", "I want to know about address of Raipur"))
def test_explicit_location_beats_stale_speed_boat_context(question):
    service, knowledge, _repository = _service()
    stale = ConversationContext(
        BookingDetails(None, "Speed Boat", None, None, None, None, None),
        last_service_name="Speed Boat",
        last_service_code="speed_boat",
    )

    result = _process(service, question, stale)

    assert result.detected_intent == "location"
    assert "Sector 24" in result.draft_text
    assert "Speed Boat" not in result.draft_text
    assert result.context.pending_field is None
    assert result.context.active_entity_type == "place"
    assert knowledge.calls == []


def test_location_clears_pending_booking_state_before_it_can_reask_date():
    service, _knowledge, _repository = _service()
    pending = ConversationContext(
        BookingDetails("Mandeep", "Speed Boat", None, None, None, None, None),
        pending_field="preferred_date",
        last_service_name="Speed Boat",
        last_service_code="speed_boat",
    )

    result = _process(service, "Where is Entartica Raipur?", pending)

    assert result.detected_intent == "location"
    assert "date" not in result.draft_text.casefold()
    assert result.context.pending_field is None


@pytest.mark.parametrize(("question", "service_name"), (
    ("I want to book speed boat", "Speed Boat"),
    ("Booking karni hai", None),
    ("Can I book Jet Ski?", "Jet Ski"),
    ("Please reserve Staycation", "Staycation Combo"),
))
def test_explicit_booking_is_direct_sales_handover_without_collection(question, service_name):
    service, _knowledge, repository = _service()
    pending = ConversationContext(
        BookingDetails("Mandeep", "Speed Boat", None, None, None, None, None),
        pending_field="preferred_date",
        last_service_name="Speed Boat",
        last_service_code="speed_boat",
    )

    result = _process(service, question, pending)

    assert result.reason_code == "booking_sales_handover"
    assert result.human_handover_required and result.context.pending_field is None
    assert "+91 94296 91418" in result.draft_text and "sales@entartica.com" in result.draft_text
    if service_name:
        assert service_name in result.draft_text
    assert not any(word in result.draft_text.casefold() for word in ("share your name", "what date", "what time", "how many guests"))
    assert repository.rows == []
