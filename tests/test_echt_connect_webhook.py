"""Focused contract tests for the CRM/ECHT Connect bridge."""

import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import echt_connect_webhook
from app.integrations.echt_connect import (
    EchtConnectClient,
    EchtConnectNumberCredentials,
    validate_signature,
)
from app.main import app
from app.services.inbound_messages import InboundMessageResult


NUMBER_ID = "number_f4210d24-7b59-48ad-b1d1-c780b0ada5d2"
CALLBACK_URL = (
    "https://whatsapp-panel-backend.hasim-c9e.workers.dev/api/integrations/"
    f"chatbot/numbers/{NUMBER_ID}/reply"
)


def settings(*, enabled: bool = True):
    configured = {
        NUMBER_ID: {
            "webhook_secret": "webhook-test-secret",
            "api_key": "callback-test-key",
            "callback_url": CALLBACK_URL,
            "business_phone": "+917948502801",
        }
    }
    return SimpleNamespace(
        echt_connect_enabled=enabled,
        echt_connect_numbers_json=SecretStr(json.dumps(configured)),
        echt_connect_callback_timeout_seconds=10.0,
    )


def payload() -> dict:
    return {
        "event": "message.received",
        "mode": "shadow",
        "numberId": NUMBER_ID,
        "conversationId": "crm-conversation-1",
        "messageId": "crm-message-1",
        "customerId": "crm-customer-1",
        "customerPhone": "+919000000000",
        "customerName": "Test Customer",
        "messageType": "text",
        "messageText": "Hello",
        "timestamp": "2026-09-01T06:30:00Z",
        "isNewConversation": True,
        "isNewCustomer": True,
    }


def signed_body(data: dict) -> tuple[bytes, str]:
    body = json.dumps(data, separators=(",", ":")).encode()
    digest = hmac.new(b"webhook-test-secret", body, hashlib.sha256).hexdigest()
    return body, f"sha256={digest}"


def test_signed_webhook_returns_202_and_schedules_only_echt_processing(monkeypatch):
    scheduled = []

    async def capture(inbound, credentials, loaded_settings):
        scheduled.append((inbound, credentials, loaded_settings))

    monkeypatch.setattr(echt_connect_webhook, "get_settings", settings)
    monkeypatch.setattr(echt_connect_webhook, "process_echt_connect_background", capture)
    body, signature = signed_body(payload())

    response = TestClient(app).post(
        "/webhooks/echt-connect/inbound",
        content=body,
        headers={"content-type": "application/json", "X-Chatbot-Signature": signature},
    )

    assert response.status_code == 202
    assert len(scheduled) == 1
    assert scheduled[0][0].number_id == NUMBER_ID
    assert scheduled[0][1].callback_url == CALLBACK_URL


def test_webhook_rejects_missing_or_invalid_hmac(monkeypatch):
    monkeypatch.setattr(echt_connect_webhook, "get_settings", settings)
    body, _signature = signed_body(payload())
    for signature in (None, "sha256=bad", "bad"):
        headers = {"content-type": "application/json"}
        if signature is not None:
            headers["X-Chatbot-Signature"] = signature
        response = TestClient(app).post(
            "/webhooks/echt-connect/inbound", content=body, headers=headers,
        )
        assert response.status_code == 401


def test_disabled_integration_fails_closed(monkeypatch):
    monkeypatch.setattr(echt_connect_webhook, "get_settings", lambda: settings(enabled=False))
    response = TestClient(app).post("/webhooks/echt-connect/inbound", json=payload())
    assert response.status_code == 503


def test_handover_sends_bot_reply_via_exotel_then_notifies_crm_without_duplicate_reply(monkeypatch):
    inbound_row = {"id": "internal-inbound"}
    persisted = InboundMessageResult(
        duplicate=False,
        customer={"id": "internal-customer", "name": "Test Customer", "email": "test@example.com"},
        conversation={"id": "internal-conversation"},
        inbound_message=inbound_row,
    )
    seen = {"messages": [], "callbacks": [], "exotel": []}

    class Service:
        def process(self, message):
            seen["messages"].append(message)
            return persisted

    class Orchestrator:
        def process(self, message, **kwargs):
            assert kwargs["source_message_id"] == "crm-message-1"
            return SimpleNamespace(
                draft_text="Approved chatbot reply",
                human_handover_required=True,
                reason_code="customer_requested_human",
            )

    class CallbackClient:
        def __init__(self, **_kwargs):
            pass

        async def send_reply(self, credentials, reply):
            seen["callbacks"].append((credentials, reply))

    async def send_via_exotel(**kwargs):
        seen["exotel"].append(kwargs)
        return True

    monkeypatch.setattr(echt_connect_webhook, "get_inbound_message_service", Service)
    monkeypatch.setattr(echt_connect_webhook, "get_raipur_inbound_orchestrator", Orchestrator)
    monkeypatch.setattr(echt_connect_webhook, "EchtConnectClient", CallbackClient)
    monkeypatch.setattr(echt_connect_webhook, "send_echt_orchestration_via_exotel", send_via_exotel)
    credentials = EchtConnectNumberCredentials(
        NUMBER_ID, "webhook-test-secret", "callback-test-key", CALLBACK_URL, "+917948502801"
    )
    active_payload = payload()
    active_payload["mode"] = "active"
    inbound = echt_connect_webhook.EchtConnectInbound.model_validate(active_payload)

    import asyncio
    asyncio.run(echt_connect_webhook.process_echt_connect_background(inbound, credentials, settings()))

    assert seen["messages"][0].external_provider == "echt_connect"
    assert seen["messages"][0].business_whatsapp_number == "+917948502801"
    assert len(seen["exotel"]) == 1
    assert len(seen["callbacks"]) == 1
    callback = seen["callbacks"][0][1].model_dump(by_alias=True, exclude_none=True)
    assert callback == {
        "conversationId": "crm-conversation-1",
        "inReplyToMessageId": "crm-message-1",
        "handover": True,
        "handoverReason": "customer_requested_human",
    }


def test_normal_bot_reply_uses_exotel_and_does_not_call_crm_reply(monkeypatch):
    persisted = InboundMessageResult(
        duplicate=False,
        customer={"id": "internal-customer", "name": "Test Customer", "email": "test@example.com"},
        conversation={"id": "internal-conversation"},
        inbound_message={"id": "internal-inbound"},
    )
    seen = {"exotel": [], "callbacks": []}

    class Service:
        def process(self, _message):
            return persisted

    class Orchestrator:
        def process(self, _message, **_kwargs):
            return SimpleNamespace(
                draft_text="Approved package with actions",
                human_handover_required=False,
                reason_code="coimbatore_standard_package",
                response_valid=True,
                safe_metadata={
                    "interactive_message": {
                        "kind": "list", "button_label": "Package Actions",
                        "options": [{"id": "book_now", "title": "Book Now"}],
                    }
                },
            )

    class CallbackClient:
        def __init__(self, **_kwargs):
            pass

        async def send_reply(self, *_args):
            seen["callbacks"].append(True)

    async def send_via_exotel(**kwargs):
        seen["exotel"].append(kwargs["orchestration"].safe_metadata["interactive_message"])
        return True

    monkeypatch.setattr(echt_connect_webhook, "get_inbound_message_service", Service)
    monkeypatch.setattr(echt_connect_webhook, "get_raipur_inbound_orchestrator", Orchestrator)
    monkeypatch.setattr(echt_connect_webhook, "EchtConnectClient", CallbackClient)
    monkeypatch.setattr(echt_connect_webhook, "send_echt_orchestration_via_exotel", send_via_exotel)
    credentials = EchtConnectNumberCredentials(
        NUMBER_ID, "webhook-test-secret", "callback-test-key", CALLBACK_URL, "+917948502801"
    )
    active_payload = payload()
    active_payload["mode"] = "active"
    inbound = echt_connect_webhook.EchtConnectInbound.model_validate(active_payload)

    import asyncio
    asyncio.run(echt_connect_webhook.process_echt_connect_background(inbound, credentials, settings()))

    assert len(seen["exotel"]) == 1
    assert seen["exotel"][0]["options"][0] == {"id": "book_now", "title": "Book Now"}
    assert seen["callbacks"] == []


def test_shadow_mode_never_sends_exotel_or_handover_callback(monkeypatch):
    persisted = InboundMessageResult(
        duplicate=False,
        customer={"id": "internal-customer", "name": "Test Customer", "email": "test@example.com"},
        conversation={"id": "internal-conversation"},
        inbound_message={"id": "internal-inbound"},
    )
    seen = {"exotel": False, "callback": False}

    class Service:
        def process(self, _message):
            return persisted

    class Orchestrator:
        def process(self, _message, **_kwargs):
            return SimpleNamespace(
                draft_text="Would otherwise be delivered",
                human_handover_required=True,
                reason_code="customer_requested_human",
            )

    class CallbackClient:
        def __init__(self, **_kwargs):
            pass

        async def send_reply(self, *_args):
            seen["callback"] = True

    async def send_via_exotel(**_kwargs):
        seen["exotel"] = True
        return True

    monkeypatch.setattr(echt_connect_webhook, "get_inbound_message_service", Service)
    monkeypatch.setattr(echt_connect_webhook, "get_raipur_inbound_orchestrator", Orchestrator)
    monkeypatch.setattr(echt_connect_webhook, "EchtConnectClient", CallbackClient)
    monkeypatch.setattr(echt_connect_webhook, "send_echt_orchestration_via_exotel", send_via_exotel)
    credentials = EchtConnectNumberCredentials(
        NUMBER_ID, "webhook-test-secret", "callback-test-key", CALLBACK_URL, "+917948502801"
    )

    import asyncio
    asyncio.run(echt_connect_webhook.process_echt_connect_background(
        echt_connect_webhook.EchtConnectInbound.model_validate(payload()),
        credentials,
        settings(),
    ))

    assert seen == {"exotel": False, "callback": False}


def test_duplicate_echt_message_never_sends_exotel_or_callback(monkeypatch):
    seen = {"orchestrated": False, "exotel": False, "callback": False}

    class Service:
        def process(self, _message):
            return InboundMessageResult(duplicate=True)

    class Orchestrator:
        def process(self, *_args, **_kwargs):
            seen["orchestrated"] = True

    class CallbackClient:
        def __init__(self, **_kwargs):
            pass

        async def send_reply(self, *_args):
            seen["callback"] = True

    async def send_via_exotel(**_kwargs):
        seen["exotel"] = True
        return True

    monkeypatch.setattr(echt_connect_webhook, "get_inbound_message_service", Service)
    monkeypatch.setattr(echt_connect_webhook, "get_raipur_inbound_orchestrator", Orchestrator)
    monkeypatch.setattr(echt_connect_webhook, "EchtConnectClient", CallbackClient)
    monkeypatch.setattr(echt_connect_webhook, "send_echt_orchestration_via_exotel", send_via_exotel)
    active_payload = payload()
    active_payload["mode"] = "active"
    credentials = EchtConnectNumberCredentials(
        NUMBER_ID, "webhook-test-secret", "callback-test-key", CALLBACK_URL, "+917948502801"
    )

    import asyncio
    asyncio.run(echt_connect_webhook.process_echt_connect_background(
        echt_connect_webhook.EchtConnectInbound.model_validate(active_payload),
        credentials,
        settings(),
    ))

    assert seen == {"orchestrated": False, "exotel": False, "callback": False}


def test_incomplete_customer_is_persisted_but_crm_reply_is_suppressed(monkeypatch):
    persisted = InboundMessageResult(
        duplicate=False,
        customer={"id": "internal-customer", "name": "Test Customer", "details_completed_at": None},
        conversation={"id": "internal-conversation"},
        inbound_message={"id": "internal-inbound"},
    )
    seen = {"orchestrated": False, "callback": False}

    class Service:
        def process(self, _message):
            return persisted

    class Orchestrator:
        def process(self, *_args, **_kwargs):
            seen["orchestrated"] = True

    class CallbackClient:
        def __init__(self, **_kwargs):
            pass

        async def send_reply(self, *_args):
            seen["callback"] = True

    monkeypatch.setattr(echt_connect_webhook, "get_inbound_message_service", Service)
    monkeypatch.setattr(echt_connect_webhook, "get_raipur_inbound_orchestrator", Orchestrator)
    monkeypatch.setattr(echt_connect_webhook, "EchtConnectClient", CallbackClient)
    credentials = EchtConnectNumberCredentials(
        NUMBER_ID, "webhook-test-secret", "callback-test-key", CALLBACK_URL, "+917948502801"
    )
    inbound = echt_connect_webhook.EchtConnectInbound.model_validate(payload())

    import asyncio
    asyncio.run(echt_connect_webhook.process_echt_connect_background(inbound, credentials, settings()))

    assert seen == {"orchestrated": False, "callback": False}


def test_callback_uses_bearer_key_and_exact_contract():
    captured = {}

    def provider(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(202, json={"accepted": True})

    credentials = EchtConnectNumberCredentials(
        NUMBER_ID, "webhook-test-secret", "callback-test-key", CALLBACK_URL, "+917948502801"
    )
    reply = echt_connect_webhook.EchtConnectReply(
        conversationId="conversation", inReplyToMessageId="message",
        reply="Hello", handover=False,
    )
    import asyncio
    asyncio.run(EchtConnectClient(transport=httpx.MockTransport(provider)).send_reply(credentials, reply))

    assert captured["authorization"] == "Bearer callback-test-key"
    assert captured["body"] == {
        "conversationId": "conversation",
        "inReplyToMessageId": "message",
        "reply": "Hello",
        "handover": False,
    }


def test_callback_retries_429_and_5xx_then_accepts():
    attempts = []

    def provider(_request: httpx.Request) -> httpx.Response:
        attempts.append(True)
        status = (429, 503, 202)[len(attempts) - 1]
        return httpx.Response(status, json={})

    credentials = EchtConnectNumberCredentials(
        NUMBER_ID, "webhook-test-secret", "callback-test-key", CALLBACK_URL, "+917948502801"
    )
    reply = echt_connect_webhook.EchtConnectReply(
        conversationId="conversation", inReplyToMessageId="message", reply="Hello",
    )
    import asyncio
    asyncio.run(EchtConnectClient(transport=httpx.MockTransport(provider)).send_reply(credentials, reply))
    assert len(attempts) == 3


def test_signature_requires_documented_sha256_prefix():
    body = b'{"message":"hello"}'
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert validate_signature(body, f"sha256={digest}", "secret") is True
    assert validate_signature(body, digest, "secret") is False


def test_echt_message_contract_carries_provider_identity_for_flow_bypass():
    credentials = EchtConnectNumberCredentials(
        NUMBER_ID, "webhook-test-secret", "callback-test-key", CALLBACK_URL, "+917948502801"
    )
    inbound = echt_connect_webhook.EchtConnectInbound.model_validate(payload())
    message = echt_connect_webhook.NormalizedInboundMessage(
        external_provider="echt_connect",
        external_message_id=inbound.message_id,
        customer_whatsapp_number=inbound.customer_phone,
        business_whatsapp_number=credentials.business_phone,
        profile_name=inbound.customer_name,
        message_type="text",
        content=inbound.message_text,
        received_at=inbound.timestamp,
    )
    assert message.external_provider == "echt_connect"
