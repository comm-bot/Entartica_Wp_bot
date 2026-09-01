from dataclasses import replace
from datetime import date

from app.services.booking_enquiries import BookingDetails
from app.services.coimbatore.pontoon_qualification import FIRST_MESSAGE, qualify
from app.services.raipur.response_models import ConversationContext
from app.services.raipur.sales_state import SalesStage
from app.services.raipur_inbound_orchestrator import _context_from_record, _context_to_record


TODAY = date(2026, 8, 19)


def context() -> ConversationContext:
    return ConversationContext(
        BookingDetails(None, None, None, None, None, None, None),
        selected_location="coimbatore",
    )


def test_fresh_customer_gets_only_coimbatore_pontoon_first_message():
    result = qualify("hello", context(), today=TODAY)
    assert result.draft_text == FIRST_MESSAGE
    assert result.context.selected_location == "coimbatore"
    assert result.context.last_service_code == "pontoon_celebration"
    assert result.context.sales_stage == SalesStage.LEAD
    assert "Raipur" not in result.draft_text
    assert "selector" not in result.safe_metadata


def test_combined_date_and_guests_qualifies():
    result = qualify("25 August, 6 people", context(), today=TODAY)
    assert result.context.details.preferred_date == date(2026, 8, 25)
    assert result.context.details.total_guests == 6
    assert result.context.sales_stage == SalesStage.QUALIFIED
    assert result.draft_text == "Great 🎉 I have your celebration date and number of guests."


def test_prompt_example_extracts_both_fields_without_reasking():
    assert FIRST_MESSAGE.endswith("💡 eg. 7 , 26/08/2026")
    assert "planning for?\n\n💡 eg." in FIRST_MESSAGE

    result = qualify("7 , 26/08/2026", context(), today=TODAY)

    assert result.context.details.total_guests == 7
    assert result.context.details.preferred_date == date(2026, 8, 26)
    assert result.context.pending_field is None
    assert "How many guests" not in result.draft_text
    assert "share your celebration date" not in result.draft_text


def test_combined_date_and_guests_accepts_comma_or_period_separator():
    for message in ("8, 25/08/2026", "8 . 25/08/2026"):
        result = qualify(message, context(), today=TODAY)
        assert result.context.details.total_guests == 8
        assert result.context.details.preferred_date == date(2026, 8, 25)
        assert result.context.pending_field is None
        assert result.draft_text == "Great 🎉 I have your celebration date and number of guests."


def test_guest_then_month_first_date_formats_extract_both_fields():
    for message, guests, planned in (
        ("8 , oct 5", 8, date(2026, 10, 5)),
        ("9 , sept 6", 9, date(2026, 9, 6)),
    ):
        result = qualify(message, context(), today=TODAY)
        assert result.context.details.total_guests == guests
        assert result.context.details.preferred_date == planned
        assert result.context.pending_field is None


def test_natural_combined_date_and_guest_response_extracts_both_exactly():
    for message in (
        "15 Sept, 4 people",
        "4 people, 15 Sept",
        "15 sept and 4 guests",
    ):
        result = qualify(message, context(), today=TODAY)
        assert result.context.details.total_guests == 4
        assert result.context.details.preferred_date == date(2026, 9, 15)
        assert result.context.pending_field is None


def test_guest_and_date_can_arrive_in_two_messages():
    guests = qualify("8", replace(context(), pending_field="total_guests"), today=TODAY)
    assert guests.context.details.total_guests == 8
    assert guests.context.pending_field == "preferred_date"

    completed = qualify("oct 5", guests.context, today=TODAY)
    assert completed.context.details.total_guests == 8
    assert completed.context.details.preferred_date == date(2026, 10, 5)
    assert completed.context.pending_field is None


def test_pending_bare_over_capacity_guest_is_retained_for_capacity_prompt():
    waiting = qualify("5 October", context(), today=TODAY).context
    assert waiting.pending_field == "total_guests"

    result = qualify("25", waiting, today=TODAY)

    assert result.context.details.total_guests == 25
    assert result.context.details.preferred_date == date(2026, 10, 5)
    # The qualification result is complete; the orchestrator then detects the
    # capacity violation and resets this to total_guests for correction.
    assert result.context.pending_field is None


def test_over_capacity_bare_number_can_be_corrected_without_losing_date():
    mistaken = qualify("25 people, oct 5", context(), today=TODAY)
    assert mistaken.context.details.total_guests == 25
    corrected = qualify("8", mistaken.context, today=TODAY)
    assert corrected.context.details.total_guests == 8
    assert corrected.context.details.preferred_date == date(2026, 10, 5)


def test_date_only_asks_only_guests():
    result = qualify("25 August", context(), today=TODAY)
    assert result.context.details.preferred_date == date(2026, 8, 25)
    assert result.context.details.total_guests is None
    assert result.draft_text == "How many guests will be joining? 👥"


def test_guests_only_asks_only_date_and_supports_bare_number():
    for message in ("6 people", "we are 6", "hum 6 log hai", "6"):
        result = qualify(message, context(), today=TODAY)
        assert result.context.details.total_guests == 6
        assert result.context.details.preferred_date is None
        assert result.draft_text == "Please share your celebration date 📅"


def test_state_round_trip_survives_later_turn(monkeypatch):
    qualified = qualify("25 August, 6 people", context(), today=TODAY).context
    record = _context_to_record(qualified)
    monkeypatch.setitem(record, "updated_at", "2099-01-01T00:00:00+00:00")
    restored, expired = _context_from_record(record, 120)
    assert not expired
    later = qualify("what happens next?", restored, today=TODAY)
    assert later.context.details.preferred_date == date(2026, 8, 25)
    assert later.context.details.total_guests == 6
    assert later.draft_text == "Great 🎉 I have your celebration date and number of guests."


def test_explicit_guest_and_date_corrections_preserve_other_field():
    current = qualify("25 August, 6 people", context(), today=TODAY).context
    guests = qualify("actually 8 people", current, today=TODAY).context
    assert guests.details.total_guests == 8
    assert guests.details.preferred_date == date(2026, 8, 25)
    changed = qualify("change date to 27 August", guests, today=TODAY).context
    assert changed.details.preferred_date == date(2026, 8, 27)
    assert changed.details.total_guests == 8


def test_past_date_rejected_but_valid_guests_retained():
    result = qualify("10 August, 6 people", context(), today=TODAY)
    assert result.context.details.preferred_date is None
    assert result.context.details.total_guests == 6
    assert "future date" in result.draft_text
    assert result.context.sales_stage == SalesStage.LEAD


def test_supported_natural_dates():
    expected = date(2026, 8, 25)
    for message in ("25 Aug", "25/08/2026", "25-08-2026", "25 August 2026", "25 aug ko"):
        assert qualify(message, context(), today=TODAY).context.details.preferred_date == expected
    assert qualify("tomorrow", context(), today=TODAY).context.details.preferred_date == date(2026, 8, 20)
    assert qualify("this Sunday", context(), today=TODAY).context.details.preferred_date == date(2026, 8, 23)
