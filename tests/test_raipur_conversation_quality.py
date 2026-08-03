"""Fake-only quality regressions for topic memory and clarification binding."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft, RaipurConversationService
from app.services.raipur_automatic_replies import eligible_for_automatic_reply


class _Knowledge:
    def __init__(self): self.calls = 0
    def answer(self, _question):
        self.calls += 1
        return KnowledgeDraft(None)


class _Services:
    def list_active_for_location(self, _location_id): return [{"name": "Bumper Boat", "slug": "bumper-boat", "is_active": True}, {"name": "Jet Ski", "slug": "jet-ski", "is_active": True}, {"name": "Staycation Combo", "slug": "staycation-combo", "is_active": True}]
    def find_active_by_customer_text(self, _location_id, _text): return None


class _Bookings:
    def create_idempotent(self, value): return value, True


class _Availability:
    def check(self, _value): return AvailabilityResult("verification_required", safe_reason_code="availability_unverified")


class _Drafts:
    def create_outbound_draft(self, **_kwargs): return {}, False


def _service(knowledge=None):
    services = _Services()
    return RaipurConversationService(knowledge=knowledge or _Knowledge(), bookings=BookingEnquiryService(_Bookings(), _Availability(), services), drafts=_Drafts(), services=services, location={"id": "raipur", "city": "Raipur", "state": "Chhattisgarh"}, persist_drafts=False)


def _message(text):
    return NormalizedInboundMessage(external_message_id="id", customer_whatsapp_number="+910000000000", business_whatsapp_number="+911111111111", message_type="text", content=text, received_at=datetime.now(UTC))


def _process(service, text, state=None):
    return service.process(_message(text), customer={"id": "customer"}, conversation={"id": "conversation", "location_id": "raipur"}, source_message_id="id", current_state=state)


def test_current_information_follow_up_preserves_person_topic_without_entartica_switch():
    service = _service()
    first = _process(service, "Who is the Prime Minister of India?")
    second = _process(service, "Pura name btao", first.context)
    assert first.context.active_entity_type == "person" and second.reason_code == "live_verification_required"
    assert "live source" in second.draft_text.casefold() and "entartica sea world raipur hai" not in second.draft_text.casefold()


def test_raipur_city_clarification_is_bound_and_repair_keeps_city_scope():
    service = _service()
    asked = _process(service, "Raipur kaise ja skte hai")
    assert asked.context.pending_clarification and asked.context.pending_clarification_type == "destination_scope"
    city = _process(service, "Raipur city", asked.context)
    assert city.context.active_domain == "raipur_city" and not city.context.pending_clarification
    assert "flight" in city.draft_text.casefold() and "kis city" in city.draft_text.casefold()
    repaired = _process(service, "Maine Raipur city ka likha hai", city.context)
    assert repaired.reason_code == "conversation_repair" and "entartica location" in repaired.draft_text.casefold()


def test_self_introduction_h2o_and_frustration_are_specific_not_menu_responses():
    service = _service()
    intro = _process(service, "Phly apne bare me btao")
    assert intro.reason_code == "self_introduction" and "virtual assistant" in intro.draft_text.casefold() and "jet ski" not in intro.draft_text.casefold()
    h2o = _process(service, "H2O Play Park kya hai")
    assert h2o.reason_code == "service_detail_unavailable" and "detailed approved information" in h2o.draft_text.casefold()
    angry = _process(service, "Tm bewkuf ho", h2o.context)
    assert angry.reason_code == "conversation_repair" and "maaf" in angry.draft_text.casefold() and "jet ski" not in angry.draft_text.casefold()


def test_identity_questions_are_deterministic_fast_paths_and_ignore_stale_service_context():
    knowledge = _Knowledge()
    service = _service(knowledge)
    stale = ConversationContext(
        BookingDetails(None, "Jetty Gazebo", None, None, None, None, None),
        last_service_name="Jetty Gazebo",
        last_service_code="jetty_gazebo",
    )
    for question in (
        "Who are you?", "What are you?", "Introduce yourself.", "Are you a bot?",
        "Tum kaun ho?", "Aap kaun ho?", "Tumhara naam kya hai?",
    ):
        result = _process(service, question, stale)
        assert result.detected_intent == "self_introduction"
        assert result.reason_code == "self_introduction"
        assert result.safe_metadata["response_basis"] == "deterministic"
        assert result.safe_metadata["response_mode"] == "grounded_answer"
        assert result.safe_metadata["rag_called"] is False and result.safe_metadata["openai_called"] is False
        assert "entartica sea world" in result.draft_text.casefold()
        assert "jetty gazebo" not in result.draft_text.casefold()
        assert "i'm entartica sea world's virtual assistant" in result.draft_text.casefold() or "main entartica sea world ka virtual assistant" in result.draft_text.casefold()
    assert knowledge.calls == 0


def test_self_introduction_is_automatically_eligible_as_information():
    result = _process(_service(), "Who am I talking to?")
    settings = SimpleNamespace(
        raipur_automatic_reply_enabled=True,
        exotel_outbound_enabled=True,
        raipur_approved_draft_send_enabled=True,
        raipur_automatic_reply_intents=("information", "location", "services"),
    )
    draft = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}
    assert eligible_for_automatic_reply(settings, result, draft) == (True, "eligible")


def test_service_context_stays_isolated_and_response_script_is_cleaned():
    service = _service()
    bumper = _process(service, "Bumper Boat kya hai?")
    assert bumper.context.last_service_code == "bumper_boat"
    assert not any("\u0a80" <= char <= "\u0aff" for char in bumper.draft_text)
    other = _process(service, "Anything fun?")
    assert other.context.last_service_name is None


def test_pricing_booking_and_live_availability_remain_restricted():
    service = _service()
    assert _process(service, "Bumper Boat ka price kya hai?").detected_intent == "pricing"
    assert _process(service, "I want to book Bumper Boat").detected_intent == "booking"
    assert _process(service, "Kal Bumper Boat available hai?").detected_intent == "availability"
