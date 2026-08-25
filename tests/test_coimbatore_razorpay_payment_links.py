from datetime import date
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.integrations.razorpay import RazorpayConfigurationError, RazorpayPaymentLinkClient
from app.services.coimbatore.payment_links import CoimbatorePaymentLinkService, generate_booking_ref
from app.services.coimbatore.pontoon_package import resolve_standard_package_pricing
from app.services.razorpay_webhooks import RazorpayWebhookService, verify_razorpay_signature
from app.api.razorpay_webhook import router as razorpay_router
from app.api.razorpay_webhook import generate_and_send_confirmation
from tests.test_booking_foundation import Client


class FakeRazorpay:
    def __init__(self): self.requests = []
    def create_payment_link(self, payload):
        self.requests.append(payload)
        sequence = len(self.requests)
        return {"id":f"plink_test_{sequence}", "short_url":f"https://rzp.io/i/test-link-{sequence}",
                "reference_id":payload["reference_id"], "amount":payload["amount"],
                "currency":"INR", "status":"created"}


def create_link(client, guests=8):
    provider = FakeRazorpay()
    result = CoimbatorePaymentLinkService(client, provider).create_or_reuse(
        customer_id="customer-1", conversation_id="conversation-1",
        customer_mobile="+919999999999", customer_name="Customer",
        customer_email="customer@example.com", event_date=date(2026, 8, 30),
        preferred_time=None, guest_count=guests,
    )
    return result, provider


@pytest.mark.parametrize(("guests", "paise"), ((1,510000),(6,510000),(7,637500),(9,637500),(10,765000),(12,765000)))
def test_payment_amount_uses_exact_approved_pricing(guests, paise):
    assert resolve_standard_package_pricing(guests).offer_price_paise == paise


def test_booking_and_payment_link_are_durable_and_reused():
    client = Client()
    first, provider = create_link(client)
    second = CoimbatorePaymentLinkService(client, provider).create_or_reuse(
        customer_id="customer-1", conversation_id="conversation-1",
        customer_mobile="+919999999999", customer_name="Customer",
        customer_email="customer@example.com", event_date=date(2026, 8, 30),
        preferred_time=None, guest_count=8,
    )
    assert first.booking["booking_ref"].startswith("CBE-PTN-") and len(first.booking["booking_ref"]) <= 40
    assert first.payment["payment_url"] == "https://rzp.io/i/test-link-1"
    assert first.payment["amount_paise"] == 637500 and first.payment["status"] == "issued"
    assert first.booking["customer_email"] == "customer@example.com"
    assert provider.requests[0]["accept_partial"] is False
    assert provider.requests[0]["reference_id"] == first.booking["booking_ref"]
    assert provider.requests[0]["notify"] == {"sms":False, "email":False}
    assert second.reused and second.payment["id"] == first.payment["id"] and len(provider.requests) == 1


def test_booking_ref_is_opaque_and_short():
    refs = {generate_booking_ref() for _ in range(20)}
    assert len(refs) == 20 and all(len(value) <= 40 for value in refs)


def test_client_fails_closed_for_non_test_configuration():
    with pytest.raises(RazorpayConfigurationError):
        RazorpayPaymentLinkClient(key_id="rzp_live_bad", key_secret="secret", mode="test")
    with pytest.raises(RazorpayConfigurationError):
        RazorpayPaymentLinkClient(key_id="rzp_test_ok", key_secret="secret", mode="live")


def test_client_posts_standard_payment_link_without_exposing_auth():
    captured = {}
    def provider(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id":"plink_1","short_url":"https://rzp.io/i/1",
            "reference_id":"CBE-PTN-1","amount":510000,"currency":"INR","status":"created"})
    client = RazorpayPaymentLinkClient(key_id="rzp_test_key", key_secret="secret", transport=httpx.MockTransport(provider))
    result = client.create_payment_link({"reference_id":"CBE-PTN-1","amount":510000,"currency":"INR"})
    assert result["short_url"].startswith("https://rzp.io/") and captured["payload"]["amount"] == 510000


def paid_payload(result, *, amount=637500, currency="INR", reference_id=None, link_id="plink_test_1"):
    return {"event":"payment_link.paid", "payload":{
        "payment_link":{"entity":{"id":link_id, "status":"paid",
            "reference_id":reference_id or result.booking["booking_ref"], "currency":currency,
            "amount":amount, "amount_paid":amount}},
        "payment":{"entity":{"id":"pay_test_1", "status":"captured", "amount":amount, "currency":currency}},
    }}


def test_webhook_signature_uses_exact_raw_body():
    raw = b'{"event":"payment_link.paid", "x":1}'
    import hashlib, hmac
    signature = hmac.new(b"webhook-secret", raw, hashlib.sha256).hexdigest()
    assert verify_razorpay_signature(raw, signature, "webhook-secret")
    assert not verify_razorpay_signature(raw + b" ", signature, "webhook-secret")
    assert not verify_razorpay_signature(raw, None, "webhook-secret")


def test_valid_paid_webhook_is_idempotent_and_marks_payment_received():
    client = Client(); linked, _ = create_link(client)
    service = RazorpayWebhookService(client)
    assert service.process("evt_1", paid_payload(linked)) == ("processed", True, linked.booking["id"])
    assert service.process("evt_1", paid_payload(linked)) == ("duplicate", True, linked.booking["id"])
    assert client.data["payments"][0]["status"] == "paid"
    assert client.data["payments"][0]["provider_payment_id"] == "pay_test_1"
    assert client.data["bookings"][0]["status"] == "payment_received"


@pytest.mark.parametrize("change", ("amount", "currency", "reference", "link"))
def test_paid_webhook_rejects_conflicting_payment_truth(change):
    client = Client(); linked, _ = create_link(client); payload = paid_payload(linked)
    if change == "amount": payload = paid_payload(linked, amount=510000)
    elif change == "currency": payload = paid_payload(linked, currency="USD")
    elif change == "reference": payload = paid_payload(linked, reference_id="WRONG")
    else: payload = paid_payload(linked, link_id="plink_unknown")
    status, paid, booking_id = RazorpayWebhookService(client).process(f"evt_{change}", payload)
    assert status == "verification_failed" and not paid
    assert booking_id is None
    assert client.data["bookings"][0]["status"] != "payment_received"


@pytest.mark.parametrize(("event_type", "expected"), (("payment_link.expired","expired"),("payment_link.cancelled","cancelled")))
def test_terminal_unpaid_events_never_mark_booking_paid(event_type, expected):
    client = Client(); linked, _ = create_link(client)
    payload = {"event":event_type, "payload":{"payment_link":{"entity":{"id":"plink_test_1"}}}}
    assert RazorpayWebhookService(client).process(f"evt_{expected}", payload) == ("processed", False, None)
    assert client.data["payments"][0]["status"] == expected
    assert client.data["bookings"][0]["status"] != "payment_received"


def test_terminal_link_gets_new_booking_reference_on_later_book_now():
    client = Client(); linked, provider = create_link(client)
    RazorpayWebhookService(client).process("evt_expire", {
        "event":"payment_link.expired",
        "payload":{"payment_link":{"entity":{"id":"plink_test_1"}}},
    })
    replacement = CoimbatorePaymentLinkService(client, provider).create_or_reuse(
        customer_id="customer-1", conversation_id="conversation-1", customer_mobile=None,
        customer_name=None, customer_email=None, event_date=date(2026, 8, 30),
        preferred_time=None, guest_count=8,
    )
    assert replacement.booking["booking_ref"] != linked.booking["booking_ref"]
    assert replacement.payment["provider_payment_link_id"] == "plink_test_2"


def test_webhook_route_rejects_missing_invalid_and_accepts_valid_signature(monkeypatch):
    database = Client(); linked, _ = create_link(database)
    scheduled = []
    monkeypatch.setattr("app.api.razorpay_webhook.get_supabase_client", lambda: database)
    monkeypatch.setattr("app.api.razorpay_webhook.generate_and_send_confirmation", scheduled.append)
    monkeypatch.setattr("app.api.razorpay_webhook.get_settings",
                        lambda: type("S", (), {"razorpay_webhook_secret":SecretStr("webhook-secret")})())
    app = FastAPI(); app.include_router(razorpay_router); client = TestClient(app)
    raw = json.dumps(paid_payload(linked), separators=(",", ":")).encode()
    missing = client.post("/webhooks/razorpay", content=raw)
    invalid = client.post("/webhooks/razorpay", content=raw,
                          headers={"x-razorpay-signature":"bad", "x-razorpay-event-id":"evt-route"})
    import hashlib, hmac
    signature = hmac.new(b"webhook-secret", raw, hashlib.sha256).hexdigest()
    valid = client.post("/webhooks/razorpay", content=raw,
        headers={"x-razorpay-signature":signature, "x-razorpay-event-id":"evt-route"})
    duplicate = client.post("/webhooks/razorpay", content=raw,
        headers={"x-razorpay-signature":signature, "x-razorpay-event-id":"evt-route"})
    assert missing.status_code == 401 and invalid.status_code == 401
    assert valid.status_code == 200 and valid.json()["payment_received"] is True
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
    assert scheduled == [linked.booking["id"], linked.booking["id"]]


def test_confirmation_background_failure_is_contained_and_logged(monkeypatch, caplog):
    monkeypatch.setattr(
        "app.api.razorpay_webhook.get_settings",
        lambda: (_ for _ in ()).throw(RuntimeError("configuration unavailable")),
    )
    generate_and_send_confirmation("booking-safe")
    assert "booking_confirmation_background_failed" in caplog.text
    assert "RuntimeError" in caplog.text
