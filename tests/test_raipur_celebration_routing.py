"""Fake-only deterministic routing for safe Raipur celebration list questions."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_automatic_replies import eligible_for_automatic_reply
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService


class _Knowledge:
    def __init__(self): self.calls = 0
    def answer(self, _): self.calls += 1; return KnowledgeDraft(None)
    def answer_service_details(self, _question, service_name):
        self.calls += 1
        if service_name == "Party Boat Celebration":
            return KnowledgeDraft("Party Boat Celebration is at Entartica Sea World, Raipur, on Jhanjh Lake. The approved duration is 2 hours and it can accommodate up to 50 guests.", "party_boat_celebration.md", .8, False)
        return KnowledgeDraft(None)


class _Services:
    def list_active_for_location(self, _):
        return [{"name": name, "slug": slug, "is_active": True} for name, slug in (
            ("Party Boat Celebration", "party-boat-celebration"), ("Pontoon Celebration", "pontoon-celebration"),
            ("Floating Gazebo", "floating-gazebo"), ("Jetty Gazebo", "jetty-gazebo"),
            ("Houseboat Celebration", "houseboat-celebration"), ("Jet Ski", "jet-ski"),
        )]


class _Bookings:
    def create_idempotent(self, row): return row, True


class _Availability:
    def check(self, _): return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class _Drafts:
    def create_outbound_draft(self, **_): return {}, False


def _service():
    knowledge = _Knowledge(); services = _Services()
    return RaipurConversationService(knowledge=knowledge, bookings=BookingEnquiryService(_Bookings(), _Availability(), services), drafts=_Drafts(), services=services, location={"id": "raipur"}), knowledge


def _message(text):
    return NormalizedInboundMessage(external_message_id="id", customer_whatsapp_number="+910000000000", business_whatsapp_number="+911111111111", message_type="text", content=text, received_at=datetime.now(UTC))


def _result(question):
    service, knowledge = _service()
    result = service.process(_message(question), customer={"id":"customer"}, conversation={"id":"conversation", "location_id":"raipur"}, source_message_id="id")
    return result, knowledge


@pytest.mark.parametrize("question", ["What celebration options are available in Raipur?", "Raipur mein celebration options kya hain?", "रायपुर में सेलिब्रेशन विकल्प क्या हैं?"])
def test_celebration_list_is_deterministic_and_never_uses_low_confidence_rag(question):
    result, knowledge = _result(question)
    assert result.detected_intent == "celebration_service_list"
    assert result.reason_code == "structured_celebration_service_list"
    assert result.human_handover_required is False and knowledge.calls == 0
    assert result.context.service_selection_prompted is True
    for name in ("Party Boat Celebration", "Pontoon Celebration", "Floating Gazebo", "Jetty Gazebo", "Houseboat Celebration"):
        assert name in result.draft_text
    assert all(term not in result.draft_text.casefold() for term in ("price", "booking is confirmed", "available now"))


def test_celebration_list_maps_to_services_and_pricing_uses_controlled_handover():
    result, _ = _result("Which celebration services do you offer?")
    settings = SimpleNamespace(exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True, raipur_automatic_reply_enabled=True, raipur_automatic_reply_intents=("information", "location", "services"))
    draft = {"id":"draft", "draft_status":"pending_review", "sent_at":None, "external_message_id":None}
    assert eligible_for_automatic_reply(settings, result, draft) == (True, "eligible")
    service, _ = _service()
    price = service.process(_message("Price kya hai?"), customer={"id":"customer"}, conversation={"id":"conversation", "location_id":"raipur"}, source_message_id="id", current_state=result.context)
    assert price.human_handover_required
    assert price.safe_metadata["response_mode"] == "human_handover"
    assert eligible_for_automatic_reply(settings, price, draft) == (True, "eligible")


@pytest.mark.parametrize("follow_up", ["Can you tell more about it", "Iske baare mein aur batao", "इसके बारे में और बताइए।"])
def test_houseboat_context_followup_is_information_eligible_without_inventing_details(follow_up):
    service, _ = _service()
    customer = {"id":"customer"}; conversation = {"id":"conversation", "location_id":"raipur"}
    selected = service.process(_message("Houseboat Celebration"), customer=customer, conversation=conversation, source_message_id="one")
    result = service.process(_message(follow_up), customer=customer, conversation=conversation, source_message_id="two", current_state=selected.context)
    settings = SimpleNamespace(exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True, raipur_automatic_reply_enabled=True, raipur_automatic_reply_intents=("information", "location", "services"))
    draft = {"id":"draft", "draft_status":"pending_review", "sent_at":None, "external_message_id":None}

    assert selected.context.last_service_code == "houseboat_celebration"
    assert selected.context.service_selection_prompted is False
    assert result.detected_intent in {"celebration_service_detail", "service_more_details"}
    assert result.human_handover_required is False
    assert eligible_for_automatic_reply(settings, result, draft) == (True, "eligible")
    assert "Houseboat Celebration" in result.draft_text
    assert all(term not in result.draft_text.casefold() for term in ("booking is confirmed", "payment link", "available tomorrow"))


def test_selection_after_celebration_list_immediately_returns_detail_not_confirmation():
    service, _ = _service(); customer = {"id":"customer"}; conversation = {"id":"conversation", "location_id":"raipur"}
    listed = service.process(_message("What celebration options are available in Raipur?"), customer=customer, conversation=conversation, source_message_id="one")
    selected = service.process(_message("Houseboat Celebration"), customer=customer, conversation=conversation, source_message_id="two", current_state=listed.context)

    assert listed.context.service_selection_prompted is True
    assert selected.detected_intent == "celebration_service_detail"
    assert selected.context.service_selection_prompted is False
    assert selected.context.last_service_code == "houseboat_celebration"
    assert "Yes, Houseboat Celebration is offered" not in selected.draft_text
    assert "Houseboat Celebration" in selected.draft_text


def test_party_boat_switch_returns_active_detail_and_replaces_houseboat_context():
    service, _ = _service(); customer = {"id":"customer"}; conversation = {"id":"conversation", "location_id":"raipur"}
    houseboat = service.process(_message("Houseboat Celebration"), customer=customer, conversation=conversation, source_message_id="one")
    party = service.process(_message("Party Boat Celebration"), customer=customer, conversation=conversation, source_message_id="two", current_state=houseboat.context)
    follow_up = service.process(_message("Can you tell em more about it"), customer=customer, conversation=conversation, source_message_id="three", current_state=party.context)

    assert party.detected_intent == "celebration_service_detail"
    assert party.context.last_service_code == "party_boat_celebration"
    assert party.context.service_selection_prompted is False
    assert all(fact in party.draft_text for fact in ("Jhanjh Lake", "2 hours", "50 guests"))
    assert "Yes, Party Boat Celebration is offered" not in party.draft_text
    assert "Party Boat Celebration" in follow_up.draft_text
    assert all(term not in party.draft_text.casefold() for term in ("price", "availability", "booking is confirmed"))


def test_explicit_party_boat_offer_question_uses_exact_service_overview():
    result, _ = _result("Do you offer Party Boat Celebration?")
    assert result.detected_intent == "service_overview"
    assert result.reason_code == "approved_service_detail"
    assert "is offered at entartica raipur" not in result.draft_text.casefold()
