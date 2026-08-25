from datetime import UTC, datetime
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.repositories.bookings import BookingRepository
from app.repositories.payments import PaymentRepository
from app.services.coimbatore.booking_confirmation import (
    BookingConfirmationService,
    generate_confirmation_pdf,
)
from tests.test_booking_foundation import Client


class MemoryStorage:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.objects = {}
        self.store_calls = 0

    def store(self, key, content):
        self.store_calls += 1
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.objects[key] = content
        return self.url_for(key)

    def url_for(self, key):
        return f"https://signed.example/{key}?temporary=1"


class MemoryDelivery:
    def __init__(self, outcomes=(True,)):
        self.outcomes = list(outcomes)
        self.calls = []

    def send(self, **values):
        self.calls.append(values)
        return self.outcomes.pop(0)


def paid_records(guests=8, *, package_id="coimbatore_pontoon_standard", amount_paise=None):
    offers = {4: 510000, 8: 637500, 11: 765000}
    amount = amount_paise if amount_paise is not None else (340000 if package_id.endswith("couple_romance") else offers[guests])
    database = Client()
    booking = BookingRepository(database).create_booking({
        "booking_ref": f"CBE-PTN-TEST{guests}", "conversation_id": "conversation-1",
        "customer_id": "customer-1", "customer_name": "Test Customer",
        "customer_mobile": "+919999999999", "customer_email": "test@example.com",
        "location_code": "coimbatore", "product_code": "pontoon_celebration",
        "package_id": package_id, "event_date": "2026-09-15", "preferred_time": "18:30:00",
        "guest_count": guests, "amount_paise": amount, "currency": "INR", "status": "payment_received",
    })
    payment = PaymentRepository(database).create_payment({
        "booking_id": booking["id"], "provider": "razorpay", "reference_id": booking["booking_ref"],
        "provider_payment_link_id": "plink_test", "provider_payment_id": "pay_test_verified",
        "amount_paise": amount, "currency": "INR", "status": "paid",
        "paid_at": "2026-08-22T06:30:00+00:00",
    })
    return database, booking, payment


@pytest.mark.parametrize(("guests", "regular", "offer"), ((4, "5,999", "5,100"), (8, "7,500", "6,375"), (11, "9,000", "7,650")))
def test_pdf_contains_verified_booking_and_dynamic_pricing(guests, regular, offer):
    _, booking, payment = paid_records(guests)
    content = generate_confirmation_pdf(
        booking, payment, razorpay_mode="test",
        generated_at=datetime(2026, 8, 22, 7, 0, tzinfo=UTC),
    )
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
    pages = PdfReader(BytesIO(content)).pages
    assert content.startswith(b"%PDF") and "TEST MODE - NOT A LIVE BOOKING" in text
    assert len(pages) == 3
    assert "BOOKING SUMMARY" in (pages[0].extract_text() or "")
    assert "TERMS & CONDITIONS" not in (pages[0].extract_text() or "")
    assert "TERMS & CONDITIONS" in (pages[1].extract_text() or "")
    assert "TERMS & CONDITIONS" in (pages[2].extract_text() or "")
    assert booking["booking_ref"] in text and "Test Customer" in text and "15 Sep 2026" in text
    assert regular in text and offer in text and "pay_test_verified" in text
    assert "22 Aug 2026, 12:00 PM IST" in text and "22 Aug 2026, 12:30 PM IST" in text


def test_no_confirmation_without_verified_payment():
    database, booking, _ = paid_records()
    database.data["payments"][0]["status"] = "issued"
    storage, delivery = MemoryStorage(), MemoryDelivery()
    result = BookingConfirmationService(database, storage, delivery).ensure_confirmation(booking["id"])
    assert not result.completed and result.reason == "verified_payment_required"
    assert storage.store_calls == 0 and delivery.calls == []


def test_success_stores_exact_key_sends_document_and_confirms_once():
    database, booking, _ = paid_records()
    storage, delivery = MemoryStorage(), MemoryDelivery()
    service = BookingConfirmationService(database, storage, delivery)
    first = service.ensure_confirmation(booking["id"])
    second = service.ensure_confirmation(booking["id"])
    row = database.data["bookings"][0]
    expected_key = f"booking-confirmations/{booking['booking_ref']}.pdf"
    assert first.completed and not first.reused_pdf and second.reason == "already_confirmed"
    assert storage.store_calls == 1 and list(storage.objects) == [expected_key]
    assert len(delivery.calls) == 1 and delivery.calls[0]["filename"].endswith(".pdf")
    assert "Test Payment Successful" in delivery.calls[0]["caption"]
    assert row["status"] == "confirmed" and row["confirmation_pdf_storage_key"] == expected_key
    assert row["confirmation_pdf_url"].startswith("https://signed.example/") and row["confirmed_at"]


def test_delivery_failure_keeps_paid_pdf_and_retry_reuses_it():
    database, booking, _ = paid_records()
    storage, delivery = MemoryStorage(), MemoryDelivery((False, True))
    service = BookingConfirmationService(database, storage, delivery)
    first = service.ensure_confirmation(booking["id"])
    assert not first.completed and first.reason == "whatsapp_delivery_failed"
    assert database.data["bookings"][0]["status"] == "confirmation_failed"
    assert database.data["payments"][0]["status"] == "paid"
    second = service.ensure_confirmation(booking["id"])
    assert second.completed and second.reused_pdf and storage.store_calls == 1
    assert database.data["bookings"][0]["status"] == "confirmed" and len(delivery.calls) == 2


def test_storage_failure_does_not_change_verified_payment_truth():
    database, booking, _ = paid_records()
    result = BookingConfirmationService(database, MemoryStorage(fail=True), MemoryDelivery()).ensure_confirmation(booking["id"])
    assert not result.completed and result.reason == "confirmation_failed"
    assert database.data["bookings"][0]["status"] == "confirmation_failed"
    assert database.data["payments"][0]["status"] == "paid"


def test_wrong_amount_and_unverified_customer_claim_cannot_generate_pdf():
    _, booking, payment = paid_records(amount_paise=510000)
    payment["amount_paise"] = 637500
    with pytest.raises(ValueError, match="confirmation_payment_not_verified"):
        generate_confirmation_pdf(booking, payment, razorpay_mode="test")
