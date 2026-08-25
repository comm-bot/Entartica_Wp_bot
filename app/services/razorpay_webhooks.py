"""Deterministic Razorpay webhook authentication and payment-state transitions."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
from typing import Any

from app.repositories.bookings import BookingRepository
from app.repositories.payments import PaymentRepository
from app.repositories.webhook_events import WebhookEventRepository


def verify_razorpay_signature(raw_body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class RazorpayWebhookService:
    SUPPORTED = {"payment_link.paid", "payment_link.expired", "payment_link.cancelled"}

    def __init__(self, database: Any) -> None:
        self._bookings = BookingRepository(database)
        self._payments = PaymentRepository(database)
        self._events = WebhookEventRepository(database)

    def process(self, provider_event_id: str, payload: dict[str, Any]) -> tuple[str, bool, str | None]:
        event_type = payload.get("event")
        event, created = self._events.try_create_webhook_event({
            "provider": "razorpay", "provider_event_id": provider_event_id,
            "event_type": str(event_type or "unknown"), "status": "received",
        })
        if not created:
            if (event_type == "payment_link.paid" and event.get("status") == "processed"
                    and isinstance(event.get("booking_id"), str) and event["booking_id"]):
                # A verified replay may safely retry the idempotent downstream
                # confirmation (for example after a temporary S3 dependency
                # failure). Payment rows are not mutated again here.
                return "duplicate", True, event["booking_id"]
            return "duplicate", False, None
        if event_type not in self.SUPPORTED:
            self._events.update_webhook_event(event["id"], {
                "status": "ignored", "processed_at": datetime.now(UTC).isoformat(),
            })
            return "ignored", False, None
        entities = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        link_wrapper = entities.get("payment_link") if isinstance(entities, dict) else None
        link = link_wrapper.get("entity") if isinstance(link_wrapper, dict) else None
        link = link if isinstance(link, dict) else {}
        payment = self._payments.get_payment_by_provider_link_id(str(link.get("id") or ""))
        if payment is None:
            self._events.mark_webhook_event_failed(event["id"], "unknown_payment_link")
            return "verification_failed", False, None
        booking = self._bookings.get_booking_by_id(str(payment["booking_id"]))
        self._events.update_webhook_event(event["id"], {
            "status": "processing", "booking_id": payment["booking_id"], "payment_id": payment["id"],
        })
        if event_type == "payment_link.paid":
            payment_wrapper = entities.get("payment") if isinstance(entities, dict) else None
            provider_payment = payment_wrapper.get("entity") if isinstance(payment_wrapper, dict) else None
            provider_payment = provider_payment if isinstance(provider_payment, dict) else {}
            valid = bool(
                booking and link.get("status") == "paid"
                and link.get("reference_id") == payment.get("reference_id") == booking.get("booking_ref")
                and link.get("currency") == payment.get("currency") == "INR"
                and link.get("amount") == payment.get("amount_paise") == booking.get("amount_paise")
                and link.get("amount_paid") == payment.get("amount_paise")
                and isinstance(provider_payment.get("id"), str)
                and provider_payment.get("status") == "captured"
                and provider_payment.get("amount") == payment.get("amount_paise")
                and provider_payment.get("currency") == "INR"
            )
            if not valid:
                self._payments.update_payment(payment["id"], {"status": "verification_failed"})
                self._events.mark_webhook_event_failed(event["id"], "payment_verification_failed")
                return "verification_failed", False, None
            now = datetime.now(UTC).isoformat()
            self._payments.update_payment(payment["id"], {
                "status": "paid", "provider_payment_id": provider_payment["id"], "paid_at": now,
            })
            self._bookings.update_booking(booking["id"], {"status": "payment_received", "payment_received_at": now})
        else:
            status = "expired" if event_type.endswith("expired") else "cancelled"
            fields = {"status": status}
            if status == "expired": fields["expired_at"] = datetime.now(UTC).isoformat()
            self._payments.update_payment(payment["id"], fields)
        self._events.mark_webhook_event_processed(event["id"])
        return "processed", event_type == "payment_link.paid", str(payment["booking_id"]) if event_type == "payment_link.paid" else None
