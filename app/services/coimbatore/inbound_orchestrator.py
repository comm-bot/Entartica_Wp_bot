"""Sole live inbound path for the bounded Coimbatore Pontoon MVP."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.repositories.conversations import ConversationRepository
from app.rag.coimbatore_knowledge_provider import CoimbatoreKnowledgeProvider
from app.services.coimbatore.customer_understanding import (
    CoimbatoreUnderstanding, CustomerIntent, PackageReference,
    build_coimbatore_understanding_service,
)
from app.services.coimbatore.response_composer import (
    CoimbatoreResponseBrief, build_coimbatore_response_composer,
)
from app.services.coimbatore.pontoon_qualification import (
    FIRST_MESSAGE,
    has_qualification_update,
    package_qualification_ready,
    qualify,
)
from app.services.coimbatore.pontoon_package import (
    COUPLE_PACKAGE_ID, STANDARD_PACKAGE_ID, action_id, action_message, handle_action,
    is_package_request, load_package, package_presented, package_request_id, render_package,
    resolve_standard_package_pricing, returning_customer_menu,
)
from app.services.raipur.response_models import ConversationContext, ConversationResult
from app.services.raipur.sales_state import SalesStage
from app.services.raipur.customer_understanding import parse_planned_date_text
from app.services.raipur_inbound_orchestrator import _context_from_record, _context_to_record, _empty_context
from app.services.latency import latency_stage
from app.services.coimbatore.langgraph_workflow import CoimbatoreLangGraphWorkflow
from app.integrations.razorpay import RazorpayPaymentLinkClient
from app.services.coimbatore.payment_links import CoimbatorePaymentLinkService
from app.services.coimbatore.customer_details import (
    CustomerDetailsFormService, customer_details_complete,
)
from app.schemas.interactive_messages import customer_details_flow


logger = logging.getLogger("uvicorn.error")


class CoimbatoreInboundOrchestrator:
    """Qualify one product without constructing or querying any RAG provider."""

    def __init__(self, client: Any, settings: Any) -> None:
        self._client = client
        self._settings = settings
        self._contexts = ConversationRepository(client)
        self._knowledge = CoimbatoreKnowledgeProvider(client, settings)
        self._understanding = build_coimbatore_understanding_service(settings)
        self._composer = build_coimbatore_response_composer(settings)
        self._context_ttl_minutes = max(
            1, int(getattr(settings, "raipur_conversation_context_ttl_minutes", 120))
        )
        self._langgraph_enabled = bool(getattr(settings, "coimbatore_langgraph_enabled", True))
        self._langgraph = CoimbatoreLangGraphWorkflow(self._process_turn) if self._langgraph_enabled else None
        self._customer_details = CustomerDetailsFormService(
            client,
            public_base_url=getattr(settings, "public_base_url", None),
            ttl_minutes=getattr(settings, "coimbatore_customer_details_form_ttl_minutes", 30),
        )

    def process(
        self,
        message: Any,
        *,
        customer: dict[str, Any],
        conversation: dict[str, Any],
        source_message_id: str,
        current_state: Any = None,
    ):
        graph = getattr(self, "_langgraph", None)
        enabled = bool(getattr(self._settings, "coimbatore_langgraph_enabled", False))
        if enabled and graph is not None:
            return graph.invoke(
                message=message, customer=customer, conversation=conversation,
                source_message_id=source_message_id, current_state=current_state,
            )
        return self._process_turn(
            message, customer=customer, conversation=conversation,
            source_message_id=source_message_id, current_state=current_state,
        )

    def _process_turn(
        self,
        message: Any,
        *,
        customer: dict[str, Any],
        conversation: dict[str, Any],
        source_message_id: str,
        current_state: Any = None,
    ):
        customer_id, conversation_id = customer.get("id"), conversation.get("id")
        if (bool(getattr(self._settings, "coimbatore_customer_details_form_enabled", False))
                and not customer_details_complete(customer)):
            form_response = getattr(message, "form_response", None)
            if getattr(message, "message_type", None) == "flow" and isinstance(form_response, dict):
                submitted = self._customer_details.submit_native(
                    str(form_response.get("flow_token") or ""),
                    customer_id=str(customer_id), conversation_id=str(conversation_id),
                    name=form_response.get("full_name"), email=form_response.get("email"),
                )
                if submitted.accepted and submitted.customer:
                    name = str(submitted.customer.get("name") or "Guest")
                    context = _empty_context(selected_location="coimbatore")
                    values = dict(context.form_values or {})
                    values.update({"customer_email": submitted.customer.get("email"),
                                   "customer_details_complete": True,
                                   "active_package_id": STANDARD_PACKAGE_ID})
                    context = replace(
                        context, details=replace(context.details, customer_name=name),
                        active_form="customer_details", form_status="completed",
                        form_values=values, pending_field="preferred_date",
                    )
                    result = ConversationResult(
                        action="answer_information",
                        draft_text=(f"Thanks {name.split()[0]}! 👋\n\n"
                                    "How many guests will be visiting, and what date are you planning for?\n\n"
                                    "💡 eg. 7 , 26/08/2026"),
                        reason_code="coimbatore_customer_details_completed",
                        detected_intent="qualification", detected_location="coimbatore",
                        response_language="en", human_handover_required=False, context=context,
                        safe_metadata={"response_basis":"deterministic", "structured_grounding":True,
                            "customer_response_sanitized":True, "automatic_reply_category":"information",
                            "customer_details_completed":True, "service_code":"pontoon_celebration"},
                    )
                    return self._finalize(result, customer_id, conversation_id, False, source_message_id)
            try:
                flow_id = getattr(self._settings, "coimbatore_customer_details_flow_id", None)
                if not isinstance(flow_id, str) or not flow_id.strip():
                    raise RuntimeError("coimbatore_customer_details_flow_id_missing")
                token = self._customer_details.issue_native_token(
                    customer_id=str(customer_id), conversation_id=str(conversation_id),
                )
                interactive = customer_details_flow(flow_id=flow_id.strip(), flow_token=token)
                prompt = interactive.body
                interactive_metadata = interactive.as_metadata()
            except Exception:
                logger.exception("coimbatore_customer_details_form_unavailable")
                prompt = ("The WhatsApp details form is temporarily unavailable. "
                          "Please try again shortly.")
                interactive_metadata = None
            context = _empty_context(selected_location="coimbatore")
            values = dict(context.form_values or {})
            values.update({"customer_details_complete": False, "active_package_id": STANDARD_PACKAGE_ID})
            context = replace(context, active_form="customer_details", form_status="in_progress",
                              form_values=values, pending_field=None)
            result = ConversationResult(
                action="answer_information", draft_text=prompt,
                reason_code="coimbatore_customer_details_required",
                detected_intent="customer_details", detected_location="coimbatore",
                response_language="en", human_handover_required=False, context=context,
                safe_metadata={"response_basis":"deterministic", "structured_grounding":True,
                    "customer_response_sanitized":True, "automatic_reply_category":"information",
                    "customer_details_required":True, "service_code":"pontoon_celebration",
                    **({"interactive_message": interactive_metadata,
                        "interactive_message_type":"flow"} if interactive_metadata else {})},
            )
            return self._finalize(result, customer_id, conversation_id, True, source_message_id)
        persistent = self._sales_state_is_persistent()
        state_key = self._session_state_key(customer_id, conversation_id)
        content = getattr(message, "content", "")
        if not persistent and _is_development_reset(content):
            if state_key is not None:
                self._session_states().pop(state_key, None)
            logger.info(
                "coimbatore_state_mode=session session_state_reset=true pending_field=none sales_stage=lead"
            )
            active = _empty_context(selected_location="coimbatore")
            values = dict(active.form_values or {})
            values["active_package_id"] = STANDARD_PACKAGE_ID
            reset = qualify("", replace(active, form_values=values), timezone_name=getattr(self._settings, "app_timezone", "Asia/Kolkata"))
            reset = replace(
                reset,
                draft_text=("Sure 😊 Let's start again.\n\n"
                            "How many guests will be visiting, and what date are you planning for?\n\n"
                            "💡 eg. 7 , 26/08/2026"),
                context=replace(reset.context, pending_field="preferred_date" if self._text_only_package_mode() else "total_guests"),
            )
            return self._finalize(reset, customer_id, conversation_id, True, source_message_id)
        with latency_stage("session_state_load"):
            stored = None
            if persistent and current_state is None and isinstance(customer_id, str) and isinstance(conversation_id, str):
                try:
                    stored = self._contexts.get_service_context(conversation_id, customer_id)
                except Exception:
                    stored = None
            elif not persistent and state_key is not None:
                stored = self._session_states().get(state_key)
                logger.info(
                    "coimbatore_state_mode=session session_state_%s=true stale_supabase_state_ignored=true",
                    "loaded" if stored is not None else "created",
                )
            context, context_expired = _context_from_record(
                (current_state if current_state is not None else stored or conversation.get("service_context"))
                if persistent else stored,
                self._context_ttl_minutes,
            )
        fresh = context is None or context.selected_location != "coimbatore" or context.last_service_code != "pontoon_celebration"
        returning_customer = context_expired or (
            context is not None
            and context.sales_stage in {
                SalesStage.QUALIFIED, SalesStage.PACKAGE_PRESENTED,
                SalesStage.INTERESTED, SalesStage.DETAILS_COLLECTED,
                SalesStage.PAYMENT_PENDING, SalesStage.BOOKED, SalesStage.HANDOVER,
            }
        )
        active = context if not fresh else _empty_context(selected_location="coimbatore")
        identity_values = dict(active.form_values or {})
        identity_values.update({
            "payment_customer_id": customer_id, "payment_conversation_id": conversation_id,
            "payment_customer_mobile": customer.get("whatsapp_number"),
            "payment_customer_name": customer.get("name"),
            "customer_email": customer.get("email"),
            "customer_details_complete": customer_details_complete(customer),
        })
        identity_details = active.details
        if isinstance(customer.get("name"), str) and customer["name"].strip():
            identity_details = replace(identity_details, customer_name=customer["name"].strip())
        active = replace(active, details=identity_details, form_values=identity_values)
        if package_presented(active) and active.sales_stage == SalesStage.QUALIFIED:
            active = replace(active, sales_stage=SalesStage.PACKAGE_PRESENTED)
        if self._text_only_package_mode():
            text_only = self._process_text_only_entry(content, active, fresh=fresh)
            if text_only is not None:
                return self._finalize(text_only, customer_id, conversation_id, fresh, source_message_id)
        if _is_coimbatore_location_question(content):
            location = _text_entry_result(
                "Entartica SeaWorld Coimbatore is at Periyakulam Lake Boat House, "
                "Ukkadam, Coimbatore, Tamil Nadu 641001.\n\n"
                "Google Maps: https://share.google/AUJRM6sIvbEqeJeH2",
                _coimbatore_text_context(active), "coimbatore_approved_location",
            )
            location = replace(location, detected_intent="location")
            return self._finalize(location, customer_id, conversation_id, fresh, source_message_id)
        if _is_greeting(content) and returning_customer:
            result = self._returning_customer_menu_result(active)
            return self._finalize(result, customer_id, conversation_id, False, source_message_id)
        selected_action = action_id(content)
        if selected_action == "coimbatore_pontoon_check_standard":
            result = self._default_standard_package_result(active)
            return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)
        if selected_action == "coimbatore_pontoon_check_couple":
            result = self._package_result(active, COUPLE_PACKAGE_ID)
            return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)
        if (
            selected_action == "coimbatore_pontoon_more_photos"
            and bool((active.form_values or {}).get("returning_customer_menu_shown"))
        ):
            values = dict(active.form_values or {})
            values["active_package_id"] = STANDARD_PACKAGE_ID
            result = self._handle_package_action(
                selected_action, replace(active, form_values=values)
            )
            return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)
        if selected_action and package_qualification_ready(active):
            result = self._handle_package_action(selected_action, active)
            return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)
        requested_package = package_request_id(content)
        if requested_package == "default_standard":
            result = self._default_standard_package_result(active)
            return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)
        if requested_package is not None:
            package_context = replace(
                active, selected_location="coimbatore", last_service_code="pontoon_celebration",
                last_service_name="Pontoon Boat Celebration", active_journey="pontoon_qualification",
            )
            if requested_package == "choice":
                current = (active.form_values or {}).get("active_package_id")
                requested_package = (
                    current if current in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID}
                    else STANDARD_PACKAGE_ID
                )
            values = dict(package_context.form_values or {})
            values["active_package_id"] = requested_package
            package_context = replace(package_context, form_values=values)
            result = self._package_result(package_context, requested_package)
            return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)
        if active.sales_stage == SalesStage.INTERESTED:
            result = _collect_booking_details(content, active)
            return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)
        if (
            fresh
            and (active.details.preferred_date is None or active.details.total_guests is None)
            and not has_qualification_update(content, active)
        ):
            values = dict(active.form_values or {})
            values["active_package_id"] = COUPLE_PACKAGE_ID if requested_package == COUPLE_PACKAGE_ID else STANDARD_PACKAGE_ID
            welcome_context = replace(active, form_values=values)
            welcome = qualify("", welcome_context, timezone_name=getattr(self._settings, "app_timezone", "Asia/Kolkata"))
            welcome = replace(welcome, context=replace(welcome.context, pending_field="total_guests"))
            return self._finalize(welcome, customer_id, conversation_id, fresh, source_message_id)
        if has_qualification_update(content, active):
            logger.info(
                "qualification_before date_known=%s guest_known=%s pending_field=%s",
                active.details.preferred_date is not None, active.details.total_guests is not None,
                active.pending_field or "none",
            )
            values = dict(active.form_values or {})
            if values.get("active_package_id") not in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID}:
                values["active_package_id"] = STANDARD_PACKAGE_ID
            qualification_context = replace(active, form_values=values)
            with latency_stage("deterministic_pending_field_resolution"), latency_stage("qualification"), latency_stage("date_parse"), latency_stage("guest_parse"):
                qualified = qualify(
                    content, qualification_context,
                    timezone_name=getattr(self._settings, "app_timezone", "Asia/Kolkata"),
                )
            date_extracted = qualified.context.details.preferred_date != active.details.preferred_date
            guest_extracted = qualified.context.details.total_guests != active.details.total_guests
            complete = package_qualification_ready(qualified.context)
            logger.info(
                "understanding_result mode=deterministic_qualification date_extracted=%s guest_extracted=%s",
                date_extracted, guest_extracted,
            )
            logger.info(
                "qualification_after date_known=%s guest_known=%s qualification_complete=%s",
                qualified.context.details.preferred_date is not None,
                qualified.context.details.total_guests is not None, complete,
            )
            if complete:
                current = (qualified.context.form_values or {}).get("active_package_id")
                selected = COUPLE_PACKAGE_ID if current == COUPLE_PACKAGE_ID else STANDARD_PACKAGE_ID
                values = dict(qualified.context.form_values or {}); values["active_package_id"] = selected
                qualified_context = replace(qualified.context, form_values=values)
                already_sent = package_presented(active)
                send_pending = bool((active.form_values or {}).get("package_presentation_pending"))
                result = qualified if already_sent or send_pending else self._package_result(qualified_context, selected)
                if not already_sent and not send_pending:
                    logger.info("package_triggered package_id=%s qualification_complete=true", selected)
            else:
                result = qualified
            return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)
        if (
            _is_greeting(content)
            and active.details.preferred_date is not None
            and active.details.total_guests is not None
            and (active.form_values or {}).get("active_package_id") not in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID}
        ):
            return self._finalize(_package_choice_result(active), customer_id, conversation_id, fresh, source_message_id)
        llm_result = self._process_llm_turn(str(content), active, fresh=fresh, source_message_id=source_message_id)
        if llm_result is not None:
            result = (
                self._default_standard_package_result(active)
                if llm_result.detected_intent == "unknown"
                and active.sales_stage == SalesStage.LEAD
                and active.details.preferred_date is None
                and active.details.total_guests is None
                else llm_result
            )
            return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)
        selected_action = action_id(content)
        explicit_package_request = is_package_request(content)
        was_presented = package_presented(active)
        if selected_action and package_qualification_ready(active):
            result = self._handle_package_action(selected_action, active)
        elif active.sales_stage == SalesStage.INTERESTED:
            result = _collect_booking_details(content, active)
        else:
            result = qualify(
                content, active,
                timezone_name=getattr(self._settings, "app_timezone", "Asia/Kolkata"),
            )
        knowledge_answer = None
        if selected_action is None and active.sales_stage not in {SalesStage.INTERESTED, SalesStage.DETAILS_COLLECTED, SalesStage.PAYMENT_PENDING, SalesStage.BOOKED}:
            try:
                knowledge_question = str(content)
                if result.context.details.total_guests != active.details.total_guests and result.context.details.total_guests is not None:
                    knowledge_question = f"price for {result.context.details.total_guests} guests"
                elif explicit_package_request and not re.search(r"how much|price+|cost|rates?|kitna|kitne ka", str(content), re.I):
                    knowledge_question = "what is Pontoon Celebration"
                active_package = (active.form_values or {}).get("active_package_id")
                knowledge_answer = self._knowledge.answer(
                    knowledge_question, guest_count=result.context.details.total_guests,
                    package_id=active_package if active_package in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID} else None,
                )
            except Exception:
                logger.exception("coimbatore_knowledge_failed operation=answer message_id=%s", source_message_id)
        if knowledge_answer is not None:
            values = dict(result.context.form_values or {})
            correction = (
                result.context.details.preferred_date != active.details.preferred_date
                or result.context.details.total_guests != active.details.total_guests
            )
            if correction:
                values["standard_package_presented"] = False
                values.pop("active_package_id", None)
                values.pop("standard_package_id", None)
            if knowledge_answer.package_id: values["active_package_id"] = knowledge_answer.package_id
            updated = replace(
                result.context, form_values=values,
                sales_stage=SalesStage.QUALIFIED if correction else active.sales_stage if active.sales_stage == SalesStage.PACKAGE_PRESENTED else result.context.sales_stage,
            )
            next_question = ""
            if updated.details.preferred_date is None and knowledge_answer.topic in {"price", "overview"}:
                next_question = "\n\nWhich date are you planning for?" if updated.details.total_guests is not None else ""
            elif knowledge_answer.topic == "occasion":
                if updated.details.total_guests is None:
                    next_question = "\n\nHow many guests will be joining?"
                elif updated.details.preferred_date is None:
                    next_question = "\n\nWhich date are you planning for?"
                else:
                    next_question = "\n\nWould you like to continue with the recommended package?"
            result = replace(
                result, draft_text=knowledge_answer.text + next_question, context=updated,
                human_handover_required=knowledge_answer.handoff_required,
                action="general_human_handover" if knowledge_answer.handoff_required else "answer_information",
                reason_code="coimbatore_master_knowledge", detected_intent=knowledge_answer.topic,
                safe_metadata={"response_basis":"active_rag","source_filename":"COIMBATORE_KNOWLEDGE_BASE.md",
                    "source_heading":knowledge_answer.source_heading,"authority":knowledge_answer.authority,
                    "customer_response_sanitized":True,"structured_grounding":True,"service_code":"pontoon_celebration",
                    "knowledge_location":"coimbatore","requires_live_data":knowledge_answer.requires_live_data,
                    "approved_coimbatore_master":True,
                    "automatic_reply_category":"information"},
            )
        elif (
            result.context.details.preferred_date is not None
            and result.context.details.total_guests is not None
            and selected_action is None
            and active.sales_stage not in {SalesStage.INTERESTED, SalesStage.DETAILS_COLLECTED, SalesStage.PAYMENT_PENDING, SalesStage.BOOKED}
        ):
            correction = (
                result.context.details.preferred_date != active.details.preferred_date
                or result.context.details.total_guests != active.details.total_guests
            )
            values = dict(result.context.form_values or {})
            guest_changed = result.context.details.total_guests != active.details.total_guests
            date_changed = result.context.details.preferred_date != active.details.preferred_date
            if correction:
                values["standard_package_presented"] = False
            if guest_changed:
                values.pop("active_package_id", None)
                values.pop("standard_package_id", None)
            if date_changed:
                fallback_text = "Perfect 😊 I've noted your celebration date. Ready to continue with your Pontoon package?"
            elif result.context.details.preferred_date is None:
                fallback_text = "Which date are you planning your Pontoon Celebration for?"
            elif result.context.details.total_guests is None:
                fallback_text = "How many guests will be joining?"
            else:
                fallback_text = "I didn't quite catch that. Would you like to continue with your Pontoon package?"
            result = replace(
                result,
                draft_text=fallback_text,
                context=replace(result.context, form_values=values, sales_stage=SalesStage.QUALIFIED if correction else active.sales_stage if active.sales_stage == SalesStage.PACKAGE_PRESENTED else SalesStage.QUALIFIED),
            )
        if (
            not fresh
            and knowledge_answer is None
            and selected_action is None
            and requested_package is None
            and active.sales_stage == SalesStage.LEAD
            and active.details.preferred_date is None
            and active.details.total_guests is None
            and not _is_greeting(content)
            and not has_qualification_update(content, active)
            and result.reason_code == "coimbatore_pontoon_qualification"
        ):
            result = self._default_standard_package_result(active)
        if _is_greeting(content) and not fresh:
            if result.context.details.total_guests is not None and result.context.details.preferred_date is None:
                greeting = "Hi 😊 Which date are you planning your Pontoon Celebration for?"
            elif result.context.details.preferred_date is not None and result.context.details.total_guests is None:
                greeting = "Hi 😊 How many guests will be joining?"
            elif active.sales_stage == SalesStage.PACKAGE_PRESENTED or (result.context.form_values or {}).get("active_package_id"):
                greeting = "Hi 😊 Ready to continue with your Pontoon Celebration?"
            else:
                greeting = result.draft_text
            result = replace(
                result,
                draft_text=greeting,
                detected_intent="greeting",
                reason_code="coimbatore_stage_greeting",
            )
        if not fresh and isinstance(content, str) and "raipur" in content.casefold():
            result = replace(
                result,
                draft_text="Right now I can help with the Pontoon Boat Celebration at Entartica Coimbatore.",
            )
        return self._finalize(result, customer_id, conversation_id, fresh, source_message_id)

    def _finalize(self, result, customer_id, conversation_id, fresh, source_message_id):
        metadata = dict(result.safe_metadata or {})
        metadata.update({
            "active_location": "coimbatore",
            "active_service": "pontoon_celebration",
            "conversation_fresh": fresh,
            "planned_date_known": result.context.details.preferred_date is not None,
            "guest_count_known": result.context.details.total_guests is not None,
            "sales_stage": result.context.sales_stage.value,
            "knowledge_location": "coimbatore",
            "raipur_retrieval_used": False,
            "raipur_knowledge_used": False,
            "standard_package_presented": package_presented(result.context),
            "automatic_reply_category": "information",
            "coimbatore_state_mode": "persistent" if self._sales_state_is_persistent() else "session",
        })
        # These bounded replies are already approved verbatim; generic formatting
        # would alter the required first-message wording.
        result = replace(result, safe_metadata=metadata)
        # Only the bounded sales journey becomes process-local in development.
        if isinstance(customer_id, str) and isinstance(conversation_id, str):
            record = _context_to_record(result.context)
            if self._sales_state_is_persistent():
                try:
                    self._contexts.save_service_context(conversation_id, customer_id, record)
                except Exception:
                    logger.exception(
                        "coimbatore_context_save_failed operation=context_save message_id=%s",
                        source_message_id,
                    )
            else:
                key = self._session_state_key(customer_id, conversation_id)
                if key is not None:
                    self._session_states()[key] = record
        logger.info(
            "coimbatore_path_selected active_location=coimbatore active_service=pontoon_celebration "
            "conversation_fresh=%s planned_date_known=%s guest_count_known=%s sales_stage=%s "
            "pending_field=%s coimbatore_state_mode=%s knowledge_location=coimbatore "
            "raipur_retrieval_used=false message_id=%s",
            fresh, metadata["planned_date_known"], metadata["guest_count_known"],
            metadata["sales_stage"], result.context.pending_field or "none",
            metadata["coimbatore_state_mode"], source_message_id,
        )
        return result

    def _sales_state_is_persistent(self) -> bool:
        # Default true for lightweight legacy test doubles; real Settings defaults
        # to session mode until production persistence is deliberately re-enabled.
        return bool(getattr(self._settings, "coimbatore_persist_sales_state", True))

    def _text_only_package_mode(self) -> bool:
        return not bool(getattr(self._settings, "coimbatore_package_media_enabled", True))

    def _process_text_only_entry(self, content: object, active: ConversationContext, *, fresh: bool):
        text = content.strip() if isinstance(content, str) else ""
        requested = package_request_id(text)
        if requested is not None:
            selected = COUPLE_PACKAGE_ID if requested == COUPLE_PACKAGE_ID else STANDARD_PACKAGE_ID
            return self._package_result(_coimbatore_text_context(active), selected)
        if fresh and _is_greeting(text):
            return _text_entry_result(
                FIRST_MESSAGE,
                replace(_coimbatore_text_context(active), pending_field="preferred_date"),
                "coimbatore_text_entry_welcome",
            )
        numeric_guest = re.fullmatch(r"\s*\d{1,3}\s*", text) is not None
        if has_qualification_update(text, active) or numeric_guest or active.pending_field in {"preferred_date", "total_guests"}:
            context = _coimbatore_text_context(active)
            if numeric_guest and context.pending_field is None:
                context = replace(context, pending_field="total_guests")
            qualified = qualify(
                text, context,
                timezone_name=getattr(self._settings, "app_timezone", "Asia/Kolkata"),
            )
            if package_qualification_ready(qualified.context):
                return self._package_result(
                    replace(qualified.context, pending_field=None, sales_stage=SalesStage.QUALIFIED),
                    STANDARD_PACKAGE_ID,
                )
            return qualified
        return None

    def _session_states(self) -> dict[str, dict[str, Any]]:
        states = getattr(self, "_coimbatore_session_states", None)
        if states is None:
            states = {}
            self._coimbatore_session_states = states
        return states

    @staticmethod
    def _session_state_key(customer_id: object, conversation_id: object) -> str | None:
        if not isinstance(customer_id, str) or not isinstance(conversation_id, str):
            return None
        return f"{customer_id.strip().casefold()}:{conversation_id.strip().casefold()}"

    def _process_llm_turn(self, content: str, active: ConversationContext, *, fresh: bool, source_message_id: str):
        understanding_service = getattr(self, "_understanding", None)
        composer = getattr(self, "_composer", None)
        if understanding_service is None or composer is None:
            return None
        compact = {
            "location": "coimbatore", "product": "pontoon_celebration",
            "sales_stage": active.sales_stage.value,
            "guest_count": active.details.total_guests,
            "preferred_date": active.details.preferred_date.isoformat() if active.details.preferred_date else None,
            "preferred_time": active.details.preferred_time.isoformat() if active.details.preferred_time else None,
            "active_package_id": (active.form_values or {}).get("active_package_id"),
            "occasion": (active.form_values or {}).get("occasion"),
        }
        with latency_stage("LLM_understanding"):
            understanding = understanding_service.understand(content, compact)
        if understanding is None:
            logger.info("coimbatore_understanding_mode=llm understanding_fallback=true reason=unavailable_or_failed")
            return None

        details, values = active.details, dict(active.form_values or {})
        prior_package_id = values.get("active_package_id")
        guest = _validated_guest_update(content, understanding)
        guest_changed = guest is not None and guest != details.total_guests
        if guest is not None: details = replace(details, total_guests=guest)
        if understanding.preferred_date_text:
            parsed = parse_planned_date_text(understanding.preferred_date_text)
            if parsed is not None: details = replace(details, preferred_date=parsed)
        if understanding.preferred_time_text:
            parsed_time = _parse_preferred_time(understanding.preferred_time_text)
            if parsed_time is not None: details = replace(details, preferred_time=parsed_time)
        if understanding.occasion:
            values["occasion"] = understanding.occasion
        if guest_changed:
            values.pop("active_package_id", None); values.pop("standard_package_id", None)
            values["standard_package_presented"] = False

        package_id = _selected_package(details.total_guests, understanding, prior_package_id)
        if package_id: values["active_package_id"] = package_id
        context = replace(
            active, details=details, form_values=values, selected_location="coimbatore",
            last_service_code="pontoon_celebration", last_service_name="Pontoon Boat Celebration",
            active_journey="pontoon_qualification",
        )

        if understanding.intent == CustomerIntent.GREETING:
            text = _greeting_for(context, fresh)
            return _llm_result(text, context, understanding, evidence=(), business={}, reason="coimbatore_llm_greeting")

        if understanding.intent in {CustomerIntent.PACKAGE_DETAILS, CustomerIntent.PACKAGE_DISCOVERY}:
            try:
                requested = COUPLE_PACKAGE_ID if understanding.package_reference == PackageReference.COUPLE_ROMANCE else STANDARD_PACKAGE_ID if understanding.package_reference == PackageReference.STANDARD else None
                current = values.get("active_package_id")
                requested = requested or (current if current in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID} else None)
                return self._package_result(context, requested) if requested else _package_choice_result(context)
            except Exception as error:
                logger.exception("standard_package_render_failed reason=%s", type(error).__name__)
                return _llm_result(
                    "I’m unable to load the approved package details right now. Our team will help you shortly.",
                    context, understanding, evidence=(), business={"handoff_required": True},
                    reason="coimbatore_standard_package_unavailable", handoff=True,
                )

        if understanding.booking_intent or understanding.intent == CustomerIntent.BOOKING:
            if details.total_guests is None or details.preferred_date is None:
                question = "How many guests will be joining?" if details.total_guests is None else "Which date are you planning for?"
                return _llm_result(question, context, understanding, evidence=(), business={"booking_allowed": False}, reason="coimbatore_llm_booking_qualification")
            return self._handle_package_action("coimbatore_pontoon_book_standard", context)

        business = _business_output(understanding, details.total_guests, package_id)
        handoff = bool(business.get("handoff_required"))
        if handoff: context = replace(context, sales_stage=SalesStage.HANDOVER)
        elif details.preferred_date is not None and details.total_guests is not None:
            context = replace(context, sales_stage=SalesStage.QUALIFIED)

        try:
            evidence_result = self._knowledge.retrieve_evidence(
                content, topic=understanding.topic, attribute=understanding.attribute, package_id=package_id, limit=5,
            )
            evidence = evidence_result.chunks
        except Exception as error:
            logger.warning("coimbatore_rag_failed reason=%s", type(error).__name__)
            evidence = ()

        next_action, next_question = _next_action(context, understanding, handoff)
        if next_action == "ask_guest_count": context = replace(context, pending_field="total_guests")
        elif next_action == "ask_date": context = replace(context, pending_field="preferred_date")
        brief = CoimbatoreResponseBrief(
            customer_message=content, understanding=understanding, state={**compact,
                "guest_count": details.total_guests,
                "preferred_date": details.preferred_date.isoformat() if details.preferred_date else None,
                "active_package_id": package_id, "occasion": values.get("occasion")},
            evidence=tuple({"section_heading": str(row["section_heading"]), "content": str(row["content"])} for row in evidence),
            business_output=business, next_action=next_action, next_question=next_question,
        )
        text = composer.compose(brief)
        composed = text is not None
        if not composed:
            text = _safe_composer_fallback(understanding, business, next_question)
        logger.info(
            "coimbatore_understanding_mode=llm intent=%s topic=%s attribute=%s guest_update=%s "
            "package_reference=%s rag_used=%s rag_chunk_count=%s response_composer=%s grounding_status=%s",
            understanding.intent.value, understanding.topic or "none", understanding.attribute or "none",
            guest is not None, understanding.package_reference.value, bool(evidence), len(evidence),
            "llm" if composed else "fallback", "approved" if evidence else "business_only",
        )
        return _llm_result(text, context, understanding, evidence=evidence, business=business,
                           reason="coimbatore_llm_grounded", handoff=handoff)

    def _handle_package_action(self, action: str, context: ConversationContext) -> ConversationResult:
        values = dict(context.form_values or {})
        if (action == "coimbatore_pontoon_book_standard"
                and values.get("active_package_id") == STANDARD_PACKAGE_ID):
            details = context.details
            pricing = resolve_standard_package_pricing(details.total_guests)
            if pricing is None or details.preferred_date is None:
                return handle_action(action, context, public_base_url=None,
                                     standard_up_to_6_payment_configured=False)
            if not bool(getattr(self._settings, "razorpay_enabled", False)):
                fallback = handle_action(action, context, public_base_url=None,
                                         standard_up_to_6_payment_configured=False)
                metadata = dict(fallback.safe_metadata or {})
                metadata.update(approved_coimbatore_payment_response=True, package_id=STANDARD_PACKAGE_ID,
                                payment_provider="razorpay", razorpay_mode="test")
                return replace(fallback, draft_text="The secure test payment link is not configured yet. Our team will help you continue safely.",
                               safe_metadata=metadata)
            key_id = getattr(self._settings, "razorpay_key_id", None)
            key_secret = getattr(self._settings, "razorpay_key_secret", None)
            try:
                razorpay = RazorpayPaymentLinkClient(
                    key_id=key_id or "", key_secret=key_secret.get_secret_value() if key_secret else "",
                    mode=getattr(self._settings, "razorpay_mode", "test"),
                    api_base_url=getattr(self._settings, "razorpay_api_base_url", "https://api.razorpay.com/v1"),
                )
                linked = CoimbatorePaymentLinkService(self._client, razorpay).create_or_reuse(
                    customer_id=str(values.get("payment_customer_id") or ""),
                    conversation_id=str(values.get("payment_conversation_id") or ""),
                    customer_mobile=values.get("payment_customer_mobile"),
                    customer_name=details.customer_name or values.get("payment_customer_name"),
                    customer_email=values.get("customer_email"), event_date=details.preferred_date,
                    preferred_time=details.preferred_time, guest_count=details.total_guests,
                )
            except Exception as error:
                logger.error("razorpay_payment_link_failed error_category=%s", type(error).__name__)
                fallback = handle_action(action, context, public_base_url=None,
                                         standard_up_to_6_payment_configured=False)
                metadata = dict(fallback.safe_metadata or {})
                metadata.update(approved_coimbatore_payment_response=True, package_id=STANDARD_PACKAGE_ID,
                                payment_provider="razorpay", razorpay_mode="test")
                return replace(fallback, draft_text="I couldn't prepare the secure test payment link right now. Our team will help you continue safely.",
                               safe_metadata=metadata)
            values.update({"booking_ref": linked.booking["booking_ref"], "pricing_slab": pricing.slab_id,
                           "regular_price": pricing.regular_price, "offer_price": pricing.offer_price})
            updated = replace(context, form_values=values, sales_stage=SalesStage.PAYMENT_PENDING, pending_field=None)
            text = ("🎉 Your booking offer is ready!\n\n"
                    f"👥 Guests: {details.total_guests}\n💰 Offer Price: ₹{pricing.offer_price:,}/-\n\n"
                    "Complete your secure payment below to confirm your Pontoon Celebration:\n\n"
                    f"🔒 Secure Payment by Razorpay\n{linked.payment['payment_url']}")
            return ConversationResult(
                action="answer_information", draft_text=text,
                reason_code="coimbatore_razorpay_payment_link",
                detected_intent="booking", detected_location="coimbatore", response_language="en",
                human_handover_required=False, context=updated,
                safe_metadata={"response_basis":"deterministic", "structured_grounding":True,
                    "customer_response_sanitized":True, "automatic_reply_category":"information",
                    "package_id":STANDARD_PACKAGE_ID, "booking_ref":linked.booking["booking_ref"],
                    "service_code":"pontoon_celebration", "approved_coimbatore_payment_response":True,
                    "pricing_slab":pricing.slab_id, "offer_price":pricing.offer_price,
                    "offer_price_paise":pricing.offer_price_paise, "payment_link_reused":linked.reused,
                    "payment_provider":"razorpay", "razorpay_mode":"test"},
            )
        return handle_action(
            action, context, public_base_url=getattr(self._settings, "public_base_url", None),
            standard_up_to_6_payment_configured=bool(
                getattr(self._settings, "coimbatore_standard_razorpay_payment_button_id", "pl_TS1dAzTQUAPVxw")),
            standard_up_to_9_payment_configured=bool(
                getattr(self._settings, "coimbatore_standard_up_to_9_razorpay_payment_button_id", None)),
            standard_up_to_12_payment_configured=bool(
                getattr(self._settings, "coimbatore_standard_up_to_12_razorpay_payment_button_id", None)),
        )

    def _package_result(self, context: ConversationContext, package_id: str | None):
        if package_id not in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID}: raise ValueError("package_selection_required")
        pricing = resolve_standard_package_pricing(context.details.total_guests) if package_id == STANDARD_PACKAGE_ID else None
        if package_id == STANDARD_PACKAGE_ID and isinstance(context.details.total_guests, int) and context.details.total_guests > 12:
            result = self._handle_package_action("coimbatore_pontoon_customize", context)
            return replace(result, draft_text="For more than 12 guests, we'll help you with a customized quotation 😊",
                           reason_code="coimbatore_standard_custom_quote_required")
        with latency_stage("exact_KB_package_lookup"), latency_stage("YAML_load"), latency_stage("package_selection"):
            package = load_package(package_id)
        if package.fixed_guest_count is not None:
            context = replace(context, details=replace(context.details, total_guests=package.fixed_guest_count))
        media_enabled = not self._text_only_package_mode()
        with latency_stage("media_build"):
            image_url = package.media_asset if media_enabled and package.media_asset else None
        if media_enabled and package_id == STANDARD_PACKAGE_ID and image_url is None: raise ValueError("standard_package_image_unavailable")
        values = dict(context.form_values or {})
        values.update({"active_package_id": package.package_id, "package_presentation_pending": True})
        if pricing is not None:
            values.update({"pricing_slab": pricing.slab_id, "regular_price": pricing.regular_price,
                           "offer_price": pricing.offer_price})
        context = replace(context, form_values=values)
        with latency_stage("package_render"), latency_stage("add_on_render"):
            body = render_package(
                package, context.details.preferred_date, context.details.total_guests,
                None,
                default_standard_pricing=bool(values.get("use_default_standard_pricing")),
            )
        if context.details.total_guests is None:
            next_prompt = "How many guests will be joining?"
        elif context.details.preferred_date is None:
            next_prompt = "Which date are you planning for?"
        else:
            next_prompt = "What would you like to do next?"
        metadata: dict[str, Any] = {
            "response_basis": "active_rag", "source_filename": "COIMBATORE_KNOWLEDGE_BASE.md",
            "source_heading": "ACTIVE STANDARD PONTOON PACKAGE — CUSTOMER PRESENTATION" if package_id == STANDARD_PACKAGE_ID else "ACTIVE COUPLE ROMANCE PONTOON PACKAGE — CUSTOMER PRESENTATION",
            "authority": "approved_current", "customer_response_sanitized": True,
            "structured_grounding": True, "service_code": "pontoon_celebration",
            "knowledge_location": "coimbatore", "approved_coimbatore_master": True,
            "approved_package": True, "answer_source": "pontoon_package_boundary",
            "package_id": package.package_id, "package_presentation_pending": True,
            "automatic_reply_category": "information", "understanding_mode": "llm",
            "response_composer": "exact_kb_package_block", "exact_kb_package_block": True, "rag_used": False,
        }
        if pricing is not None:
            metadata.update(pricing_slab=pricing.slab_id, regular_price=pricing.regular_price,
                            offer_price=pricing.offer_price, offer_price_paise=pricing.offer_price_paise)
        if package.actions and media_enabled:
            # List messages preserve all package actions. Exotel/WhatsApp list
            # messages do not support image headers, so keep this text-only.
            with latency_stage("interactive_action_build"):
                metadata["interactive_message"] = action_message(
                    package, body=body, header_image_url=None,
                ).as_metadata()
        elif package.actions:
            with latency_stage("interactive_action_build"):
                metadata["interactive_message"] = action_message(
                    package, body=body, header_image_url=None,
                ).as_metadata()
            metadata.update(package_media_enabled=False, package_action_count=len(package.actions))
        logger.info(
            "package_content_draft_created package_id=%s media_present=%s body_present=true",
            package.package_id, image_url is not None,
        )
        logger.info(
            "package_actions_draft_created package_id=%s action_count=%s transport=%s",
            package.package_id, len(package.actions), metadata.get("interactive_message", {}).get("kind", "none"),
        )
        logger.info(
            "qualification_complete=%s package_id=%s package_body_length=%s package_media_present=%s "
            "package_media_url_host=%s package_action_count=%s package_interactive_type=%s",
            context.details.preferred_date is not None and (
                context.details.total_guests is not None
            ),
            package.package_id, len(body), image_url is not None,
            "coimbatore-chatbot.s3.ap-south-1.amazonaws.com" if image_url else "none",
            len(package.actions), metadata.get("interactive_message", {}).get("kind", "none"),
        )
        return ConversationResult(
            action="answer_information", draft_text=body, reason_code="coimbatore_exact_kb_package",
            detected_intent="package_details", detected_location="coimbatore", response_language="en",
            human_handover_required=False, context=context, safe_metadata=metadata,
        )

    def _default_standard_package_result(self, context: ConversationContext) -> ConversationResult:
        """Present approved entry-slab details without inventing missing facts."""
        saved_details = context.details
        values = dict(context.form_values or {})
        values.update({
            "active_package_id": STANDARD_PACKAGE_ID,
            "use_default_standard_pricing": True,
        })
        fallback_context = replace(
            context,
            details=replace(context.details, preferred_date=None, preferred_time=None, total_guests=None),
            form_values=values,
            pending_field=None,
            selected_location="coimbatore",
            last_service_code="pontoon_celebration",
            last_service_name="Pontoon Boat Celebration",
            active_journey="pontoon_qualification",
        )
        fallback = self._package_result(fallback_context, STANDARD_PACKAGE_ID)
        metadata = dict(fallback.safe_metadata or {})
        metadata.update({
            "default_package_fallback": True,
            "default_pricing_slab": "up_to_6",
            "understanding_mode": "deterministic_fallback",
        })
        return replace(
            fallback,
            context=replace(fallback.context, details=saved_details),
            safe_metadata=metadata,
        )

    def _returning_customer_menu_result(self, context: ConversationContext) -> ConversationResult:
        values = dict(context.form_values or {})
        values.update({
            "active_package_id": STANDARD_PACKAGE_ID,
            "returning_customer_menu_shown": True,
        })
        updated = replace(
            context,
            form_values=values,
            selected_location="coimbatore",
            last_service_code="pontoon_celebration",
            last_service_name="Pontoon Boat Celebration",
            pending_field=None,
        )
        interactive = returning_customer_menu()
        return ConversationResult(
            action="answer_information",
            draft_text=interactive.body,
            reason_code="coimbatore_returning_customer_menu",
            detected_intent="greeting",
            detected_location="coimbatore",
            response_language="en",
            human_handover_required=False,
            context=updated,
            safe_metadata={
                "response_basis": "deterministic",
                "structured_grounding": True,
                "customer_response_sanitized": True,
                "automatic_reply_category": "information",
                "service_code": "pontoon_celebration",
                "package_id": STANDARD_PACKAGE_ID,
                "returning_customer_menu": True,
                "interactive_message": interactive.as_metadata(),
                "interactive_message_type": "buttons",
            },
        )

    def confirm_standard_package_presented(self, result: ConversationResult, customer_id: str, conversation_id: str) -> bool:
        """Commit presentation state only after the outbound sequence is accepted."""
        metadata = result.safe_metadata or {}
        package_id = metadata.get("package_id")
        if package_id not in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID} or not metadata.get("package_presentation_pending"):
            return False
        values = dict(result.context.form_values or {})
        values.update({"active_package_id": package_id, "standard_package_presented": True,
                       "package_presentation_pending": False})
        updated = replace(result.context, form_values=values, sales_stage=SalesStage.PACKAGE_PRESENTED)
        record = _context_to_record(updated)
        if self._sales_state_is_persistent():
            committed = self._contexts.save_service_context(conversation_id, customer_id, record)
        else:
            key = self._session_state_key(customer_id, conversation_id)
            committed = key is not None
            if key is not None:
                self._session_states()[key] = record
        logger.info("package_presented_committed package_id=%s committed=%s", package_id, committed)
        return committed


def _is_greeting(text: object) -> bool:
    return isinstance(text, str) and bool(re.fullmatch(r"\s*(?:hi+|hello+|hey+)\s*[!.?]*\s*", text, re.I))


def _is_coimbatore_location_question(text: object) -> bool:
    return isinstance(text, str) and bool(re.search(
        r"\b(?:address|location|located|where is (?:your|the) (?:site|park)|google maps?|map link|how (?:do|can) i reach)\b",
        text, re.I,
    ))


def _coimbatore_text_context(context: ConversationContext) -> ConversationContext:
    values = dict(context.form_values or {})
    values["active_package_id"] = STANDARD_PACKAGE_ID
    return replace(
        context, form_values=values, selected_location="coimbatore",
        last_service_code="pontoon_celebration", last_service_name="Pontoon Boat Celebration",
        active_journey="pontoon_qualification",
    )


def _parse_text_entry_date(text: str):
    direct = parse_planned_date_text(text)
    if direct is not None:
        return direct
    match = re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b", text)
    return parse_planned_date_text(match.group(0)) if match else None


def _text_entry_result(text: str, context: ConversationContext, reason: str) -> ConversationResult:
    return ConversationResult(
        action="answer_information", draft_text=text, reason_code=reason,
        detected_intent="qualification", detected_location="coimbatore", response_language="en",
        human_handover_required=False, context=context,
        safe_metadata={
            "response_basis": "deterministic", "structured_grounding": True,
            "customer_response_sanitized": True, "service_code": "pontoon_celebration",
            "knowledge_location": "coimbatore", "automatic_reply_category": "information",
            "coimbatore_pontoon_mvp": True, "answer_source": "structured_grounding",
        },
    )


def _is_development_reset(text: object) -> bool:
    return isinstance(text, str) and bool(
        re.fullmatch(r"\s*(?:restart|start\s+over|reset\s+conversation)\s*[!.?]*\s*", text, re.I)
    )


def _package_choice_result(context: ConversationContext) -> ConversationResult:
    text = ("We have two Pontoon Celebration options 😊\n"
            "• Couple Romance — ₹3,999\n"
            "• Standard Pontoon Celebration — ₹5,999\n\n"
            "Which one would you like to see?")
    return ConversationResult(
        action="answer_information", draft_text=text, reason_code="coimbatore_package_choice_required",
        detected_intent="package_discovery", detected_location="coimbatore", response_language="en",
        human_handover_required=False, context=context,
        safe_metadata={"response_basis":"deterministic", "structured_grounding":True,
                       "customer_response_sanitized":True, "service_code":"pontoon_celebration",
                       "knowledge_location":"coimbatore", "approved_coimbatore_master":True,
                       "source_filename":"COIMBATORE_KNOWLEDGE_BASE.md",
                       "source_heading":"Active Package Presentations",
                       "automatic_reply_category":"information", "package_choice_required":True,
                       "rag_used":False, "raipur_retrieval_used":False},
    )


def _validated_guest_update(message: str, understanding: CoimbatoreUnderstanding) -> int | None:
    if not understanding.guest_count_explicit or understanding.guest_count is None:
        return None
    if (understanding.topic or "").casefold() in {"cake", "duration", "pyro", "price", "photoshoot", "drone"}:
        return None
    guest_language = re.search(
        r"\b(?:guests?|people|persons?|members?|pax|family\s+of|we\s+are|hum\s+|couple|wife|husband|two\s+of\s+us|both\s+of\s+us|make\s+it)\b",
        message, re.I,
    )
    if guest_language or understanding.intent == CustomerIntent.QUALIFICATION_UPDATE and understanding.mentioned_number is None:
        return understanding.guest_count
    return None


def _parse_preferred_time(value: str):
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", value, re.I)
    if not match: return None
    hour, minute, period = int(match.group(1)), int(match.group(2) or 0), match.group(3).casefold()
    if not 1 <= hour <= 12 or minute > 59: return None
    if period == "pm" and hour != 12: hour += 12
    if period == "am" and hour == 12: hour = 0
    return datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()


def _selected_package(guests: int | None, understanding: CoimbatoreUnderstanding, current: object) -> str | None:
    if understanding.package_reference == PackageReference.STANDARD: return "coimbatore_pontoon_standard"
    if understanding.package_reference == PackageReference.COUPLE_ROMANCE: return COUPLE_PACKAGE_ID
    if understanding.package_reference == PackageReference.FAMILY_FRIENDS: return "family_friends"
    if current in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID}: return str(current)
    return None


def _business_output(understanding: CoimbatoreUnderstanding, guests: int | None, package_id: str | None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "selected_package_id": package_id, "guest_count": guests,
        "availability_verified": False, "payment_verified": False,
        "booking_confirmed": False, "handoff_required": False,
    }
    if package_id == COUPLE_PACKAGE_ID:
        output.update(selected_package_name="Pontoon Couple Romance Celebration", price_inr=3999)
    elif package_id == "family_friends" and isinstance(guests, int):
        output.update(selected_package_name="Pontoon Family & Friends Celebration",
                      price_inr=6000 if guests <= 6 else 7500 if guests <= 9 else 9000)
    elif package_id == "coimbatore_pontoon_standard":
        output.update(selected_package_name="Pontoon Boat Celebration Package", price_inr=5999)
    if isinstance(guests, int) and guests > 12 and package_id not in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID}:
        output.update(selected_package_id=None, selected_package_name=None, price_inr=None,
                      handoff_required=True, handoff_reason="group_over_12")
    if understanding.intent == CustomerIntent.AVAILABILITY or understanding.availability_intent:
        output.update(handoff_required=True, handoff_reason="live_availability_unverified")
    if understanding.intent == CustomerIntent.PAYMENT or understanding.payment_intent:
        output.update(handoff_required=True, handoff_reason="payment_unverified")
    if understanding.intent == CustomerIntent.DISCOUNT:
        output.update(handoff_required=True, handoff_reason="discount_requires_team")
    if understanding.intent == CustomerIntent.HUMAN_HANDOFF or understanding.handoff_intent:
        output.update(handoff_required=True, handoff_reason="customer_requested_human")
    return output


def _next_action(context: ConversationContext, understanding: CoimbatoreUnderstanding, handoff: bool) -> tuple[str, str | None]:
    if handoff: return "human_handoff", None
    progressing = understanding.intent in {
        CustomerIntent.QUALIFICATION_UPDATE, CustomerIntent.PACKAGE_DISCOVERY,
        CustomerIntent.OCCASION, CustomerIntent.BOOKING,
    }
    if progressing and context.details.total_guests is None:
        return "ask_guest_count", "How many guests will be joining?"
    if progressing and context.details.preferred_date is None:
        return "ask_date", "Which date are you planning for?"
    return "continue", None


def _greeting_for(context: ConversationContext, fresh: bool) -> str:
    if fresh:
        return "Hi 👋 Welcome to Entartica Coimbatore.\nI'll help you plan your Pontoon Celebration 🎉\n\nHow many guests are you planning for, and which date?"
    if context.details.total_guests is None: return "Hi 😊 How many guests will be joining?"
    if context.details.preferred_date is None: return "Hi 😊 Which date are you planning your Pontoon Celebration for?"
    return "Hi 😊 Ready to continue with your Pontoon Celebration?"


def _safe_composer_fallback(understanding: CoimbatoreUnderstanding, business: dict[str, Any], next_question: str | None) -> str:
    reason = business.get("handoff_reason")
    if reason == "live_availability_unverified":
        return "I can't confirm live availability yet. Our team will verify the requested slot for you."
    if reason == "payment_unverified":
        return "I can't verify payment status here. Our team will check it and assist you."
    if reason == "discount_requires_team":
        return "Discounts need confirmation from our team. I'll have them assist you."
    if reason == "group_over_12":
        return "For more than 12 guests, our team will help with the suitable celebration arrangement."
    name, price = business.get("selected_package_name"), business.get("price_inr")
    if understanding.intent in {CustomerIntent.QUALIFICATION_UPDATE, CustomerIntent.PACKAGE_DISCOVERY} and name and price:
        answer = f"{name} is the applicable package at ₹{price:,}."
        return f"{answer}\n\n{next_question}" if next_question else answer
    if next_question: return next_question
    return "I don't have an approved detail for that yet. Our team can help clarify it."


def _llm_result(text: str, context: ConversationContext, understanding: CoimbatoreUnderstanding, *,
                evidence: tuple[Any, ...], business: dict[str, Any], reason: str, handoff: bool = False) -> ConversationResult:
    source_heading = str(evidence[0].get("section_heading")) if evidence else None
    metadata = {
        "response_basis": "active_rag" if evidence else "deterministic",
        "source_filename": "COIMBATORE_KNOWLEDGE_BASE.md" if evidence else None,
        "source_heading": source_heading, "authority": "approved_current" if evidence else "business_rule",
        "customer_response_sanitized": True, "structured_grounding": True,
        "service_code": "pontoon_celebration", "knowledge_location": "coimbatore",
        "approved_coimbatore_master": bool(evidence), "coimbatore_pontoon_mvp": True,
        "answer_source": "approved_coimbatore_llm" if evidence else "structured_grounding",
        "understanding_mode": "llm", "response_composer": "llm",
        "rag_used": bool(evidence), "rag_chunk_count": len(evidence),
        "topic": understanding.topic, "attribute": understanding.attribute,
        "requires_live_data": business.get("handoff_reason") in {"live_availability_unverified", "payment_unverified"},
        "automatic_reply_category": "information",
    }
    return ConversationResult(
        action="general_human_handover" if handoff else "answer_information", draft_text=text,
        reason_code=reason, detected_intent=understanding.intent.value, detected_location="coimbatore",
        response_language="en", human_handover_required=handoff, context=context, safe_metadata=metadata,
    )

def _collect_booking_details(text: object, context: ConversationContext):
    from app.services.raipur.response_models import ConversationResult
    value = text.strip() if isinstance(text, str) else ""
    details = context.details
    if context.pending_field == "customer_name" or details.customer_name is None:
        name = re.sub(r"^(?:my name is|i am|i'm)\s+", "", value, flags=re.I).strip()
        if not name or any(char.isdigit() for char in name):
            reply, updated = "Please share your name.", replace(context, pending_field="customer_name")
        else:
            updated = replace(context, details=replace(details, customer_name=name), pending_field="preferred_time")
            reply = "What time would you prefer? Please include AM or PM."
    else:
        preferred = _parse_preferred_time(value)
        if preferred is None and re.fullmatch(r"\s*am\s*[!.?]*\s*", value, re.I):
            reply, updated = ("Sure 😊 What time in the morning would you prefer? For example, 10 AM.",
                              replace(context, pending_field="preferred_time"))
        elif preferred is None and re.fullmatch(r"\s*pm\s*[!.?]*\s*", value, re.I):
            reply, updated = ("Sure 😊 What time in the evening would you prefer? For example, 6 PM.",
                              replace(context, pending_field="preferred_time"))
        elif preferred is None:
            reply, updated = "What time would you prefer? Please include AM or PM.", replace(context, pending_field="preferred_time")
        else:
            updated = replace(context, details=replace(details, preferred_time=preferred), pending_field=None, sales_stage=SalesStage.DETAILS_COLLECTED)
            guests = details.total_guests or 0
            amount = "₹3,999" if guests == 2 else "₹6,000" if guests <= 6 else "₹7,500" if guests <= 9 else "₹9,000"
            package_name = "Pontoon Couple Romance Celebration" if guests == 2 else "Pontoon Family & Friends Celebration"
            reply = (f"🎉 Your Celebration Summary\n\nDate: {details.preferred_date.strftime('%d %b %Y')}\nGuests: {guests}\n"
                     f"Package: {package_name}\nAmount: {amount}\nPayment: 100% advance\n\n"
                     "Secure payment integration is not available yet. Our team will assist with the next approved step.")
    return ConversationResult(action="answer_information", draft_text=reply, reason_code="coimbatore_booking_details",
        detected_intent="booking", detected_location="coimbatore", response_language="en", human_handover_required=False,
        context=updated, safe_metadata={"response_basis":"deterministic","structured_grounding":True,"customer_response_sanitized":True,
        "service_code":"pontoon_celebration","automatic_reply_category":"information"})
