"""Engine-selection regression guards for the production orchestrator."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.raipur.response_models import ConversationResult
import app.services.raipur_inbound_orchestrator as module


class _Locations:
    def __init__(self, _client):
        pass

    def get_location_by_code(self, _code):
        return {"id": "raipur"}


class _Contexts:
    def __init__(self, _client):
        self.saved = []

    def get_service_context(self, *_args):
        return None

    def save_service_context(self, *_args):
        self.saved.append(_args)


def _result() -> ConversationResult:
    return ConversationResult(
        action="answer_information", draft_text="Safe reply.",
        reason_code="deterministic", detected_intent="greeting",
        detected_location="raipur", response_language="en",
        human_handover_required=False, safe_metadata={},
    )


def _build(monkeypatch, *, enabled: bool):
    monkeypatch.setattr(module, "LocationRepository", _Locations)
    monkeypatch.setattr(module, "ConversationRepository", _Contexts)
    monkeypatch.setattr(module, "ServiceRepository", lambda _client: object())
    monkeypatch.setattr(module, "BookingEnquiryRepository", lambda _client: object())
    monkeypatch.setattr(module, "BookingEnquiryService", lambda *_args: object())
    monkeypatch.setattr(module, "build_raipur_availability_provider", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(module, "build_raipur_conversational_fallback", lambda _settings: None)
    monkeypatch.setattr(module, "format_whatsapp_response", lambda **kwargs: kwargs["text"])
    calls = {"legacy": 0, "graph": 0}

    class _Legacy:
        def __init__(self, **_kwargs):
            pass

        def process(self, *_args, **_kwargs):
            calls["legacy"] += 1
            return _result()

    class _Graph:
        def __init__(self, *_args, **_kwargs):
            pass

        def invoke(self, *_args, **_kwargs):
            calls["graph"] += 1
            return _result()

    monkeypatch.setattr(module, "RaipurConversationService", _Legacy)
    monkeypatch.setattr(module, "RaipurLangGraphWorkflow", _Graph)
    settings = SimpleNamespace(
        app_timezone="Asia/Kolkata",
        raipur_langgraph_enabled=enabled,
        router_revision="test",
        raipur_conversation_context_ttl_minutes=120,
        conversation_session_ttl_minutes=30,
        entartica_sales_phone="+919429691418",
        entartica_sales_email="sales@entartica.com",
    )
    return module.RaipurInboundOrchestrator(object(), settings), calls


def _message():
    return NormalizedInboundMessage(
        external_message_id="test-message",
        customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111",
        message_type="text",
        content="hii",
        received_at=datetime.now(timezone.utc),
    )


def test_langgraph_mode_never_invokes_legacy_process(monkeypatch):
    orchestrator, calls = _build(monkeypatch, enabled=True)

    orchestrator.process(
        _message(), customer={"id": "customer"}, conversation={"id": "conversation"},
        source_message_id="test-message",
    )

    assert calls == {"legacy": 0, "graph": 1}


def test_explicit_false_retains_single_legacy_compatibility_path(monkeypatch):
    orchestrator, calls = _build(monkeypatch, enabled=False)

    orchestrator.process(
        _message(), customer={"id": "customer"}, conversation={"id": "conversation"},
        source_message_id="test-message",
    )

    assert calls == {"legacy": 1, "graph": 0}
