from datetime import date
from types import SimpleNamespace
import pytest

from app.services.booking_enquiries import BookingDetails
from app.services.coimbatore.pontoon_package import (
    MASTER_KB,
    action_id, action_message, is_package_request, load_couple_package, load_standard_package, package_request_id,
    render_package, resolve_s3_image_url, resolve_standard_package_pricing,
)
from app.services.raipur.response_models import ConversationContext


def test_master_knowledge_path_matches_tracked_linux_casing():
    assert MASTER_KB.parts[-4:] == (
        "documents", "Coimbatore", "active", "COIMBATORE_KNOWLEDGE_BASE.md",
    )
    assert MASTER_KB.is_file()


def test_approved_kb_and_yaml_load_without_raipur_facts():
    package = load_standard_package()
    assert package.package_id == "coimbatore_pontoon_standard"
    assert package.media_asset == "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/pontoon_boat_celebration_Coimbtore.jpg"
    assert package.inclusions == (
        "Red Carpet Welcome", "02 Cold Pyro Entry", "Cake", "Music Setup", "Decoration",
        "Cake cutting in the middle of the serene lake", "30 Minutes Premium Boat Ride",
    )
    assert (package.rack_rate, package.offer_rate, package.token_amount) == ("₹5,999", "₹5,100/- (15% OFF) including GST", "")
    assert package.offer_note == "Rates are valid for today."
    assert package.refund_rule == "Full refund if cancelled before 24 hours of the event date."
    assert package.add_ons == ()
    assert [item.id for item in package.actions] == [
        "coimbatore_pontoon_book_standard", "coimbatore_pontoon_talk_sales",
        "coimbatore_pontoon_customize", "coimbatore_pontoon_more_photos",
        "coimbatore_pontoon_brochure",
        "coimbatore_pontoon_check_couple",
    ]
    assert [item.title for item in package.actions] == [
        "Book Now", "Talk to Sales Person", "Customize", "See Photo & Video",
        "See Pontoon Brochure", "Check Couple Package",
    ]


def test_render_uses_dynamic_values_and_never_internal_uri():
    text = render_package(load_standard_package(), date(2026, 8, 30), 5)
    assert "Event Date: 30 Aug 2026" in text and "Guests: 5" in text
    assert "02 or 04 or 05 persons" not in text and "s3://" not in text
    assert text.startswith("Thank you for sharing your details 😊\nHere is the package for your Pontoon Boat Celebration.")
    assert all(value in text for value in (
        "💰 Special Offer", "~₹5,999/-~", "₹5,100/- (15% OFF) including GST",
        "30 Minutes Premium Boat Ride",
    ))
    assert "₹4,999" not in text and "token of ₹1,000" not in text and "Rack Rate" not in text
    assert "APPROVED ADD-ONS" not in text and "Pyro Gun" not in text
    incomplete = render_package(load_standard_package(), None, None)
    assert "Event Date:" not in incomplete and "Guests:" not in incomplete
    assert "Full refund if cancelled before 24 hours" in incomplete
    assert "Special Offer" not in incomplete and "₹5,100" not in incomplete


@pytest.mark.parametrize(("guests", "slab", "regular", "offer", "paise"), (
    (1, "up_to_6", 5999, 5100, 510000), (6, "up_to_6", 5999, 5100, 510000),
    (7, "up_to_9", 7500, 6375, 637500), (9, "up_to_9", 7500, 6375, 637500),
    (10, "up_to_12", 9000, 7650, 765000),
))
def test_standard_pricing_boundaries(guests, slab, regular, offer, paise):
    pricing = resolve_standard_package_pricing(guests)
    assert pricing is not None
    assert (pricing.slab_id, pricing.regular_price, pricing.offer_price, pricing.offer_price_paise) == (slab, regular, offer, paise)


@pytest.mark.parametrize("guests", (None, 0, -1, 11, 12, 13, 25))
def test_standard_pricing_never_defaults_invalid_or_custom_counts(guests):
    assert resolve_standard_package_pricing(guests) is None


@pytest.mark.parametrize(("guests", "regular", "offer"), (
    (4, "~₹5,999/-~", "₹5,100/- (15% OFF) including GST"),
    (8, "~₹7,500/-~", "₹6,375/- (15% OFF) including GST"),
    (10, "~₹9,000/-~", "₹7,650/- (15% OFF) including GST"),
))
def test_standard_package_renders_only_resolved_slab_price(guests, regular, offer):
    text = render_package(load_standard_package(), date(2026, 8, 30), guests)
    assert text.startswith("Thank you for sharing your details 😊")
    assert f"Guests: {guests}" in text and regular in text and offer in text


@pytest.mark.parametrize(("package_kind", "guests"), (
    ("couple", 2),
    ("standard", 5),
    ("standard", 8),
    ("standard", 10),
))
def test_all_four_customer_package_variants_have_three_working_sales_buttons(package_kind, guests):
    package = load_couple_package() if package_kind == "couple" else load_standard_package()
    message = action_message(package, body=render_package(package, date(2027, 9, 30), guests))

    assert message.kind == "buttons"
    assert [(option.id, option.title) for option in message.options] == [
        ("coimbatore_pontoon_book_standard", "Book Now"),
        ("coimbatore_pontoon_customize", "Customize"),
        ("coimbatore_pontoon_talk_sales", "Talk to Sales Person"),
    ]


def test_typed_and_stable_actions_are_deterministic():
    assert action_id("I want this") == "coimbatore_pontoon_book_standard"
    assert action_id("special request") == "coimbatore_pontoon_customize"
    assert action_id("show more photos") == "coimbatore_pontoon_more_photos"
    assert action_id("See Pontoon Brochure") == "coimbatore_pontoon_brochure"
    assert action_id("send pontoon boat celebration brochure") == "coimbatore_pontoon_brochure"
    assert action_id("coimbatore_pontoon_book_standard") == "coimbatore_pontoon_book_standard"
    assert action_id("Ask a Question") == "coimbatore_pontoon_ask_question"
    assert action_id("Talk to Sales Person") == "coimbatore_pontoon_talk_sales"
    assert action_id("Check Couple Package") == "coimbatore_pontoon_check_couple"
    assert is_package_request("what is standard package")
    assert is_package_request("send package")


def test_approved_https_media_needs_no_aws_credentials():
    settings = SimpleNamespace(aws_access_key_id=None, aws_secret_access_key=None)
    assert resolve_s3_image_url(load_standard_package().media_asset, settings) == load_standard_package().media_asset




def test_exact_couple_kb_block_and_request_resolution():
    package = load_couple_package()
    assert package.package_id == "coimbatore_pontoon_couple_romance"
    assert package.fixed_guest_count == 2
    assert package.media_asset == ""
    assert package.add_ons == ()
    assert package.actions[-1].id == "coimbatore_pontoon_check_standard"
    assert package.actions[-1].title == "Check Standard Package"
    text = render_package(package, date(2026, 8, 30), 99)
    assert all(value in text for value in ("Event Date: 30 Aug 2026", "Guests: 2", "~₹3,999/-~", "₹3,400/- (15% off) including GST", "20 Minutes Private Pontoon Boat Ride"))
    assert package_request_id("₹3999 package") == "coimbatore_pontoon_couple_romance"
    assert package_request_id("₹5999 package") == "coimbatore_pontoon_standard"
    assert package_request_id("package") == "choice"
