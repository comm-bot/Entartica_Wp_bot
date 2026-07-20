"""Tests for the inbound Exotel webhook."""

import hashlib
import hmac
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr

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
    """A valid mocked payload is acknowledged after persistence."""

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


def test_webhook_hides_persistence_error_details(monkeypatch) -> None:
    """Storage failures do not expose message content or internal details."""

    monkeypatch.setattr(exotel_webhook, "get_settings", lambda: _settings())
    monkeypatch.setattr(exotel_webhook, "get_inbound_message_service", FailingService)

    response = TestClient(app).post("/webhooks/exotel/inbound", json=_payload())

    assert response.status_code == 500
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
