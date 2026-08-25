"""Durable Coimbatore Standard-package Payment Link creation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
import logging
import secrets
from typing import Any

from app.repositories.bookings import BookingRepository
from app.repositories.payments import PaymentRepository
from app.services.coimbatore.pontoon_package import STANDARD_PACKAGE_ID, resolve_standard_package_pricing

logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class PaymentLinkResult:
    booking: dict[str, Any]
    payment: dict[str, Any]
    reused: bool


def generate_booking_ref() -> str:
    return f"CBE-PTN-{secrets.token_hex(8).upper()}"


class CoimbatorePaymentLinkService:
    def __init__(self, database: Any, razorpay: Any) -> None:
        self._bookings = BookingRepository(database)
        self._payments = PaymentRepository(database)
        self._razorpay = razorpay

    def create_or_reuse(self, *, customer_id: str, conversation_id: str,
                        customer_mobile: str | None, customer_name: str | None,
                        customer_email: str | None, event_date: date,
                        preferred_time: time | None, guest_count: int) -> PaymentLinkResult:
        pricing = resolve_standard_package_pricing(guest_count)
        if pricing is None:
            raise ValueError("standard_payment_pricing_unavailable")
        booking = self._bookings.get_active_booking_for_conversation(conversation_id)
        expected = {
            "customer_id": customer_id, "package_id": STANDARD_PACKAGE_ID,
            "event_date": event_date.isoformat(), "guest_count": guest_count,
            "amount_paise": pricing.offer_price_paise, "currency": "INR",
        }
        if booking is not None and any(booking.get(key) != value for key, value in expected.items()):
            booking = None
        if booking is not None:
            if booking.get("status") == "payment_received":
                paid = self._payments.get_payment_by_reference(str(booking["booking_ref"]))
                if paid is not None and paid.get("payment_url"):
                    return PaymentLinkResult(booking, paid, True)
            payment = self._payments.get_active_payment_for_booking(str(booking["id"]))
            if payment is not None and payment.get("payment_url") and payment.get("provider_payment_link_id"):
                return PaymentLinkResult(booking, payment, True)
            if self._payments.get_payment_by_reference(str(booking["booking_ref"])) is not None:
                # Razorpay requires a unique reference per Payment Link. A terminal
                # or invalid attempt therefore starts a new booking/ref rather than
                # reusing another link's immutable reference.
                booking = None
        if booking is None:
            booking = self._bookings.create_booking({
                "booking_ref": generate_booking_ref(), "conversation_id": conversation_id,
                "customer_id": customer_id, "location_code": "coimbatore",
                "product_code": "pontoon_celebration", "package_id": STANDARD_PACKAGE_ID,
                "event_date": event_date.isoformat(),
                "preferred_time": preferred_time.isoformat() if preferred_time else None,
                "guest_count": guest_count, "customer_name": customer_name,
                "customer_mobile": customer_mobile, "customer_email": customer_email,
                "amount_paise": pricing.offer_price_paise, "currency": "INR",
                "status": "form_submitted",
            })
        booking_ref = str(booking["booking_ref"])
        customer = {key: value for key, value in {
            "name": customer_name, "contact": customer_mobile, "email": customer_email,
        }.items() if value}
        try:
            created = self._razorpay.create_payment_link({
                "amount": pricing.offer_price_paise, "currency": "INR", "accept_partial": False,
                "reference_id": booking_ref,
                "description": f"Entartica Coimbatore Pontoon Celebration - {booking_ref}",
                "customer": customer, "notify": {"sms": False, "email": False},
                "notes": {"booking_ref": booking_ref, "package_id": STANDARD_PACKAGE_ID,
                          "guest_count": str(guest_count)},
            })
        except Exception:
            self._bookings.update_booking(str(booking["id"]), {"status": "payment_link_failed"})
            raise
        if (created.get("reference_id") != booking_ref or created.get("amount") != pricing.offer_price_paise
                or created.get("currency") != "INR"):
            self._bookings.update_booking(str(booking["id"]), {"status": "payment_link_failed"})
            raise RuntimeError("razorpay_payment_link_mismatch")
        payment = self._payments.create_payment({
            "booking_id": booking["id"], "provider": "razorpay", "reference_id": booking_ref,
            "provider_payment_link_id": created["id"], "payment_url": created["short_url"],
            "amount_paise": pricing.offer_price_paise, "currency": "INR", "status": "issued",
        })
        booking = self._bookings.update_booking(str(booking["id"]), {"status": "payment_pending"}) or booking
        logger.info("razorpay_payment_link_created booking_ref=%s payment_link_id=%s amount_paise=%s mode=test",
                    booking_ref, created["id"], pricing.offer_price_paise)
        return PaymentLinkResult(booking, payment, False)
