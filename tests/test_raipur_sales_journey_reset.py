"""Focused regressions for controlled celebration sales-journey resets."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.services.booking_enquiries import BookingDetails
from app.services.raipur.context_state import reset_for_new_celebration_journey
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
from app.services.raipur.sales_state import SalesStage
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"name": item.name, "is_active": True} for item in APPROVED_RAIPUR_SERVICES]


class _Knowledge:
    def answer_service_details(self, _question, service_name, service_code, **_kwargs):
        return KnowledgeDraft(f"{service_name} has approved service details.", f"{service_code}.md", .9, False, "Overview", 1, service_code, ("Overview",))


def _state(message):
    return {"message_id":"m","conversation_id":"c","customer_id":"u","customer_message":message,"normalized_message":message.casefold(),"language":"en","location_code":"raipur","previous_service_code":None,"previous_topic":None,"intent":None,"entity_type":"unknown","service_code":None,"topic":None,"use_previous_service":False,"requires_handover":False,"handover_reason":None,"selected_route":None,"answer_source":None,"validation_errors":[],"plan_consistency_repaired":False,"invocation_id":"i","draft_response":None,"validation_status":"pending","error":None,"route":None}


def _turn(message, context):
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(), services=_Services())
    return workflow.invoke(_state(message), message=SimpleNamespace(content=message), customer={"id":"u"}, conversation={"id":"c","location_id":"raipur"}, source_message_id="m", current_state=context)


def _old_context(**changes):
    context = ConversationContext(
        BookingDetails("Customer", "Houseboat Celebration", date(2026, 8, 13), None, None, None, 23, "cake", True),
        pending_field=None,
        active_topic="celebration_catalogue",
        active_entity_type="catalogue",
        active_entity_name="celebration",
        pending_action="celebration_sales",
        pending_slots={"occasion":"birthday", "celebration_preference":"private_intimate", "preference":"private_intimate", "pontoon_media_sent":"true"},
        preferred_language="en",
        sales_stage=SalesStage.QUALIFIED,
    )
    return context.__class__(**{**context.__dict__, **changes})


def test_qualified_old_celebration_top_level_request_starts_fresh_journey():
    result = _turn("I want to celebrate", _old_context())
    assert result.detected_intent == "celebration_service_list"
    assert result.context.details.total_guests is None
    assert result.context.details.preferred_date is None
    assert result.context.pending_slots is None
    assert result.context.pending_field == "total_guests"


def test_intervening_staycation_does_not_leak_into_fresh_celebration():
    stale = _old_context(active_topic="package_catalogue", active_entity_name="package")
    stale = stale.__class__(**{**stale.__dict__, "details": BookingDetails("Customer", "Staycation Package", date(2026, 8, 13), None, None, None, 23)})
    result = _turn("mujhe celebration karna hai", stale)
    assert result.context.details.requested_service_text is None
    assert result.context.details.total_guests is None
    assert result.context.details.preferred_date is None
    assert result.context.active_entity_name == "celebration"


def test_handover_then_clearly_new_celebration_starts_fresh():
    result = _turn("new celebration", _old_context(sales_stage=SalesStage.HANDOVER))
    assert result.context.details.total_guests is None
    assert result.context.details.preferred_date is None
    assert result.context.sales_stage is SalesStage.QUALIFYING


@pytest.mark.parametrize("message", ["tell me more", "Party Boat duration?"])
def test_contextual_followups_do_not_reset_active_celebration(message):
    result = _turn(message, _old_context(sales_stage=SalesStage.QUALIFYING))
    assert result.context.details.total_guests == 23
    assert result.context.details.preferred_date == date(2026, 8, 13)


def test_guest_answer_preserves_active_journey():
    active = _old_context(
        sales_stage=SalesStage.QUALIFYING,
        pending_field="total_guests",
        pending_question_type="sales_guest_count",
    )
    result = _turn("12", active)
    assert result.context.details.total_guests == 12
    assert result.context.details.preferred_date == date(2026, 8, 13)


def test_date_answer_preserves_guest_count():
    active = _old_context(
        sales_stage=SalesStage.QUALIFYING,
        pending_field="preferred_date",
        pending_question_type="sales_planned_date",
    )
    result = _turn("13 August", active)
    assert result.context.details.total_guests == 23
    assert result.context.details.preferred_date is not None


def test_reset_preserves_durable_customer_information_only():
    reset = reset_for_new_celebration_journey(_old_context())
    assert reset.details.customer_name == "Customer"
    assert reset.preferred_language == "en"
    assert reset.active_domain == "entartica"
    assert reset.details.requested_service_text is None
    assert reset.details.special_requirements is None
    assert reset.pending_slots is None
