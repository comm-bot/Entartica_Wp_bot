"""Hosted Razorpay Payment Button and Book Now routing checks."""

from datetime import date
from types import SimpleNamespace
import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.services.booking_enquiries import BookingDetails
from app.services.coimbatore.pontoon_package import (
    COUPLE_PACKAGE_ID, STANDARD_PACKAGE_ID, handle_action, payment_page_url,
)
from app.services.raipur.response_models import ConversationContext
from app.services.raipur.sales_state import SalesStage
from app.services.raipur_automatic_replies import eligible_for_automatic_reply


client = TestClient(app)


def _context(package_id: str, guests: int | None = None) -> ConversationContext:
    return ConversationContext(
        details=BookingDetails(
            customer_name=None, requested_service_text="Pontoon Celebration",
            preferred_date=date(2026, 8, 30), preferred_time=None,
            adults_count=None, children_count=None,
            total_guests=guests if guests is not None else 2 if package_id == COUPLE_PACKAGE_ID else 5,
        ),
        selected_location="coimbatore", last_service_code="pontoon_celebration",
        sales_stage=SalesStage.PACKAGE_PRESENTED,
        form_values={"active_package_id": package_id, "standard_package_presented": True},
    )


def test_standard_payment_page_has_only_standard_button_and_no_state_mutation(monkeypatch):
    database_calls = []
    monkeypatch.setattr("app.integrations.supabase.get_supabase_client", lambda: database_calls.append(True))
    response = client.get("/pay/coimbatore/standard")
    assert response.status_code == 200
    assert 'data-payment_button_id="pl_TS1dAzTQUAPVxw"' in response.text
    assert "pl_TS1ekmc61KTlf9" not in response.text
    assert "payment successful" not in response.text.casefold()
    assert database_calls == []


def test_couple_payment_page_has_only_couple_button():
    response = client.get("/pay/coimbatore/couple-romance")
    assert response.status_code == 200
    assert 'data-payment_button_id="pl_TS1ekmc61KTlf9"' in response.text
    assert "pl_TS1dAzTQUAPVxw" not in response.text


def test_higher_standard_payment_pages_use_only_their_configured_slab_buttons(monkeypatch):
    # Keep this route contract independent of the developer's local .env.
    monkeypatch.setattr("app.api.coimbatore_payments.get_settings", lambda: SimpleNamespace(
        coimbatore_standard_up_to_9_razorpay_payment_button_id="pl_TSNThxqzu3nPp5",
        coimbatore_standard_up_to_12_razorpay_payment_button_id="pl_TSNUw0LO5O98q2",
    ))
    up_to_9 = client.get("/pay/coimbatore/standard/up-to-9")
    assert up_to_9.status_code == 200
    assert 'data-payment_button_id="pl_TSNThxqzu3nPp5"' in up_to_9.text
    assert "pl_TS1dAzTQUAPVxw" not in up_to_9.text and "pl_TSNUw0LO5O98q2" not in up_to_9.text

    up_to_12 = client.get("/pay/coimbatore/standard/up-to-12")
    assert up_to_12.status_code == 200
    assert 'data-payment_button_id="pl_TSNUw0LO5O98q2"' in up_to_12.text
    assert "pl_TS1dAzTQUAPVxw" not in up_to_12.text and "pl_TSNThxqzu3nPp5" not in up_to_12.text


def test_booking_ref_is_optional_validated_and_not_injected():
    valid = client.get("/pay/coimbatore/standard?booking_ref=CBE-PTN-A82K5M")
    assert "Booking Reference: CBE-PTN-A82K5M" in valid.text
    malicious = client.get("/pay/coimbatore/standard", params={"booking_ref": "<script>alert(1)</script>"})
    assert "alert(1)" not in malicious.text
    assert malicious.text.count("<script") == 1  # Only the fixed Razorpay embed.


def test_public_base_url_and_unknown_package_are_safe():
    assert payment_page_url("https://book.entartica.test/", STANDARD_PACKAGE_ID) == "https://book.entartica.test/pay/coimbatore/standard"
    assert payment_page_url("https://book.entartica.test", COUPLE_PACKAGE_ID) == "https://book.entartica.test/pay/coimbatore/couple-romance"
    assert payment_page_url("http://book.entartica.test", STANDARD_PACKAGE_ID) is None
    assert payment_page_url("https://book.entartica.test", "unknown") is None
    assert payment_page_url("https://book.entartica.test", STANDARD_PACKAGE_ID, pricing_slab="up_to_9",
                            payment_destination_configured=False) is None


def test_standard_book_now_notifies_sales_without_sending_payment_link():
    result = handle_action("coimbatore_pontoon_book_standard", _context(STANDARD_PACKAGE_ID), public_base_url="https://book.entartica.test/")
    assert "sales team has been notified" in result.draft_text
    assert "Payment will be coordinated directly with our team outside WhatsApp" in result.draft_text
    assert "http" not in result.draft_text and "Razorpay" not in result.draft_text
    assert result.context.sales_stage == SalesStage.HANDOVER
    assert result.human_handover_required is True
    assert result.safe_metadata["handover_reason"] == "customer_requested_booking"
    draft = {"draft_status":"pending_review", "sent_at":None, "external_message_id":None}
    settings = SimpleNamespace(raipur_automatic_reply_enabled=True, exotel_outbound_enabled=True,
                               raipur_approved_draft_send_enabled=True, raipur_automatic_reply_intents=("information",))
    assert eligible_for_automatic_reply(settings, result, draft) == (True, "eligible")


def test_couple_book_now_notifies_sales_without_sending_payment_link():
    result = handle_action("coimbatore_pontoon_book_standard", _context(COUPLE_PACKAGE_ID), public_base_url="https://book.entartica.test")
    assert "sales team has been notified" in result.draft_text
    assert "http" not in result.draft_text and "Razorpay" not in result.draft_text
    assert result.context.sales_stage == SalesStage.HANDOVER
    assert result.safe_metadata["package_id"] == COUPLE_PACKAGE_ID


def test_sales_and_customize_actions_send_professional_customer_acknowledgements():
    context = _context(STANDARD_PACKAGE_ID)

    sales = handle_action("coimbatore_pontoon_talk_sales", context)
    assert "sales specialist has been notified" in sales.draft_text
    assert "package details, availability, and the next steps" in sales.draft_text
    assert sales.human_handover_required is True

    customize = handle_action("coimbatore_pontoon_customize", context)
    assert "sales team has been notified" in customize.draft_text
    assert "decoration, cake, music" in customize.draft_text
    assert customize.human_handover_required is True


def test_book_now_with_unknown_package_never_receives_a_payment_url():
    result = handle_action("coimbatore_pontoon_book_standard", _context("unknown"), public_base_url="https://book.entartica.test")
    assert "https://" not in result.draft_text
    assert result.safe_metadata["payment_handled_outside_whatsapp"] is True


@pytest.mark.parametrize(("guests", "slab", "amount"), ((8, "up_to_9", 6375), (10, "up_to_12", 7650)))
def test_higher_slab_book_now_never_uses_up_to_6_payment_destination(guests, slab, amount):
    result = handle_action("coimbatore_pontoon_book_standard", _context(STANDARD_PACKAGE_ID, guests),
                           public_base_url="https://book.entartica.test")
    assert "https://" not in result.draft_text and "/pay/coimbatore/standard" not in result.draft_text
    assert result.safe_metadata["handover_context"]["pricing_slab"] == slab
    assert result.safe_metadata["handover_context"]["offer_price"] == amount


def test_configured_higher_slab_still_keeps_payment_outside_whatsapp():
    result = handle_action("coimbatore_pontoon_book_standard", _context(STANDARD_PACKAGE_ID, 8),
                           public_base_url="https://book.entartica.test",
                           standard_up_to_9_payment_configured=True)
    assert "http" not in result.draft_text and "Razorpay" not in result.draft_text
    assert result.safe_metadata["handover_context"]["offer_price"] == 6375


@pytest.mark.parametrize(("guests", "slab", "offer"), (
    (4, "up_to_6", 5100), (8, "up_to_9", 6375), (10, "up_to_12", 7650),
))
def test_standard_actions_and_photo_continuation_preserve_pricing_context(guests, slab, offer):
    context = _context(STANDARD_PACKAGE_ID, guests)
    photos = handle_action("coimbatore_pontoon_more_photos", context)
    assert photos.safe_metadata["package_id"] == STANDARD_PACKAGE_ID
    assert photos.context.details.total_guests == guests
    assert [item["title"] for item in photos.safe_metadata["interactive_message"]["options"]] == [
        "Book Now", "Customize", "Talk to Sales Person",
    ]
    question = handle_action("coimbatore_pontoon_ask_question", photos.context)
    assert question.context.details.total_guests == guests
    customized = handle_action("coimbatore_pontoon_customize", photos.context)
    assert customized.safe_metadata["handover_context"]["pricing_slab"] == slab
    assert customized.safe_metadata["handover_context"]["offer_price"] == offer
    booked = handle_action("coimbatore_pontoon_book_standard", photos.context,
                           public_base_url="https://book.entartica.test")
    assert booked.safe_metadata["handover_context"]["pricing_slab"] == slab
    assert booked.safe_metadata["handover_context"]["offer_price"] == offer
    assert booked.context.form_values["active_package_id"] == STANDARD_PACKAGE_ID
