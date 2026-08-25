from datetime import date, datetime, time, timezone
from types import SimpleNamespace

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.booking_enquiries import BookingDetails
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
import app.services.raipur_inbound_orchestrator as module


class _Locations:
    def __init__(self, client): pass
    def get_location_by_code(self, code): return {"id": "raipur"}


class _Provider:
    def __init__(self, draft=None, error=None): self.draft, self.error, self.calls = draft, error, 0
    def answer(self, question):
        self.calls += 1
        if self.error: raise self.error
        return self.draft


def _orchestrator(monkeypatch, provider=None):
    monkeypatch.setattr(module, "LocationRepository", _Locations)
    monkeypatch.setattr(module, "ServiceRepository", lambda client: object())
    monkeypatch.setattr(module, "BookingEnquiryRepository", lambda client: object())
    monkeypatch.setattr(module, "BookingEnquiryService", lambda *args: object())
    monkeypatch.setattr(module, "build_raipur_availability_provider", lambda settings, client: object())
    return module.RaipurInboundOrchestrator(object(), SimpleNamespace(app_timezone="Asia/Kolkata"), knowledge_provider=provider)


def _message(content="Where is the Raipur location?"):
    return NormalizedInboundMessage(external_message_id="marker", customer_whatsapp_number="+910000000000", business_whatsapp_number="+911111111111", message_type="text", content=content, received_at=datetime.now(timezone.utc))


def test_injected_provider_produces_grounded_valid_conversation_result(monkeypatch):
    provider = _Provider(KnowledgeDraft("Approved activities are available at Raipur.", "source.docx", 0.8, False))
    result = _orchestrator(monkeypatch, provider).process(_message("What activities are available?"), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="marker")
    assert provider.calls == 1 and result.draft_text and result.response_valid
    assert result.template_key == "information" and not result.human_handover_required


def test_low_confidence_uses_safe_clarification_and_default_remains_safe(monkeypatch):
    provider = _Provider(KnowledgeDraft(None, None, None, True))
    result = _orchestrator(monkeypatch, provider).process(_message("What activities are available?"), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="marker")
    assert provider.calls == 1 and not result.human_handover_required and result.response_valid
    assert result.reason_code in {"safe_conversational_fallback", "clarification_required"}
    default = _orchestrator(monkeypatch)
    assert isinstance(default._conversation._knowledge, module._SafeKnowledge)


def test_provider_exception_has_no_send_path(monkeypatch):
    provider = _Provider(error=RuntimeError("private provider error"))
    orchestrator = _orchestrator(monkeypatch, provider)
    with pytest.raises(RuntimeError, match="private provider error"):
        orchestrator.process(_message("What activities are available?"), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="marker")
    assert provider.calls == 1


def test_location_pending_action_entity_binding_round_trips_through_context_storage():
    context = ConversationContext(
        details=BookingDetails(None, None, None, None, None, None, None, special_requirements_collected=False),
        pending_question_type="yes_no",
        pending_action="send_location_map_link",
        pending_entity_type="place",
        pending_entity_name="Entartica Sea World Raipur",
        pending_created_at="2026-07-28T10:00:00+00:00",
    )

    stored = module._context_to_record(context)
    restored, expired = module._context_from_record(stored, 120)

    assert not expired
    assert restored.pending_action == "send_location_map_link"
    assert restored.pending_entity_type == "place"
    assert restored.pending_entity_name == "Entartica Sea World Raipur"
    assert restored.pending_created_at == "2026-07-28T10:00:00+00:00"


def test_booking_context_round_trip_preserves_every_collected_field():
    context = ConversationContext(
        details=BookingDetails(
            "Mandeep", "Jet Ski Ride", date(2026, 8, 1), time(16, 0), 1, 1, 2,
            special_requirements="life jacket requested", special_requirements_collected=True,
            requested_service_id="service-id",
        ),
        pending_field="special_requirements",
        availability_requested=True,
        last_service_name="Jet Ski Ride",
        last_service_code="jet_ski_ride",
        service_details_requested=True,
        pending_action="verify_live_availability",
        pending_slots={"date": "2026-08-01", "time": "16:00"},
    )

    restored, expired = module._context_from_record(module._context_to_record(context), 120)

    assert not expired
    assert restored.pending_field == "special_requirements"
    assert restored.availability_requested and restored.service_details_requested
    assert restored.last_service_code == "jet_ski_ride"
    assert restored.details == context.details
    assert restored.pending_action == "verify_live_availability"
    assert restored.pending_slots == {"date": "2026-08-01", "time": "16:00"}


def test_older_service_only_context_remains_compatible():
    record = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "service_name": "Jet Ski Ride",
        "service_code": "jet_ski_ride",
        "active_domain": "entartica",
    }

    restored, expired = module._context_from_record(record, 120)

    assert not expired
    assert restored.last_service_code == "jet_ski_ride"
    assert restored.details.requested_service_text == "Jet Ski Ride"
    assert restored.pending_field is None


def test_exact_service_detail_does_not_compose_an_already_sanitized_provider_answer(monkeypatch):
    provider = _Provider(KnowledgeDraft("Jet Ski capacity supports two guests.", "jet_ski_ride.md", 0.8, False))
    provider.answer_service_details = lambda *_args, **_kwargs: provider.draft
    orchestrator = _orchestrator(monkeypatch, provider)
    compose_calls: list[str] = []
    import app.services.raipur_conversation as conversation_module
    monkeypatch.setattr(conversation_module, "compose_customer_response", lambda text, **_kwargs: compose_calls.append(text) or text)

    result = orchestrator._conversation._service_detail("How many people can ride?", "Jet Ski Ride")

    assert result is provider.draft
    assert compose_calls == []
