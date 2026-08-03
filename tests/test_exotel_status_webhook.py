"""Route-level tests for tolerant, SID-only Exotel delivery callbacks."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import status_webhook
from app.config import Settings


class _DeliveryService:
    def __init__(self) -> None:
        self.provider_ids: list[str] = []

    def process(self, callback) -> bool:
        assert callback.provider_message_id
        self.provider_ids.append(callback.provider_message_id)
        return True


def _client(monkeypatch, service: _DeliveryService) -> TestClient:
    app = FastAPI()
    app.include_router(status_webhook.router)
    monkeypatch.setattr(
        status_webhook,
        "get_settings",
        lambda: Settings(exotel_signature_validation_enabled=False),
    )
    monkeypatch.setattr(status_webhook, "get_delivery_status_service", lambda: service)
    return TestClient(app)


def test_status_route_accepts_nested_dlr_and_uses_only_exact_sid(monkeypatch) -> None:
    service = _DeliveryService()

    response = _client(monkeypatch, service).post(
        "/webhooks/exotel/status",
        json={"whatsapp": {"messages": [{"callback_type": "dlr", "sid": "safe-test-sid", "exo_detailed_status": "EX_MESSAGE_DELIVERED"}]}},
    )

    assert response.status_code == 200
    assert service.provider_ids == ["safe-test-sid"]


def test_status_route_accepts_flat_form_dlr_and_acknowledges_unknown_status(monkeypatch) -> None:
    service = _DeliveryService()
    client = _client(monkeypatch, service)

    sent = client.post(
        "/webhooks/exotel/status",
        data={"callback_type": "dlr", "sid": "safe-form-sid", "exo_detailed_status": "EX_MESSAGE_SENT"},
    )
    unknown = client.post(
        "/webhooks/exotel/status",
        data={"callback_type": "dlr", "sid": "safe-form-sid", "exo_detailed_status": "UNKNOWN"},
    )

    assert sent.status_code == 200
    assert unknown.status_code == 200
    assert service.provider_ids == ["safe-form-sid"]


def test_status_route_rejects_malformed_body_but_acknowledges_missing_sid(monkeypatch) -> None:
    service = _DeliveryService()
    client = _client(monkeypatch, service)

    malformed = client.post("/webhooks/exotel/status", content=b"{", headers={"content-type": "application/json"})
    missing_sid = client.post(
        "/webhooks/exotel/status",
        json={"whatsapp": {"messages": [{"callback_type": "dlr", "exo_detailed_status": "EX_MESSAGE_SENT"}]}},
    )

    assert malformed.status_code == 400
    assert missing_sid.status_code == 200
    assert service.provider_ids == []


def test_status_route_accepts_multipart_dlr_without_form_dependency(monkeypatch) -> None:
    service = _DeliveryService()
    boundary = "test-boundary"
    body = (
        b"--test-boundary\r\nContent-Disposition: form-data; name=\"callback_type\"\r\n\r\ndlr\r\n"
        b"--test-boundary\r\nContent-Disposition: form-data; name=\"sid\"\r\n\r\nsafe-multipart-sid\r\n"
        b"--test-boundary\r\nContent-Disposition: form-data; name=\"exo_detailed_status\"\r\n\r\nEX_MESSAGE_SEEN\r\n"
        b"--test-boundary--\r\n"
    )

    response = _client(monkeypatch, service).post(
        "/webhooks/exotel/status",
        content=body,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 200
    assert service.provider_ids == ["safe-multipart-sid"]
