"""Post-persistence, non-sending Raipur orchestration for eligible inbound text."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import logging
from typing import Any

from app.repositories.booking_enquiries import BookingEnquiryRepository
from app.repositories.locations import LocationRepository
from app.repositories.services import ServiceRepository
from app.repositories.conversations import ConversationRepository
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_availability_provider import build_raipur_availability_provider
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService, _language
from app.services.raipur_services import approved_service_from_message
from app.services.raipur_conversational_fallback import build_raipur_conversational_fallback
from app.services.raipur_sales_contact import SalesContact
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


logger = logging.getLogger("uvicorn.error")


class _NoDrafts:
    def create_outbound_draft(self, **_: Any):
        return {}, False


class _SafeKnowledge:
    def answer(self, _: str) -> KnowledgeDraft:
        return KnowledgeDraft(None)


class RaipurInboundOrchestrator:
    def __init__(self, client: Any, settings: Any, knowledge_provider: Any = None):
        self._location = LocationRepository(client).get_location_by_code("raipur")
        availability_provider = build_raipur_availability_provider(settings, client=client)
        services = ServiceRepository(client)
        bookings = BookingEnquiryService(
            BookingEnquiryRepository(client), availability_provider, services
        )
        self._conversation = RaipurConversationService(
            knowledge=knowledge_provider or _SafeKnowledge(),
            bookings=bookings,
            drafts=_NoDrafts(),
            services=services,
            location=self._location,
            persist_drafts=False,
            timezone_name=settings.app_timezone,
            conversational_fallback=build_raipur_conversational_fallback(settings),
            sales_contact=SalesContact.from_settings(settings),
        )
        self._contexts = ConversationRepository(client)
        self._langgraph_enabled = bool(getattr(settings, "raipur_langgraph_enabled", False))
        self._router_revision = str(getattr(settings, "router_revision", "local"))
        self._langgraph = RaipurLangGraphWorkflow(
            self._conversation, knowledge=knowledge_provider or _SafeKnowledge(), services=services,
            location=self._location, sales_contact=SalesContact.from_settings(settings),
        ) if self._langgraph_enabled else None
        self._context_ttl_minutes = max(1, int(getattr(settings, "raipur_conversation_context_ttl_minutes", 120)))
        self._session_ttl_minutes = max(1, int(getattr(settings, "conversation_session_ttl_minutes", 30)))

    def process(
        self,
        message: Any,
        *,
        customer: dict[str, Any],
        conversation: dict[str, Any],
        source_message_id: str,
        current_state: Any = None,
    ):
        if not isinstance(self._location, dict) or not isinstance(self._location.get("id"), str):
            raise RuntimeError("raipur_location_missing")
        scoped = dict(conversation)
        scoped["location_id"] = self._location["id"]
        customer_id, conversation_id = customer.get("id"), scoped.get("id")
        stored = None
        if current_state is None and isinstance(customer_id, str) and isinstance(conversation_id, str):
            try:
                stored = self._contexts.get_service_context(conversation_id, customer_id)
            except Exception:
                # A context read failure must never leak another conversation's state.
                stored = None
        state, expired = _context_from_record(
            current_state if current_state is not None else stored or scoped.get("service_context"),
            self._context_ttl_minutes,
        )
        if current_state is None and _is_stale_greeting(stored, getattr(message, "content", ""), self._session_ttl_minutes):
            state, expired = None, True
        previous_service = state.last_service_name if state is not None else None
        if self._langgraph is None:
            result = self._conversation.process(
                message, customer=customer, conversation=scoped,
                source_message_id=source_message_id, current_state=state,
            )
        else:
            content = getattr(message, "content", "")
            result = self._langgraph.invoke(
                {
                    "message_id": source_message_id,
                    "conversation_id": conversation_id if isinstance(conversation_id, str) else "",
                    "customer_id": customer_id if isinstance(customer_id, str) else "",
                    "customer_message": content if isinstance(content, str) else "",
                    "normalized_message": content.casefold().strip() if isinstance(content, str) else "",
                    "language": _language(content) if isinstance(content, str) else "en",
                    "location_code": "raipur", "previous_service_code": getattr(state, "last_service_code", None),
                    "previous_topic": getattr(state, "active_topic", None),
                    "intent": "unknown", "entity_type": "unknown", "service_code": None, "topic": None,
                    "use_previous_service": False, "requires_handover": False, "handover_reason": None,
                    "answer_source": "unresolved", "draft_response": None, "validation_status": "pending", "error": None, "route": "",
                },
                message=message, customer=customer, conversation=scoped,
                source_message_id=source_message_id, current_state=state,
            )
        explicit_match = approved_service_from_message(getattr(message, "content", "")) is not None
        context_used = bool(
            not explicit_match
            and state is not None
            and state.last_service_name
            and result.context is not None
            and result.context.last_service_name == state.last_service_name
        )
        metadata = dict(result.safe_metadata or {})
        metadata.update({
            "router_revision": self._router_revision,
            "langgraph_enabled": self._langgraph_enabled,
            "active_engine": "langgraph" if self._langgraph is not None else "legacy",
            "context_expired": expired,
            "explicit_service_match": explicit_match,
            "context_service_used": context_used,
            "service_switched": bool(previous_service and result.context and result.context.last_service_name and result.context.last_service_name != previous_service),
            "automatic_reply_eligible": False,
            "automatic_reply_rejection_reason": "not_evaluated",
        })
        result = replace(result, safe_metadata=metadata)
        logger.info(
            "raipur_path_selected router_revision=%s langgraph_enabled=%s active_engine=%s "
            "message_id=%s normalized_message=%s selected_route=%s intent=%s service_code=%s topic=%s "
            "used_previous_service=%s answer_source=%s source_filename=%s automatic_reply_eligible=%s "
            "automatic_reply_rejection_reason=%s",
            self._router_revision,
            self._langgraph_enabled,
            metadata["active_engine"],
            source_message_id,
            getattr(message, "content", "").casefold().strip() if isinstance(getattr(message, "content", None), str) else "",
            metadata.get("graph_answer_source", result.reason_code),
            result.detected_intent,
            metadata.get("service_code") if isinstance(metadata, dict) and "service_code" in metadata else getattr(result.context, "last_service_code", None) or "none",
            metadata.get("topic") if isinstance(metadata, dict) and "topic" in metadata else getattr(result.context, "active_topic", None) or "none",
            metadata.get("context_service_used", False),
            metadata.get("answer_source", "none"),
            metadata.get("source_filename", "none"),
            False,
            "not_evaluated",
        )
        if isinstance(customer_id, str) and isinstance(conversation_id, str) and result.context is not None:
            try:
                self._contexts.save_service_context(conversation_id, customer_id, _context_to_record(result.context))
            except Exception:
                # The reply remains safe, but the next message will ask for clarification.
                pass
        return result


def _context_from_record(value: Any, ttl_minutes: int) -> tuple[Any, bool]:
    """Deserialize only structured service context, enforcing its TTL."""

    if value is None:
        return None, False
    if not isinstance(value, dict):
        return None, True
    updated = value.get("updated_at", value.get("context_updated_at"))
    if not isinstance(updated, str):
        return None, True
    try:
        stamp = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None, True
    except ValueError:
        return None, True
    if stamp.astimezone(timezone.utc) < datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes):
        return None, True
    service_name = value.get("service_name", value.get("last_matched_service_name"))
    service_code = value.get("service_code", value.get("last_matched_service_code"))
    has_service = isinstance(service_name, str) and service_name.strip() and isinstance(service_code, str) and service_code.strip()
    has_topic = isinstance(value.get("active_domain"), str) or bool(value.get("pending_clarification"))
    if not has_service and not has_topic:
        return None, False
    from app.services.booking_enquiries import BookingDetails
    from app.services.raipur_conversation import ConversationContext
    details_record = value.get("booking_details") if isinstance(value.get("booking_details"), dict) else {}
    requested_service_text = _optional_text(details_record.get("requested_service_text"))
    if requested_service_text is None and has_service:
        requested_service_text = service_name
    return ConversationContext(
        details=BookingDetails(
            _optional_text(details_record.get("customer_name")),
            requested_service_text,
            _parse_date(details_record.get("preferred_date")),
            _parse_time(details_record.get("preferred_time")),
            _optional_nonnegative_int(details_record.get("adults_count")),
            _optional_nonnegative_int(details_record.get("children_count")),
            _optional_nonnegative_int(details_record.get("total_guests")),
            special_requirements=_optional_text(details_record.get("special_requirements")),
            special_requirements_collected=bool(details_record.get("special_requirements_collected", False)),
            requested_service_id=_optional_text(details_record.get("requested_service_id")),
        ),
        pending_field=_optional_text(value.get("pending_field")),
        availability_requested=bool(value.get("availability_requested")),
        last_service_name=service_name if has_service else None,
        last_service_code=service_code if has_service else None,
        last_intent=value.get("last_intent", value.get("intent", value.get("last_detected_intent"))) if isinstance(value.get("last_intent", value.get("intent", value.get("last_detected_intent"))), str) else None,
        last_bot_action=value.get("last_bot_action") if isinstance(value.get("last_bot_action"), str) else None,
        service_selection_prompted=bool(value.get("awaiting_service_selection")),
        service_details_requested=bool(value.get("service_details_requested")),
        active_domain=value.get("active_domain") if isinstance(value.get("active_domain"), str) else "entartica",
        active_topic=value.get("active_topic") if isinstance(value.get("active_topic"), str) else None,
        active_entity_type=value.get("active_entity_type") if isinstance(value.get("active_entity_type"), str) else None,
        active_entity_name=value.get("active_entity_name") if isinstance(value.get("active_entity_name"), str) else None,
        last_user_intent=value.get("last_user_intent") if isinstance(value.get("last_user_intent"), str) else None,
        last_assistant_answer_summary=value.get("last_assistant_answer_summary") if isinstance(value.get("last_assistant_answer_summary"), str) else None,
        pending_clarification=bool(value.get("pending_clarification")),
        pending_clarification_type=value.get("pending_clarification_type") if isinstance(value.get("pending_clarification_type"), str) else None,
        pending_clarification_options=tuple(item for item in value.get("pending_clarification_options", ()) if isinstance(item, str)) if isinstance(value.get("pending_clarification_options", ()), (list, tuple)) else (),
        preferred_language=value.get("preferred_language") if isinstance(value.get("preferred_language"), str) else None,
        last_assistant_question=value.get("last_assistant_question") if isinstance(value.get("last_assistant_question"), str) else None,
        pending_question_type=value.get("pending_question_type") if isinstance(value.get("pending_question_type"), str) else None,
        pending_action=value.get("pending_action") if isinstance(value.get("pending_action"), str) else None,
        pending_entity_type=value.get("pending_entity_type") if isinstance(value.get("pending_entity_type"), str) else None,
        pending_entity_name=value.get("pending_entity_name") if isinstance(value.get("pending_entity_name"), str) else None,
        pending_created_at=value.get("pending_created_at") if isinstance(value.get("pending_created_at"), str) else None,
        pending_service_code=value.get("pending_service_code") if isinstance(value.get("pending_service_code"), str) else None,
        pending_slots=value.get("pending_slots") if isinstance(value.get("pending_slots"), dict) else None,
        last_answer_source=_optional_text(value.get("last_answer_source")),
        last_answer_sections=tuple(item for item in value.get("last_answer_sections", ()) if isinstance(item, str) and item.strip()) if isinstance(value.get("last_answer_sections", ()), (list, tuple)) else (),
    ), False


def _context_to_record(context: Any) -> dict[str, Any]:
    """Serialize the structured conversation state needed for the next inbound turn."""

    details = context.details
    return {
        "location_code": "raipur",
        "service_code": context.last_service_code,
        "previous_service_code": context.last_service_code,
        "previous_topic": context.active_topic,
        "last_answer_source": context.last_answer_source,
        "last_answer_sections": list(context.last_answer_sections),
        "service_name": context.last_service_name,
        "last_intent": context.last_intent,
        "last_bot_action": context.last_bot_action,
        "awaiting_service_selection": context.service_selection_prompted,
        "active_domain": context.active_domain,
        "active_topic": context.active_topic,
        "active_entity_type": context.active_entity_type,
        "active_entity_name": context.active_entity_name,
        "last_user_intent": context.last_user_intent,
        "last_assistant_answer_summary": context.last_assistant_answer_summary,
        "pending_clarification": context.pending_clarification,
        "pending_clarification_type": context.pending_clarification_type,
        "pending_clarification_options": list(context.pending_clarification_options),
        "preferred_language": context.preferred_language,
        "last_assistant_question": context.last_assistant_question,
        "pending_question_type": context.pending_question_type,
        "pending_action": context.pending_action,
        "pending_entity_type": context.pending_entity_type,
        "pending_entity_name": context.pending_entity_name,
        "pending_created_at": context.pending_created_at,
        "pending_service_code": context.pending_service_code,
        "pending_slots": context.pending_slots,
        "pending_field": context.pending_field,
        "availability_requested": context.availability_requested,
        "service_details_requested": context.service_details_requested,
        "booking_details": {
            "customer_name": details.customer_name,
            "requested_service_text": details.requested_service_text,
            "requested_service_id": details.requested_service_id,
            "preferred_date": details.preferred_date.isoformat() if details.preferred_date else None,
            "preferred_time": details.preferred_time.isoformat() if details.preferred_time else None,
            "adults_count": details.adults_count,
            "children_count": details.children_count,
            "total_guests": details.total_guests,
            "special_requirements": details.special_requirements,
            "special_requirements_collected": details.special_requirements_collected,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_time(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def _is_stale_greeting(record: Any, content: Any, ttl_minutes: int) -> bool:
    if not isinstance(record, dict) or not isinstance(content, str) or content.strip().casefold() not in {"hi", "hii", "hello", "hey", "namaste"}:
        return False
    updated = record.get("updated_at")
    if not isinstance(updated, str): return False
    try:
        stamp = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        return stamp.tzinfo is not None and stamp.astimezone(timezone.utc) < datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
    except ValueError:
        return False
