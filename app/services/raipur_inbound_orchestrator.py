"""Post-persistence, non-sending Raipur orchestration for eligible inbound text."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import json
import logging
import re
from threading import Lock
from time import monotonic
from typing import Any

from app.repositories.booking_enquiries import BookingEnquiryRepository
from app.repositories.locations import LocationRepository
from app.repositories.services import ServiceRepository
from app.repositories.conversations import ConversationRepository
from app.services.booking_enquiries import BookingEnquiryService
from app.services.booking_enquiries import BookingDetails
from app.services.raipur_availability_provider import build_raipur_availability_provider
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
from app.services.raipur.sales_state import SalesStage
from app.services.raipur_conversation import RaipurConversationService
from app.services.raipur.language import detect_language
from app.services.raipur_services import approved_service_from_message
from app.services.raipur_conversational_fallback import build_raipur_conversational_fallback
from app.services.raipur.customer_understanding import build_customer_understanding_service
from app.services.raipur_sales_contact import SalesContact
from app.services.raipur_langgraph import RaipurLangGraphWorkflow
from app.services.raipur.sales_response_composer import build_sales_response_composer
from app.services.raipur.sales_agent import build_sales_agent
from app.services.whatsapp_response_formatter import format_whatsapp_response
from app.services.latency import current_latency_trace, latency_attribute, latency_counter, latency_stage
from app.schemas.interactive_messages import celebration_selector, configured_flow, location_selector
from app.schemas.template_messages import TemplateMessage
from app.services.raipur.interactive_journey import merge_form_response, merge_natural_visit_details, qualification_reply, requested_location, requests_location_change
from app.services.coimbatore.pontoon_qualification import is_enabled as coimbatore_pontoon_enabled, qualify as qualify_coimbatore_pontoon


logger = logging.getLogger("uvicorn.error")
_LOCATION_CACHE_TTL_SECONDS = 300
_location_cache: dict[object, tuple[float, dict[str, Any] | None]] = {}
_location_cache_lock = Lock()
_RAIPUR_QUALIFICATION_MESSAGE = """Hello, this is Chiki from Entartica SeaWorld 😊

Kindly share a few details so I can assist you better:

• Which date are you planning for?
• How many persons are going to attend?
• Which location are you coming from?"""


def _cached_raipur_location(client: Any) -> dict[str, Any] | None:
    key, now = client, monotonic()
    with _location_cache_lock:
        cached = _location_cache.get(key)
        if cached is not None and cached[0] > now:
            latency_attribute("location_cache_hit", True)
            return cached[1]
    latency_attribute("location_cache_hit", False)
    location = LocationRepository(client).get_location_by_code("raipur")
    with _location_cache_lock:
        _location_cache[key] = (now + _LOCATION_CACHE_TTL_SECONDS, location)
    return location


class _NoDrafts:
    def create_outbound_draft(self, **_: Any):
        return {}, False


class _SafeKnowledge:
    def answer(self, _: str) -> KnowledgeDraft:
        return KnowledgeDraft(None)


class RaipurInboundOrchestrator:
    def __init__(self, client: Any, settings: Any, knowledge_provider: Any = None):
        self._settings = settings
        self._location = _cached_raipur_location(client)
        availability_provider = build_raipur_availability_provider(settings, client=client)
        services = ServiceRepository(client)
        bookings = BookingEnquiryService(
            BookingEnquiryRepository(client), availability_provider, services
        )
        self._contexts = ConversationRepository(client)
        self._langgraph_enabled = bool(getattr(settings, "raipur_langgraph_enabled", False))
        self._router_revision = str(getattr(settings, "router_revision", "local"))
        knowledge = knowledge_provider or _SafeKnowledge()
        fallback = build_raipur_conversational_fallback(settings)
        customer_understanding = build_customer_understanding_service(settings)
        sales_response_composer = build_sales_response_composer(settings)
        sales_agent = build_sales_agent(settings)
        sales_contact = SalesContact.from_settings(settings)
        # The feature flag selects exactly one engine.  LangGraph receives its
        # focused dependencies directly and never constructs the rollback
        # service; false retains the single explicit compatibility path.
        if self._langgraph_enabled:
            self._conversation = None
            self._langgraph = RaipurLangGraphWorkflow(
                knowledge=knowledge,
                services=services,
                location=self._location,
                sales_contact=sales_contact,
                conversational_fallback=fallback,
                customer_understanding=customer_understanding,
                understanding_enabled=True,
                sales_response_composer=sales_response_composer,
                sales_agent=sales_agent,
            )
        else:
            self._conversation = RaipurConversationService(
                knowledge=knowledge,
                bookings=bookings,
                drafts=_NoDrafts(),
                services=services,
                location=self._location,
                persist_drafts=False,
                timezone_name=settings.app_timezone,
                conversational_fallback=fallback,
                sales_contact=sales_contact,
            )
            self._langgraph = None
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
        # Context resolution is local repository work; keep it visible without
        # changing its ordering or fail-closed behaviour.
        with latency_stage("context_resolution"):
          if current_state is None and isinstance(customer_id, str) and isinstance(conversation_id, str):
            try:
                stored = self._contexts.get_service_context(conversation_id, customer_id)
            except Exception:
                # A context read failure must never leak another conversation's state.
                stored = None
        if (trace := current_latency_trace()) is not None: trace.event("context_load_complete", duration_ms=trace.value("context_resolution"))
        state, expired = _context_from_record(
            current_state if current_state is not None else stored or scoped.get("service_context"),
            self._context_ttl_minutes,
        )
        if current_state is None and _is_stale_greeting(stored, getattr(message, "content", ""), self._session_ttl_minutes):
            state, expired = None, True
        previous_service = state.last_service_name if state is not None else None
        content = getattr(message, "content", "")
        coimbatore_path = coimbatore_pontoon_enabled(self._settings, state)
        if coimbatore_path:
            result = qualify_coimbatore_pontoon(
                content, state or _empty_context(selected_location="coimbatore"),
                timezone_name=getattr(self._settings, "app_timezone", "Asia/Kolkata"),
            )
        else:
            result = (
                _interactive_gate_result(message, state, settings=self._settings)
                if bool(getattr(self._settings, "interactive_whatsapp_enabled", False)) else None
            )
        if result is not None:
            pass
        elif self._langgraph is None:
            result = self._conversation.process(
                message, customer=customer, conversation=scoped,
                source_message_id=source_message_id, current_state=state,
            )
        else:
            result = self._langgraph.invoke(
                {
                    "message_id": source_message_id,
                    "conversation_id": conversation_id if isinstance(conversation_id, str) else "",
                    "customer_id": customer_id if isinstance(customer_id, str) else "",
                    "customer_message": content if isinstance(content, str) else "",
                    "normalized_message": content.casefold().strip() if isinstance(content, str) else "",
                    "language": detect_language(content) if isinstance(content, str) else "en",
                    "location_code": "raipur", "previous_service_code": getattr(state, "last_service_code", None),
                    "previous_topic": getattr(state, "active_topic", None),
                    "intent": "unknown", "entity_type": "unknown", "service_code": None, "topic": None,
                    "use_previous_service": False, "requires_handover": False, "handover_reason": None,
                    "answer_source": "unresolved", "draft_response": None, "validation_status": "pending", "error": None, "route": "",
                },
                message=message, customer=customer, conversation=scoped,
                source_message_id=source_message_id, current_state=state,
            )
        if not coimbatore_path and result.context is not None and bool(getattr(self._settings, "interactive_whatsapp_enabled", False)):
            result = replace(result, context=merge_natural_visit_details(result.context, content))
            follow_up = qualification_reply(result.context)
            if follow_up is not None and not _looks_like_customer_question(content):
                result = replace(result, draft_text=follow_up, detected_intent="visit_qualification")
        if not coimbatore_path and bool(getattr(self._settings, "interactive_whatsapp_enabled", False)):
            result = _offer_celebration_selector(result)
        if not coimbatore_path and bool(getattr(self._settings, "interactive_whatsapp_enabled", False)):
            result = _offer_interactive_form(result, content, self._settings)
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
        service_code = metadata.get("service_code") if isinstance(metadata.get("service_code"), str) else getattr(result.context, "last_service_code", None)
        with latency_stage("response_formatting"):
            formatted = format_whatsapp_response(
                text=result.draft_text, intent=result.detected_intent,
                response_mode=metadata.get("response_mode") if isinstance(metadata.get("response_mode"), str) else None,
                service_code=service_code if isinstance(service_code, str) else None,
                service_display_name=getattr(result.context, "last_service_name", None),
                topic=metadata.get("topic") if isinstance(metadata.get("topic"), str) else None,
                language=result.response_language, requires_handover=result.human_handover_required,
            )
        result = replace(result, draft_text=formatted, safe_metadata=metadata)
        logger.info(
            "raipur_path_selected router_revision=%s langgraph_enabled=%s active_engine=%s "
            "message_id=%s message_character_count=%s selected_route=%s intent=%s service_code=%s topic=%s "
            "used_previous_service=%s answer_source=%s source_filename=%s automatic_reply_eligible=%s "
            "automatic_reply_rejection_reason=%s",
            self._router_revision,
            self._langgraph_enabled,
            metadata["active_engine"],
            source_message_id,
            len(getattr(message, "content", "")) if isinstance(getattr(message, "content", None), str) else 0,
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
        telemetry = metadata.get("conversation_telemetry")
        if isinstance(telemetry, dict):
            logger.info("raipur_conversation_telemetry event=%s", json.dumps(telemetry, separators=(",", ":"), sort_keys=True))
        if isinstance(customer_id, str) and isinstance(conversation_id, str) and result.context is not None:
            try:
                with latency_stage("context_save"):
                    self._contexts.save_service_context(conversation_id, customer_id, _context_to_record(result.context))
                if (trace := current_latency_trace()) is not None: trace.event("context_save_complete", duration_ms=trace.value("context_save"))
            except Exception:
                # The reply remains safe, but the next message will ask for clarification.
                pass
        return result


def _empty_context(*, selected_location: str | None = None) -> ConversationContext:
    return ConversationContext(
        BookingDetails(None, None, None, None, None, None, None),
        selected_location=selected_location,
    )


def _controlled_interactive_result(
    text: str, *, context: ConversationContext, intent: str, metadata: dict[str, Any] | None = None,
) -> Any:
    from app.services.raipur.response_models import ConversationResult
    return ConversationResult(
        action="answer_information", draft_text=text, reason_code="interactive_journey",
        detected_intent=intent, detected_location=context.selected_location or "unresolved",
        response_language="en", human_handover_required=False, context=context,
        safe_metadata={
            "response_mode": "deterministic_interactive", "response_basis": "structured_grounding",
            "structured_grounding": True, "customer_response_sanitized": True,
            "answer_source": "interactive_journey", **(metadata or {}),
        },
    )


def _interactive_gate_result(message: Any, state: ConversationContext | None, *, settings: Any) -> Any | None:
    text = getattr(message, "content", "")
    context = state or _empty_context()
    if requests_location_change(text):
        selector = location_selector()
        reset = replace(context, selected_location=None, active_journey=None, active_form=None, form_status="not_started")
        return _controlled_interactive_result(
            selector.fallback_text, context=reset, intent="location",
            metadata={"interactive_message": selector.as_metadata(), "interactive_message_type": "list", "location_selector_sent": True},
        )

    selected = requested_location(text)
    if context.selected_location is None:
        if selected is None:
            selector = location_selector()
            return _controlled_interactive_result(
                selector.fallback_text, context=context, intent="location",
                metadata={"interactive_message": selector.as_metadata(), "interactive_message_type": "list", "location_selector_sent": True},
            )
        context = replace(context, selected_location=selected)
        if selected == "raipur":
            context = replace(context, active_journey="visit_qualification")
            return _controlled_interactive_result(
                _RAIPUR_QUALIFICATION_MESSAGE,
                context=context, intent="location", metadata={"location_selected": "raipur"},
            )
        return _controlled_interactive_result(
            "Automated assistance for this location is being prepared. Raipur is currently available for complete assistance.",
            context=context, intent="location", metadata={"location_selected": selected, "inactive_location": True},
        )

    if selected is not None and selected != context.selected_location:
        context = replace(context, selected_location=selected, active_journey=None, active_form=None, form_status="not_started")
        if selected != "raipur":
            return _controlled_interactive_result(
                "Automated assistance for this location is being prepared. Raipur is currently available for complete assistance.",
                context=context, intent="location", metadata={"location_selected": selected, "inactive_location": True},
            )
        return _controlled_interactive_result(
            _RAIPUR_QUALIFICATION_MESSAGE,
            context=replace(context, active_journey="visit_qualification"), intent="location", metadata={"location_selected": "raipur"},
        )

    if context.selected_location != "raipur":
        return _controlled_interactive_result(
            "Automated assistance for this location is being prepared. Raipur is currently available for complete assistance.",
            context=context, intent="location", metadata={"location_selected": context.selected_location, "inactive_location": True},
        )

    form_response = getattr(message, "form_response", None)
    if getattr(message, "message_type", None) == "flow" and isinstance(form_response, dict):
        if context.last_service_code == "pontoon_celebration" and context.active_form == "pontoon_celebration":
            form_response = {**form_response, "flow_type": "pontoon_celebration"}
        merged, errors = merge_form_response(context, form_response)
        if errors:
            if merged.active_form == "pontoon_celebration":
                if "event_date" in errors and merged.details.total_guests is not None:
                    correction = "That date is invalid or has already passed. Please share a future date for the celebration."
                elif "number_of_persons" in errors and merged.details.preferred_date is not None:
                    correction = "Please share a positive number of persons for the celebration."
                else:
                    correction = "Please share a valid future Event Date and a positive Number of Persons."
                return _controlled_interactive_result(
                    correction, context=merged, intent="booking",
                    metadata={"flow_submitted": True, "flow_type": "pontoon_celebration", "flow_validation_errors": list(errors)},
                )
            return _controlled_interactive_result(
                "I couldn't validate all submitted details. Please share the corrected details here.",
                context=merged, intent="booking", metadata={"flow_submitted": True, "flow_validation_errors": list(errors)},
            )
        form_type = merged.active_form
        if form_type == "pontoon_celebration":
            planned = merged.details.preferred_date
            guests = merged.details.total_guests
            text = (
                f"Great — I have {planned.strftime('%d %B')} for {guests} guests for your Pontoon Celebration 🎉\n"
                "You can ask me anything about the package, inclusions or arrangements."
            )
            return _controlled_interactive_result(
                text, context=merged, intent="booking",
                metadata={"flow_submitted": True, "flow_type": form_type, "pontoon_qualification_complete": True},
            )
        text = (
            "Thanks 😊 I have your visit details. I can now help you explore the most relevant Raipur experiences."
            if form_type == "general_quote"
            else "Thanks 😊 I have your celebration details. Our team will confirm availability, price and final booking details with you."
        )
        return _controlled_interactive_result(
            text, context=merged, intent="booking",
            metadata={"flow_submitted": True, "flow_type": form_type},
        )
    return None


def _looks_like_customer_question(text: object) -> bool:
    if not isinstance(text, str):
        return False
    lowered = text.casefold()
    return "?" in text or bool(re.search(r"\b(?:what|which|where|when|how|do you|is there|kya|kaun|kab|activities|activity)\b", lowered))


def _offer_celebration_selector(result: Any) -> Any:
    """Attach one list to broad discovery; service-specific routes remain untouched."""
    if result is None or result.context is None or result.context.selected_location != "raipur":
        return result
    if result.detected_intent != "celebration_service_list" or result.context.last_service_code:
        return result
    interactive = celebration_selector(result.draft_text)
    metadata = dict(result.safe_metadata or {})
    metadata.update({
        "interactive_message": interactive.as_metadata(),
        "interactive_message_type": "list",
        "celebration_selector_sent": True,
    })
    return replace(result, safe_metadata=metadata)


def _offer_interactive_form(result: Any, text: object, settings: Any) -> Any:
    if result is None or result.context is None or result.context.selected_location != "raipur" or not isinstance(text, str):
        return result
    if result.safe_metadata and result.safe_metadata.get("flow_submitted"):
        return result
    metadata = dict(result.safe_metadata or {})
    if result.context.last_service_code == "pontoon_celebration" and metadata.get("pontoon_media_attached") is True:
        flow_id = getattr(settings, "raipur_pontoon_celebration_flow_id", None)
        template_id = getattr(settings, "raipur_pontoon_celebration_template_id", None)
        media = metadata.get("media_message") if isinstance(metadata.get("media_message"), dict) else None
        image_url = media.get("url") if isinstance(media, dict) else None
        package_source = metadata.get("package_source_file")
        if all(isinstance(value, str) and value.strip() for value in (flow_id, template_id, image_url, package_source)):
            template = TemplateMessage(
                name=template_id.strip(), language="en", header_image_url=image_url.strip(),
                flow_id=flow_id.strip(), flow_cta="Share Event Details",
                service_code="pontoon_celebration", package_source_file=package_source.strip(),
            )
            context = replace(
                result.context, active_journey="celebration", active_form="pontoon_celebration", form_status="in_progress",
            )
            metadata.pop("media_message", None)
            metadata.pop("interactive_message", None)
            metadata.update({
                "template_message": template.as_metadata(), "template_message_type": "template",
                "combined_template_offered": True, "flow_offered": True, "flow_type": "pontoon_celebration",
            })
            return replace(result, context=context, safe_metadata=metadata)
        return result
    lowered = text.casefold()
    celebration_booking = bool(
        re.search(r"\b(?:book|booking|reserve)\b", lowered)
        and re.search(r"\b(?:birthday|anniversary|celebration|proposal|party|gazebo|pontoon|houseboat)\b", lowered)
    )
    general_planning = bool(re.search(r"\b(?:plan\s+(?:my|a|our)?\s*visit|best\s+quote|quote\s+details|package\s+(?:selection|book))\b", lowered))
    if not (celebration_booking or general_planning):
        return result
    flow_type = "celebration" if celebration_booking else "general_quote"
    flow_id = getattr(settings, "raipur_celebration_flow_id" if celebration_booking else "raipur_general_quote_flow_id", None)
    interactive = configured_flow(flow_type=flow_type, flow_id=flow_id)
    context = replace(result.context, active_journey="celebration" if celebration_booking else "visit_quote",
                      active_form=flow_type, form_status="in_progress")
    metadata = dict(result.safe_metadata or {})
    if interactive.kind == "flow":
        metadata.update({"interactive_message": interactive.as_metadata(), "interactive_message_type": "flow",
                         "flow_offered": True, "flow_type": flow_type})
    else:
        metadata.update({"interactive_fallback_used": True, "flow_offered": False, "flow_type": flow_type})
    return replace(result, draft_text=interactive.fallback_text, context=context, safe_metadata=metadata)


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
    selected_location = _optional_text(value.get("selected_location") or value.get("location_code"))
    has_topic = isinstance(value.get("active_domain"), str) or bool(value.get("pending_clarification"))
    if not has_service and not has_topic and selected_location is None:
        return None, False
    from app.services.booking_enquiries import BookingDetails
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
        sales_stage=_sales_stage(value.get("sales_stage")),
        selected_location=selected_location,
        active_journey=_optional_text(value.get("active_journey")),
        active_form=_optional_text(value.get("active_form")),
        form_status=_optional_text(value.get("form_status")) or "not_started",
        form_values=value.get("form_values") if isinstance(value.get("form_values"), dict) else None,
    ), False


def _context_to_record(context: Any) -> dict[str, Any]:
    """Serialize the structured conversation state needed for the next inbound turn."""

    details = context.details
    return {
        "location_code": context.selected_location,
        "selected_location": context.selected_location,
        "active_journey": context.active_journey,
        "active_form": context.active_form,
        "form_status": context.form_status,
        "form_values": context.form_values,
        "service_code": context.last_service_code,
        "previous_service_code": context.last_service_code,
        "previous_topic": context.active_topic,
        "last_answer_source": context.last_answer_source,
        "last_answer_sections": list(context.last_answer_sections),
        "sales_stage": context.sales_stage.value,
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


def _sales_stage(value: Any) -> SalesStage:
    try:
        return SalesStage(value)
    except (TypeError, ValueError):
        return SalesStage.DISCOVERY


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
