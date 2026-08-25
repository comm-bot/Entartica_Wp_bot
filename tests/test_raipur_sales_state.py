"""Focused tests for the persistent, side-effect-free sales foundation."""
from dataclasses import replace
from datetime import date

from app.services.booking_enquiries import BookingDetails
from app.services.raipur.context_state import set_catalogue_context
from app.services.raipur.response_models import ConversationContext
from app.services.raipur.sales_state import (
    SalesNextAction,
    SalesStage,
    evaluate_sales_next_action,
)
from app.services.raipur_inbound_orchestrator import _context_from_record, _context_to_record


def _context(*, service: bool = False, guests: int | None = None, planned: date | None = None):
    return ConversationContext(
        BookingDetails(
            customer_name=None,
            requested_service_text="Houseboat Celebration" if service else None,
            preferred_date=planned,
            preferred_time=None,
            adults_count=None,
            children_count=None,
            total_guests=guests,
        ),
        last_service_name="Houseboat Celebration" if service else None,
        last_service_code="houseboat_celebration" if service else None,
        sales_stage=SalesStage.SERVICE_SELECTED if service else SalesStage.DISCOVERY,
    )


def test_no_commercial_context_has_no_sales_action():
    decision = evaluate_sales_next_action(_context())
    assert decision.action is SalesNextAction.NONE
    assert decision.next_stage is SalesStage.DISCOVERY


def test_celebration_options_shown_start_one_field_qualification():
    context = set_catalogue_context(_context(), "celebration").updated_context
    decision = evaluate_sales_next_action(context)
    assert context.sales_stage is SalesStage.OPTIONS_SHOWN
    assert decision.action is SalesNextAction.ASK_GUEST_COUNT
    assert decision.requested_field == "total_guests"


def test_selected_service_without_guest_count_suggests_guest_count():
    decision = evaluate_sales_next_action(_context(service=True))
    assert decision.action is SalesNextAction.ASK_GUEST_COUNT
    assert decision.requested_field == "total_guests"


def test_known_guest_count_is_not_requested_again():
    decision = evaluate_sales_next_action(_context(service=True, guests=12))
    assert decision.action is not SalesNextAction.ASK_GUEST_COUNT


def test_known_guest_count_without_date_suggests_date():
    decision = evaluate_sales_next_action(_context(service=True, guests=12))
    assert decision.action is SalesNextAction.ASK_DATE
    assert decision.requested_field == "preferred_date"


def test_minimum_qualification_suggests_controlled_handover():
    decision = evaluate_sales_next_action(
        _context(service=True, guests=12, planned=date(2026, 9, 1))
    )
    assert decision.action is SalesNextAction.HANDOVER
    assert decision.next_stage is SalesStage.QUALIFIED


def test_higher_priority_route_is_never_overridden_by_sales_state():
    context = _context(service=True)
    for intent in ("pricing", "booking", "availability", "payment", "cancellation_refund"):
        decision = evaluate_sales_next_action(context, current_intent=intent)
        assert decision.action is SalesNextAction.NONE, intent
        assert decision.reason == "higher_priority_route_owns_turn", intent


def test_sales_stage_round_trips_through_existing_persistent_context():
    context = replace(_context(service=True), sales_stage=SalesStage.QUALIFYING)
    record = _context_to_record(context)
    restored, expired = _context_from_record(record, 120)
    assert expired is False
    assert restored.sales_stage is SalesStage.QUALIFYING
    assert restored.last_service_code == "houseboat_celebration"
