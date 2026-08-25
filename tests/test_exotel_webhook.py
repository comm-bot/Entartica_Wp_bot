"""Tests for the promptly acknowledged, background-only inbound webhook."""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.background import BackgroundTasks
from starlette.requests import Request

from app.api import exotel_webhook
from app.main import app
from app.services.inbound_messages import InboundMessageResult


class SuccessfulService:
    """A mocked persistence service with no external calls."""

    def process(self, message):
        return InboundMessageResult(duplicate=False)


class FailingService:
    """A mocked persistence service that fails safely."""

    def process(self, message):
        raise RuntimeError("database unavailable")


class DuplicateService:
    """A mocked persistence service reporting an already stored message."""

    def process(self, message):
        return InboundMessageResult(duplicate=True)


def _settings(*, signatures_enabled: bool = False):
    return SimpleNamespace(
        exotel_account_sid="account-1",
        exotel_api_token=SecretStr("test-token"),
        exotel_signature_validation_enabled=signatures_enabled,
        raipur_inbound_orchestrator_enabled=False,
        raipur_draft_creation_enabled=False,
        raipur_automatic_reply_enabled=False,
        exotel_outbound_enabled=False,
        raipur_approved_draft_send_enabled=False,
    )


def _payload() -> dict:
    return {
        "whatsapp": {
            "messages": [
                {
                    "callback_type": "incoming_message",
                    "sid": "message-1",
                    "from": "+919000000000",
                    "to": "+919000000001",
                    "timestamp": "2022-10-19T21:48:31+05:30",
                    "content": {"type": "text", "text": {"body": "Hello"}},
                }
            ]
        }
    }


def test_webhook_acknowledges_valid_payload(monkeypatch) -> None:
    """A valid mocked payload is acknowledged while persistence runs later."""

    monkeypatch.setattr(exotel_webhook, "get_settings", lambda: _settings())
    monkeypatch.setattr(exotel_webhook, "get_inbound_message_service", SuccessfulService)

    response = TestClient(app).post("/webhooks/exotel/inbound", json=_payload())

    assert response.status_code == 200
    assert response.content == b""


def test_webhook_rejects_invalid_json(monkeypatch) -> None:
    """Malformed JSON receives a safe client error."""

    monkeypatch.setattr(exotel_webhook, "get_settings", lambda: _settings())

    response = TestClient(app).post(
        "/webhooks/exotel/inbound", content=b"{", headers={"content-type": "application/json"}
    )

    assert response.status_code == 400


def test_webhook_accepts_valid_signature(monkeypatch) -> None:
    """Enabled HMAC validation accepts the matching raw-body signature."""

    monkeypatch.setattr(
        exotel_webhook, "get_settings", lambda: _settings(signatures_enabled=True)
    )
    monkeypatch.setattr(exotel_webhook, "get_inbound_message_service", SuccessfulService)
    body = b'{"whatsapp":{"messages":[{"callback_type":"incoming_message","sid":"message-1","from":"+919000000000","to":"+919000000001","timestamp":"2022-10-19T21:48:31+05:30","content":{"type":"text","text":{"body":"Hello"}}}]}}'
    signature = hmac.new(b"test-token", body, hashlib.sha256).hexdigest()

    response = TestClient(app).post(
        "/webhooks/exotel/inbound",
        content=body,
        headers={"content-type": "application/json", "X-Exotel-Signature": signature},
    )

    assert response.status_code == 200


def test_webhook_rejects_invalid_signature(monkeypatch) -> None:
    """Enabled signature validation fails closed for invalid values."""

    monkeypatch.setattr(
        exotel_webhook, "get_settings", lambda: _settings(signatures_enabled=True)
    )

    response = TestClient(app).post(
        "/webhooks/exotel/inbound", json=_payload(), headers={"X-Exotel-Signature": "invalid"}
    )

    assert response.status_code == 401


def test_webhook_background_persistence_failure_still_acknowledges(monkeypatch) -> None:
    """Later storage failures never change Exotel's already-safe acknowledgement."""

    monkeypatch.setattr(exotel_webhook, "get_settings", lambda: _settings())
    monkeypatch.setattr(exotel_webhook, "get_inbound_message_service", FailingService)

    response = TestClient(app).post("/webhooks/exotel/inbound", json=_payload())

    assert response.status_code == 200
    assert "Hello" not in response.text
    assert "database unavailable" not in response.text


def test_webhook_acknowledges_duplicate_message(monkeypatch) -> None:
    """An already-stored provider message still receives a 200 acknowledgment."""

    monkeypatch.setattr(exotel_webhook, "get_settings", lambda: _settings())
    monkeypatch.setattr(exotel_webhook, "get_inbound_message_service", DuplicateService)

    response = TestClient(app).post("/webhooks/exotel/inbound", json=_payload())

    assert response.status_code == 200


def test_webhook_ignores_unsupported_callback_type(monkeypatch) -> None:
    """Non-incoming callbacks are acknowledged without persistence."""

    payload = _payload()
    payload["whatsapp"]["messages"][0]["callback_type"] = "delivery_status"
    monkeypatch.setattr(exotel_webhook, "get_settings", lambda: _settings())

    response = TestClient(app).post("/webhooks/exotel/inbound", json=payload)

    assert response.status_code == 200


def test_valid_request_schedules_slow_processing_without_awaiting_it(monkeypatch) -> None:
    """The route returns before a potentially slow background task starts."""

    scheduled: list[object] = []

    async def slow_background(*_args):
        scheduled.append("started")

    monkeypatch.setattr(exotel_webhook, "get_settings", lambda: _settings())
    monkeypatch.setattr(exotel_webhook, "process_inbound_messages_background", slow_background)
    body = json.dumps(_payload()).encode()
    called = False

    async def receive():
        nonlocal called
        if called:
            return {"type": "http.disconnect"}
        called = True
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/webhooks/exotel/inbound", "headers": []}, receive)
    tasks = BackgroundTasks()
    response = asyncio.run(exotel_webhook.receive_inbound_message(request, tasks))

    assert response.status_code == 200
    assert len(tasks.tasks) == 1
    assert scheduled == []


def test_duplicate_background_processing_skips_orchestration(monkeypatch) -> None:
    class Service:
        def __init__(self): self.calls = 0
        def process(self, _message):
            self.calls += 1
            return InboundMessageResult(self.calls > 1, {"id": "customer"}, {"id": "conversation"}, {"id": "inbound"})

    class Orchestrator:
        def __init__(self): self.calls = 0
        def process(self, *_args, **_kwargs): self.calls += 1; return SimpleNamespace(action="answer_information", reason_code="approved_knowledge")

    service, orchestrator = Service(), Orchestrator()
    configured = _settings(); configured.raipur_inbound_orchestrator_enabled = True
    monkeypatch.setattr(exotel_webhook, "get_inbound_message_service", lambda: service)
    monkeypatch.setattr(exotel_webhook, "get_raipur_inbound_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(exotel_webhook, "get_supabase_client", lambda: object())
    monkeypatch.setattr(exotel_webhook, "OutboundDraftRepository", lambda _client: object())
    monkeypatch.setattr(exotel_webhook, "create_draft_after_orchestration", lambda **_kwargs: SimpleNamespace(draft_saved=False, reason_code="disabled"))
    message = exotel_webhook.normalize_exotel_payload(_payload())[0]

    asyncio.run(exotel_webhook.process_inbound_messages_background([message], configured))
    asyncio.run(exotel_webhook.process_inbound_messages_background([message], configured))

    assert service.calls == 2 and orchestrator.calls == 1


def test_orchestrator_dependency_graph_is_constructed_once(monkeypatch) -> None:
    calls = []
    client, settings = object(), object()
    class Knowledge:
        def __init__(self, received_client, received_settings):
            assert (received_client, received_settings) == (client, settings)
    class Orchestrator:
        def __init__(self, received_client, received_settings, knowledge_provider=None):
            calls.append("constructed")
            assert received_client is client and received_settings is settings and isinstance(knowledge_provider, Knowledge)
    from app.rag import raipur_knowledge_provider
    monkeypatch.setattr(exotel_webhook, "get_supabase_client", lambda: client)
    monkeypatch.setattr(exotel_webhook, "get_settings", lambda: settings)
    monkeypatch.setattr(exotel_webhook, "RaipurInboundOrchestrator", Orchestrator)
    monkeypatch.setattr(raipur_knowledge_provider, "RaipurKnowledgeProvider", Knowledge)
    exotel_webhook.get_raipur_inbound_orchestrator.cache_clear()
    first = exotel_webhook.get_raipur_inbound_orchestrator()
    second = exotel_webhook.get_raipur_inbound_orchestrator()
    assert first is second and calls == ["constructed"]
    exotel_webhook.get_raipur_inbound_orchestrator.cache_clear()


def test_rapid_same_customer_messages_remain_serialized(monkeypatch) -> None:
    state = {"active": 0, "maximum": 0, "order": []}
    class Service:
        def process(self, message):
            state["active"] += 1; state["maximum"] = max(state["maximum"], state["active"])
            state["order"].append(message.external_message_id); time.sleep(0.02); state["active"] -= 1
            return InboundMessageResult(False, {"id": "customer"}, {"id": "conversation"}, {"id": message.external_message_id})
    configured = _settings()
    monkeypatch.setattr(exotel_webhook, "get_inbound_message_service", Service)
    first = exotel_webhook.normalize_exotel_payload(_payload())[0]
    second_payload = _payload(); second_payload["whatsapp"]["messages"][0]["sid"] = "message-2"
    second = exotel_webhook.normalize_exotel_payload(second_payload)[0]
    async def run():
        await asyncio.gather(
            exotel_webhook.process_inbound_messages_background([first], configured),
            exotel_webhook.process_inbound_messages_background([second], configured),
        )
    asyncio.run(run())
    assert state["maximum"] == 1 and state["order"] == ["message-1", "message-2"]


def test_background_automatic_reply_uses_existing_sender_only_when_enabled(monkeypatch) -> None:
    class Service:
        def process(self, _message): return InboundMessageResult(False, {"id": "customer"}, {"id": "conversation"}, {"id": "inbound"})

    orchestration = SimpleNamespace(
        action="answer_information", reason_code="approved_knowledge", response_valid=True,
        human_handover_required=False, draft_text="Grounded fact.", detected_intent="location",
            safe_metadata={"source_filename": "safe.docx", "customer_response_sanitized": True, "response_basis": "active_rag"},
    )

    class Orchestrator:
        def process(self, *_args, **_kwargs): return orchestration

    class Repository:
        def __init__(self): self.row = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}
        def find_draft_for_inbound_message(self, _inbound_id): return self.row
        def approve_draft(self, _draft_id): self.row["draft_status"] = "approved"; return True

    class Sender:
        def __init__(self): self.calls = 0
        async def send(self, *_args, **_kwargs): self.calls += 1; return SimpleNamespace(attempted=True, reason="completed")

    repository, sender = Repository(), Sender()
    configured = _settings(); configured.raipur_inbound_orchestrator_enabled = True; configured.raipur_draft_creation_enabled = True
    configured.raipur_automatic_reply_enabled = True; configured.exotel_outbound_enabled = True; configured.raipur_approved_draft_send_enabled = True
    configured.raipur_automatic_reply_intents = ("location",)
    monkeypatch.setattr(exotel_webhook, "get_inbound_message_service", Service)
    monkeypatch.setattr(exotel_webhook, "get_raipur_inbound_orchestrator", Orchestrator)
    monkeypatch.setattr(exotel_webhook, "get_supabase_client", lambda: object())
    monkeypatch.setattr(exotel_webhook, "OutboundDraftRepository", lambda _client: repository)
    monkeypatch.setattr(exotel_webhook, "create_draft_after_orchestration", lambda **_kwargs: SimpleNamespace(draft_saved=True, reason_code="draft_created"))
    monkeypatch.setattr(exotel_webhook, "get_raipur_draft_sender", lambda _repository, _settings: sender)
    message = exotel_webhook.normalize_exotel_payload(_payload())[0]

    asyncio.run(exotel_webhook.process_inbound_messages_background([message], configured))
    assert sender.calls == 1

    configured.raipur_automatic_reply_enabled = False
    repository.row.update(draft_status="pending_review", sent_at=None, external_message_id=None)
    asyncio.run(exotel_webhook.process_inbound_messages_background([message], configured))
    assert sender.calls == 1


def test_actual_background_path_emits_safe_raipur_runtime_trace(monkeypatch, caplog) -> None:
    class Service:
        def process(self, _message): return InboundMessageResult(False, {"id": "customer"}, {"id": "conversation"}, {"id": "inbound"})
    orchestration = SimpleNamespace(
        action="answer_information", reason_code="approved_service_detail", response_valid=True,
        human_handover_required=False, draft_text="Approved Jet Ski overview.", detected_intent="service_overview",
        safe_metadata={"graph_answer_source": "answer_service_knowledge", "service_code": "jet_ski_ride", "topic": "overview", "answer_source": "provider_composition", "response_basis": "active_rag"},
    )
    class Orchestrator:
        def process(self, *_args, **_kwargs): return orchestration
    configured = _settings(); configured.raipur_inbound_orchestrator_enabled = True
    monkeypatch.setattr(exotel_webhook, "get_inbound_message_service", Service)
    monkeypatch.setattr(exotel_webhook, "get_raipur_inbound_orchestrator", Orchestrator)
    monkeypatch.setattr(exotel_webhook, "get_supabase_client", lambda: object())
    monkeypatch.setattr(exotel_webhook, "OutboundDraftRepository", lambda _client: object())
    monkeypatch.setattr(exotel_webhook, "create_draft_after_orchestration", lambda **_kwargs: SimpleNamespace(draft_saved=False, reason_code="draft_created"))
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        asyncio.run(exotel_webhook.process_inbound_messages_background([exotel_webhook.normalize_exotel_payload(_payload())[0]], configured))
    trace = next(item for item in caplog.messages if "raipur_runtime_trace" in item)
    assert "service_code=jet_ski_ride" in trace and "answer_service_knowledge" in trace
    assert "+919000000000" not in trace and "response_character_count=26" in trace
    assert "Approved Jet Ski overview." not in trace
