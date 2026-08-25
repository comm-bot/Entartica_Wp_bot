"""Pure deterministic Raipur conversation-context decisions and mutations."""
from __future__ import annotations
from dataclasses import dataclass, replace
import re
from app.services.raipur.response_models import ConversationContext
from app.services.raipur.sales_state import SalesStage
from app.services.raipur.customer_understanding import CustomerUnderstanding, parse_planned_date_text
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, approved_service_from_message, knowledge_service_code

@dataclass(frozen=True)
class ContextResolutionResult:
    active_service_code: str | None
    active_service_name: str | None
    active_topic: str | None
    context_service_used: bool = False
    context_topic_used: bool = False
    explicit_service_switch: bool = False
    clear_service_context: bool = False
    clear_topic_context: bool = False
    updated_context: ConversationContext | None = None
    reason: str = "unchanged"


def apply_customer_understanding(
    context: ConversationContext,
    understanding: CustomerUnderstanding,
) -> ConversationContext:
    """Merge only explicit current-message facts; nulls never erase state."""
    details = context.details
    if understanding.guest_count is not None:
        details = replace(details, total_guests=understanding.guest_count)
    if understanding.adult_count is not None or understanding.child_count is not None:
        adults = understanding.adult_count if understanding.adult_count is not None else details.adults_count
        children = understanding.child_count if understanding.child_count is not None else details.children_count
        total = adults + children if adults is not None and children is not None else details.total_guests
        details = replace(details, adults_count=adults, children_count=children, total_guests=total)
    slots = dict(context.pending_slots or {})
    form_values = dict(context.form_values or {})
    if understanding.customer_location is not None:
        form_values["customer_location"] = understanding.customer_location
    if understanding.occasion is not None:
        slots["occasion"] = understanding.occasion
    if understanding.planned_date_text is not None:
        slots["planned_date_text"] = understanding.planned_date_text
        parsed = parse_planned_date_text(understanding.planned_date_text)
        if parsed is not None:
            details = replace(details, preferred_date=parsed)
    if understanding.preference is not None:
        slots["preference"] = understanding.preference
        if understanding.intent == "celebration" or context.active_entity_name == "celebration" or context.pending_action == "celebration_sales":
            slots["celebration_preference"] = understanding.preference

    updates = {"details": details, "pending_slots": slots or context.pending_slots,
               "form_values": form_values or context.form_values}
    if understanding.intent == "celebration":
        updates.update({
            "active_topic": "celebration_catalogue",
            "active_entity_type": "catalogue",
            "active_entity_name": "celebration",
            "pending_action": "celebration_sales",
            "sales_stage": SalesStage.QUALIFYING,
        })
    if understanding.service_code is not None:
        service = next(
            (item for item in APPROVED_RAIPUR_SERVICES if knowledge_service_code(item) == understanding.service_code),
            None,
        )
        if service is not None:
            updates.update({
                "last_service_code": understanding.service_code,
                "last_service_name": service.name,
                "active_entity_type": "service",
                "active_entity_name": service.name,
            })
    return replace(context, **updates)


def should_reset_for_new_celebration_journey(context: ConversationContext, text: str) -> bool:
    """Return true only for a top-level celebration request after an ended or superseded journey."""
    explicit_restart = bool(re.search(r"\b(?:new|another|start\s+over|fresh)\b", text, re.I))
    ended = context.sales_stage in {SalesStage.QUALIFIED, SalesStage.HANDOVER}
    service = approved_service_from_message(context.details.requested_service_text)
    superseded = (
        context.active_topic == "package_catalogue"
        or (context.last_service_code is not None and not any(
            knowledge_service_code(item) == context.last_service_code and item.category == "floating_celebration"
            for item in APPROVED_RAIPUR_SERVICES
        ))
        or (service is not None and service.category != "floating_celebration")
    )
    return explicit_restart or ended or superseded


def reset_for_new_celebration_journey(context: ConversationContext) -> ConversationContext:
    """Clear journey-scoped sales state while retaining durable customer context."""
    details = replace(
        context.details,
        requested_service_text=None,
        requested_service_id=None,
        preferred_date=None,
        preferred_time=None,
        adults_count=None,
        children_count=None,
        total_guests=None,
        special_requirements=None,
        special_requirements_collected=False,
    )
    return replace(
        context,
        details=details,
        pending_field=None,
        availability_requested=False,
        last_service_name=None,
        last_service_code=None,
        last_bot_action=None,
        service_selection_prompted=False,
        service_details_requested=False,
        active_topic=None,
        active_entity_type=None,
        active_entity_name=None,
        last_assistant_answer_summary=None,
        pending_clarification=False,
        pending_clarification_type=None,
        pending_clarification_options=(),
        last_assistant_question=None,
        pending_question_type=None,
        pending_action=None,
        pending_entity_type=None,
        pending_entity_name=None,
        pending_created_at=None,
        pending_service_code=None,
        pending_slots=None,
        last_answer_source=None,
        last_answer_sections=(),
        sales_stage=SalesStage.DISCOVERY,
    )

def clear_for_non_service_turn(context: ConversationContext, *, reason: str) -> ContextResolutionResult:
    """Clear the active service subject for greeting/location/category turns."""
    updated=replace(context,last_service_name=None,last_service_code=None,active_topic=None,active_entity_type=None,active_entity_name=None,service_selection_prompted=False,service_details_requested=False,pending_service_code=None)
    return ContextResolutionResult(None,None,None,clear_service_context=True,clear_topic_context=True,updated_context=updated,reason=reason)

def set_catalogue_context(context: ConversationContext, catalogue_type: str) -> ContextResolutionResult:
    """Persist an approved catalogue subject for immediate list follow-ups."""
    topics={"activity":"activity_catalogue","celebration":"celebration_catalogue","package":"package_catalogue"}
    topic=topics.get(catalogue_type)
    if topic is None:return ContextResolutionResult(None,None,None,updated_context=context,reason="invalid_catalogue")
    discovery_updates = {}
    if catalogue_type == "activity":
        # A fresh activity catalogue is the active discovery domain. Keep
        # durable customer facts, but do not let an older celebration journey
        # interpret the next short preference reply.
        discovery_updates = {
            "pending_field": None,
            "pending_question_type": None,
            "pending_action": None,
            "pending_entity_type": None,
            "pending_entity_name": None,
            "last_assistant_question": None,
        }
    updated=replace(
        context,last_service_name=None,last_service_code=None,active_topic=topic,
        active_entity_type="catalogue",active_entity_name=catalogue_type,
        service_selection_prompted=False,service_details_requested=False,pending_service_code=None,
        pending_clarification=False,pending_clarification_type=None,pending_clarification_options=(),
        sales_stage=SalesStage.OPTIONS_SHOWN,
        **discovery_updates,
    )
    return ContextResolutionResult(None,None,topic,clear_service_context=True,updated_context=updated,reason="catalogue_context")

def set_celebration_occasion_pending(context: ConversationContext) -> ContextResolutionResult:
    """Persist a pending celebration-occasion clarification so a short next
    reply (anniversary/birthday/corporate) continues the celebration flow."""
    updated=replace(
        context,last_service_name=None,last_service_code=None,
        active_topic="celebration_catalogue",active_entity_type="catalogue",active_entity_name="celebration",
        service_selection_prompted=False,service_details_requested=False,pending_service_code=None,
        pending_clarification=True,pending_clarification_type="celebration_occasion",
        pending_clarification_options=("anniversary","birthday","corporate"),
        pending_action="celebration_occasion",pending_entity_type="celebration",pending_entity_name="celebration",
    )
    return ContextResolutionResult(None,None,"celebration_catalogue",clear_service_context=True,updated_context=updated,reason="celebration_occasion_pending")

def clear_pending_celebration(context: ConversationContext, *, reason: str) -> ContextResolutionResult:
    """Clear a pending celebration occasion and any stale celebration subject."""
    updated=replace(
        context,last_service_name=None,last_service_code=None,
        active_topic=None,active_entity_type=None,active_entity_name=None,
        service_selection_prompted=False,service_details_requested=False,pending_service_code=None,
        pending_clarification=False,pending_clarification_type=None,pending_clarification_options=(),
        pending_action=None,pending_entity_type=None,pending_entity_name=None,
    )
    return ContextResolutionResult(None,None,None,clear_service_context=True,clear_topic_context=True,updated_context=updated,reason=reason)

def resolve_service_turn(context: ConversationContext, *, service_code: str | None, service_name: str | None, topic: str | None, explicit_service: bool) -> ContextResolutionResult:
    if explicit_service and service_code and service_name:
        switched=bool(context.last_service_code and context.last_service_code != service_code)
        updated=replace(context,last_service_code=service_code,last_service_name=service_name,active_topic=topic,sales_stage=SalesStage.SERVICE_SELECTED)
        return ContextResolutionResult(service_code,service_name,topic,explicit_service_switch=switched,updated_context=updated,reason="explicit_service")
    if context.last_service_code and context.last_service_name:
        updated=replace(context,active_topic=topic or context.active_topic)
        return ContextResolutionResult(context.last_service_code,context.last_service_name,updated.active_topic,context_service_used=True,context_topic_used=bool(context.active_topic),updated_context=updated,reason="stored_service")
    return ContextResolutionResult(None,None,topic,reason="no_service")
