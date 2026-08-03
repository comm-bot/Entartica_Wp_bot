"""Draft-only Raipur inbound orchestration; it has no Exotel or provider-send path."""
from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import logging
import re
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, approved_primary_service_from_question, approved_service_from_message, approved_service_alias_used, is_active_approved_service, knowledge_service_code
from app.services.raipur_responses import RaipurResponseRequest, present
from app.services.raipur_answers import compose_customer_response
from app.services.raipur_conversational_fallback import RaipurConversationalFallback
from app.services.raipur_dialogue_planner import RaipurDialoguePlanner, is_participation_eligibility_question, _service_question_topic
from app.services.raipur_sales_contact import SalesContact, approved_safe_fallback, booking_sales_handover, controlled_sales_handover, direct_human_handover
from app.config import get_settings
from app.services.latency import latency_stage

logger = logging.getLogger("uvicorn.error")

Action = Literal["answer_information", "ask_booking_field", "check_availability", "booking_enquiry_saved", "pricing_sales_handover", "unsupported_location_handover", "low_confidence_handover", "general_human_handover"]

@dataclass(frozen=True)
class KnowledgeDraft:
    text: str | None
    source_filename: str | None = None
    confidence: float | None = None
    low_confidence: bool = True
    section_heading: str | None = None
    retrieval_result_count: int | None = None
    source_document_id: str | None = None
    retrieved_section_headings: tuple[str, ...] = ()

class KnowledgeAnswerProvider(Protocol):
    def answer(self, question: str) -> KnowledgeDraft: ...

class DraftRepository(Protocol):
    def create_outbound_draft(self, **kwargs: Any) -> tuple[dict[str, Any], bool]: ...

@dataclass(frozen=True)
class ConversationContext:
    details: BookingDetails
    pending_field: str | None = None
    availability_requested: bool = False
    last_service_name: str | None = None
    last_service_code: str | None = None
    last_intent: str | None = None
    last_bot_action: str | None = None
    service_selection_prompted: bool = False
    service_details_requested: bool = False
    active_domain: str = "entartica"
    active_topic: str | None = None
    active_entity_type: str | None = None
    active_entity_name: str | None = None
    last_user_intent: str | None = None
    last_assistant_answer_summary: str | None = None
    pending_clarification: bool = False
    pending_clarification_type: str | None = None
    pending_clarification_options: tuple[str, ...] = ()
    preferred_language: str | None = None
    last_assistant_question: str | None = None
    pending_question_type: str | None = None
    pending_action: str | None = None
    pending_entity_type: str | None = None
    pending_entity_name: str | None = None
    pending_created_at: str | None = None
    pending_service_code: str | None = None
    pending_slots: dict[str, str | None] | None = None
    last_answer_source: str | None = None
    last_answer_sections: tuple[str, ...] = ()

@dataclass(frozen=True)
class ConversationResult:
    action: Action
    draft_text: str
    reason_code: str
    detected_intent: str
    detected_location: str
    response_language: str
    human_handover_required: bool
    booking_enquiry_created: bool = False
    booking_enquiry_updated: bool = False
    availability_status: str | None = None
    next_required_field: str | None = None
    draft_only: bool = True
    draft_saved: bool = False
    context: ConversationContext | None = None
    safe_metadata: dict[str, Any] | None = None
    template_key: str | None = None
    response_valid: bool = True
    response_validation_reason: str = "safe"

_PRICING = re.compile(r"\b(price|pricing|quotation|quote|rate|cost)\b", re.I)
_AVAILABILITY = re.compile(r"\b(slot|availability|available)\b", re.I)
_BOOKING = re.compile(r"\b(book|booking|enquiry|reservation|reserve|arrange\s+booking)\b", re.I)
_HUMAN = re.compile(r"\b(human|person|agent|sales|customer\s+care|contact(?:\s+details)?|payment|refund|cancel|complaint|medical|emergency|confirm|custom\s+(?:package|arrangement))\b", re.I)
_DIRECT_CONTACT = re.compile(
    r"\b(?:number|nmbr|phone|contact)\s+(?:send|bhejo|bh[eé]j|do|kro)\b"
    r"|\b(?:team|sales(?:\s+team)?|customer\s+care|jetty\s+gazebo)\s+(?:ka|ki|ke)?\s*(?:number|nmbr|no\.?|contact)\b"
    r"|\b(?:sales(?:\s+team)?|contact|phone|call)\s+(?:number|details?)\b"
    r"|\b(?:connect\s+me\s+to\s+sales|(?:i\s+want\s+to\s+)?speak\s+with\s+(?:a\s+)?person|kisi\s+se\s+baat\s+karni\s+hai|contact\s+details\s+(?:bhejo|send|do))\b",
    re.I,
)
_UNSUPPORTED = re.compile(r"\b(in|at)\s+(indore|delhi)\b", re.I)
_LOCATION_QUESTION = re.compile(r"\b(where|located|location|address|map|kahan|kahaan)\b|\u0915\u0939\u093e\u0901", re.I)
_SERVICE_LIST_QUESTION = re.compile(r"\b(?:various|different|all|available|list|options?|show|tell\s+me)\b[^.?!]{0,40}\b(?:rides?|activities|services?)\b|\b(?:rides?|activities|services?)\b[^.?!]{0,30}\b(?:available|list|options?|hain|hai|batao)\b|\bwhat\s+(?:are\s+the\s+)?rides\b|\bhow\s+many\s+(?:rides|activities|services)\b|\b(?:can\s+you\s+provide|show\s+me|any)\s+(?:other\s+)?(?:rides?|activities|services?)\b|\bwhat\s+else\s+do\s+you\s+have\b|\b(?:aur\s+(?:kaun\s+si|kaun\s+kaun)\s+)?(?:rides?|activities)\s+(?:hain|hai|batao)\b|\bdusri\s+rides?|baaki\s+rides?|aur\s+kya\s+hai\b|\braipur\s+(ki|mein)\s+(activity|activities|services?)\s+(kya|hain|hai)\b", re.I)
_CELEBRATION_LIST_QUESTION = re.compile(r"\b(celebration|party|birthday)\b.*\b(options?|services?|activities|available|offer|book)\b|\b(what|which|show|list)\b.*\b(celebration|party)\b|\b(celebration|party)\s+(options?|services?)\s*(kya|hain|hai|batao)\b|\bparty\s+ke\s+liye\b|\u0938\u0947\u0932\u093f\u092c\u094d\u0930\u0947\u0936\u0928.*\u0935\u093f\u0915\u0932\u094d\u092a", re.I)
_LIVE_AVAILABILITY_SIGNAL = re.compile(r"\b(today|tomorrow|tonight|date|time|slot|seats?|capacity|am|pm|aaj|kal)\b", re.I)
_SERVICE_DETAIL = re.compile(r"\b(tell me about|information about|give (?:me )?(?:information|details)|details? (?:of|about)|what can you tell me about|want to (?:know|learn) about|(?:can i )?know more(?: about it)?|more information (?:on|about) (?:this|it)|how many (?:rides|activities|services) are included|ke baare mein|iske baare mein|aur information|tell me more|can you (?:give|explain)|can you tell (?:(?:me|em) )?more|give me|details do|aur batao|what is included|is breakfast included|what about children|how long is it|is swimming required|more information please|iska detail batao)\b|\u0907\u0938\u0915\u0947\s+\u092c\u093e\u0930\u0947\s+\u092e\u0947\u0902|\u0907\u0938\u0915\u0940\s+\u092a\u0942\u0930\u0940\s+\u091c\u093e\u0928\u0915\u093e\u0930\u0940|\u0935\u093f\u0938\u094d\u0924\u093e\u0930\s+\u0938\u0947\s+\u092c\u0924\u093e\u0907\u090f", re.I)
_SERVICE_CONFIRMATION = re.compile(r"\bdo\s+you\s+(?:offer|have)\b|\bis\s+.+\s+(?:offered|available\s+as\s+a\s+service)\b|\bkya\s+raipur\s+mein.+\b(?:hai|available)\b|\u0915\u094d\u092f\u093e\s+\u0930\u093e\u092f\u092a\u0941\u0930\s+\u092e\u0947\u0902.*\u0909\u092a\u0932\u092c\u094d\u0927|\u0915\u094d\u092f\u093e\s+.+\s+\u0939\u0948", re.I)
_SERVICE_DEFINITION = re.compile(r"\b(?:what\s+is|what\s+does\s+.+\s+mean|explain|what\s+kind\s+of\s+activity\s+is|tell\s+me\s+what\s+it\s+is|how\s+does\s+it\s+work|kya\s+hai|kya\s+hota\s+hai|kya\s+chiz\s+hai|kya\s+cheez\s+hoti\s+hai|matlab\s+kya\s+hai|iske\s+baare\s+mein\s+samjhao|ye\s+activity\s+kya\s+hai|mera\s+matlab)\b|\u0915\u094d\u092f\u093e\s+\u0939\u0948|\u0915\u094d\u092f\u093e\s+\u0939\u094b\u0924\u093e\s+\u0939\u0948|\u0907\u0938\u0915\u093e\s+\u092e\u0924\u0932\u092c\s+\u0915\u094d\u092f\u093e\s+\u0939\u0948", re.I)
_SELF_INTRO = re.compile(
    r"\b(?:who\s+are\s+you|what\s+are\s+you|introduce\s+yourself|tell\s+me\s+about\s+yourself|"
    r"your\s+name|who\s+am\s+i\s+talking\s+to|are\s+you\s+(?:a\s+)?bot|are\s+you\s+human|"
    r"apne\s+bare\s+(?:mein|me)|apne\s+baare\s+mein|pehle\s+apne|tum\s+kya\s+ho|"
    r"tum\s+kaun\s+ho|aap\s+kaun\s+ho|apna\s+introduction\s+do|tumhara\s+naam\s+kya\s+hai|"
    r"main\s+kis\s+se\s+baat\s+kar\s+raha\s+hoon|bot\s+ho\s+kya)\b|\u0906\u092a\s+\u0915\u094c\u0928",
    re.I,
)
_CURRENT_AFFAIRS = re.compile(r"\b(?:prime minister|president|chief minister|election|news|weather|current\s+(?:office|minister|leader))\b", re.I)
_RAIPUR_TRAVEL = re.compile(r"\b(?:raipur\s+(?:kaise|how)\s+(?:ja|reach)|how\s+to\s+reach\s+raipur|travel\s+to\s+raipur)\b", re.I)
_RAIPUR_CITY = re.compile(r"\braipur\s+city\b|\braipur\s+shehar\b", re.I)
_RAIPUR_CITY_GEOGRAPHY = re.compile(r"\b(?:raipur\s+(?:city|shehar)\s+(?:kaha|kahaan|where)|where\s+is\s+raipur\s+city|raipur\s+kis\s+state)\b", re.I)
_ENTARTICA_SCOPE = re.compile(r"\b(?:entartica|sea world)\b", re.I)
_FRUSTRATION = re.compile(r"\b(?:bewakoof|bewkuf|not understanding|maine\s+kuch\s+aur|maine\s+raipur\s+city|galat\s+jawab|listen properly|same answer|sahi context|no\s+first|that\s+is\s+not\s+what\s+i\s+asked|why\s+can(?:not|'t)\s+you\s+provide|you\s+are\s+not\s+answering|pehle\s+details|information\s+nahi\s+de)\b", re.I)
_H2O_PLAY_PARK = re.compile(r"\bh2o\s+play\s+park\b", re.I)
_LANGUAGE_HINDI = re.compile(r"\b(?:hindi|hindi mein|hindi me)\s+(?:mein\s+)?(?:bolo|baat|bol)\b|\u0939\u093f\u0902\u0926\u0940\s+\u092e\u0947\u0902", re.I)
_LANGUAGE_ENGLISH = re.compile(r"\benglish\s+(?:mein\s+)?(?:bolo|baat|bol)\b", re.I)
_LANGUAGE_HINGLISH = re.compile(r"\bhinglish\s+(?:mein\s+)?(?:bolo|baat|bol)\b", re.I)
_AFFIRMATIVE = re.compile(r"^(?:haan|han|ha|yes|yep|ji)\.?$", re.I)
_ENQUIRY_CANCEL = re.compile(r"\b(?:cancel\s+(?:enquiry|booking)|stop\s+(?:enquiry|booking)|enquiry\s+cancel)\b", re.I)
_ENQUIRY_RESTART = re.compile(r"\b(?:start\s+again|restart\s+(?:enquiry|booking)|new\s+enquiry)\b", re.I)
_AMBIGUOUS_SEATER = re.compile(r"\b(?:twin|twins|two|double)[ -]?seater\b", re.I)

class RaipurConversationService:
    def __init__(self, *, knowledge: KnowledgeAnswerProvider, bookings: BookingEnquiryService, drafts: DraftRepository, services: Any | None = None, location: dict[str, Any] | None = None, timezone_name: str = "Asia/Kolkata", persist_drafts: bool = True, conversational_fallback: RaipurConversationalFallback | None = None, dialogue_planner: RaipurDialoguePlanner | None = None, sales_contact: SalesContact | None = None) -> None:
        self._knowledge, self._bookings, self._drafts = knowledge, bookings, drafts
        self._services, self._location = services, location
        self._persist_drafts = persist_drafts
        self._conversational_fallback = conversational_fallback or RaipurConversationalFallback()
        self._dialogue_planner = dialogue_planner or RaipurDialoguePlanner()
        self._sales_contact = sales_contact or SalesContact.from_settings(get_settings())
        try:
            self._timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            # Asia/Kolkata has no DST; Windows Python installations may lack IANA data.
            if timezone_name != "Asia/Kolkata":
                raise
            self._timezone = timezone(timedelta(hours=5, minutes=30))

    def process(self, message: NormalizedInboundMessage, *, customer: dict[str, Any], conversation: dict[str, Any], source_message_id: str, current_state: ConversationContext | None = None, now: datetime | None = None) -> ConversationResult:
        text = (message.content or "").strip(); routing_text = _normalize_intent_text(text); language = _language(text); now = now or datetime.now(self._timezone)
        context = current_state or ConversationContext(BookingDetails(customer.get("name"), None, None, None, None, None, None, special_requirements_collected=False))
        requested_language = _requested_language(routing_text)
        if requested_language:
            updated = replace(context, preferred_language=requested_language)
            return self._save("answer_information", _language_changed(requested_language), "language_preference_updated", "language_preference", requested_language, False, customer, conversation, source_message_id, updated, metadata={"response_basis": "deterministic", "customer_response_sanitized": True})
        if context.preferred_language in {"en", "hi", "hinglish"} and not re.search(r"[\u0900-\u097f]", text) and len(text.split()) <= 8:
            language = context.preferred_language
        with latency_stage("dialogue_planner"):
            plan = self._dialogue_planner.plan(routing_text, context, language=language)
        language = plan.language
        repair_requested = _is_service_repair_request(routing_text, context)
        if _is_direct_contact_request(routing_text):
            contact_context = replace(
                context,
                pending_field=None,
                availability_requested=False,
                pending_question_type=None,
                pending_action=None,
                pending_entity_type=None,
                pending_entity_name=None,
                pending_created_at=None,
                pending_service_code=None,
                pending_slots=None,
                active_topic="entartica_sales_contact",
                active_entity_type="organization",
                active_entity_name="Entartica sales team",
            )
            return self._save(
                "general_human_handover",
                direct_human_handover(self._sales_contact, language),
                "direct_contact_details",
                "human_contact_request",
                language,
                True,
                customer,
                conversation,
                source_message_id,
                contact_context,
                metadata={
                    "response_basis": "deterministic",
                    "structured_grounding": True,
                    "customer_response_sanitized": True,
                    "response_mode": "direct_contact_details",
                    "automatic_reply_category": "information",
                },
            )
        location_follow_up = _is_location_follow_up(routing_text, context)
        location_correction = _is_location_correction(routing_text)
        if _AFFIRMATIVE.fullmatch(routing_text) and _is_pending_location_map_action(context):
            location_answer = _structured_location_answer(self._location, language)
            if location_answer:
                return self._save("answer_information", location_answer, "structured_location", "location", language, False, customer, conversation, source_message_id, _location_context(context), metadata=_structured_metadata(False, False, False))
        if (location_follow_up or location_correction or _is_location_question(routing_text)) and not _is_raipur_city_geography_question(routing_text) and not _RAIPUR_TRAVEL.search(routing_text):
            location_answer = _structured_location_answer(self._location, language)
            location_context = _location_context(context)
            if location_answer:
                metadata = _structured_metadata(False, False, False)
                if location_correction:
                    metadata |= {"response_basis": "conversation_repair", "location_correction": True}
                return self._save("answer_information", location_answer, "structured_location", "location", language, False, customer, conversation, source_message_id, location_context, metadata=metadata)
            # An explicit location request must never fall through into a stale
            # service context when structured location data is unavailable.
            return self._save("answer_information", approved_safe_fallback(self._sales_contact, language), "location_information_unavailable", "location", language, True, customer, conversation, source_message_id, location_context, metadata={"response_basis": "clarification", "approved_safe_fallback": True, "customer_response_sanitized": True})
        if _AFFIRMATIVE.fullmatch(routing_text) and context.pending_question_type == "yes_no" and context.pending_action == "provide_service_details" and context.pending_service_code:
            service = next((item for item in _all_approved_services() if item.slug.replace("-", "_") == context.pending_service_code), None)
            if service is not None:
                detail_context = replace(context, pending_question_type=None, pending_action=None, pending_service_code=None, last_service_name=service.name, last_service_code=service.slug.replace("-", "_"))
                detail = self._service_detail(text, service.name, contextual_follow_up=True)
                answer = detail.text if detail is not None else _service_detail_fallback(service.name, language)
                return self._save("answer_information", answer, "approved_service_detail" if detail else "service_detail_unavailable", "service_detail", language, False, customer, conversation, source_message_id, detail_context, metadata={"response_basis": "active_rag" if detail else "clarification", "customer_response_sanitized": True, "source_filename": detail.source_filename if detail else None})
        if _ENQUIRY_CANCEL.search(routing_text):
            cleared = replace(context, pending_field=None, pending_question_type=None, pending_action=None, availability_requested=False)
            return self._save("answer_information", "Your booking enquiry collection has been stopped. You can start a new enquiry anytime.", "booking_enquiry_cancelled", "booking", language, False, customer, conversation, source_message_id, cleared, metadata={"response_basis":"deterministic","customer_response_sanitized":True})
        if _ENQUIRY_RESTART.search(routing_text):
            reset = replace(context, details=replace(context.details, requested_service_text=None, preferred_date=None, preferred_time=None, adults_count=None, children_count=None, total_guests=None, special_requirements=None, special_requirements_collected=False), pending_field="requested_service_text", pending_question_type=None, pending_action=None, availability_requested=False)
            return self._save("ask_booking_field", _ask("requested_service_text", language), "booking_detail_required", "booking", language, False, customer, conversation, source_message_id, reset, next_field="requested_service_text", metadata={"response_basis":"deterministic","customer_response_sanitized":True})
        if _is_celebration_list_question(routing_text):
            services = self._active_celebration_services(conversation.get("location_id"))
            if services:
                celebration_context = replace(_catalogue_context(context, "celebration_catalogue"), service_selection_prompted=True)
                return self._save("answer_information", _celebration_service_list_answer(services, language), "structured_celebration_service_list", "celebration_service_list", language, False, customer, conversation, source_message_id, celebration_context, metadata=_structured_metadata(False, False, True) | {"automatic_reply_category": "services"})
        if plan.intent == "service_list" or _is_service_list_question(routing_text):
            services = self._active_approved_services(conversation.get("location_id"))
            if services:
                return self._save("answer_information", _service_list_answer(services, language), "structured_service_list", "service_catalogue", language, False, customer, conversation, source_message_id, _catalogue_context(context, "service_catalogue"), metadata=_structured_metadata(False, False, True))
        if _AFFIRMATIVE.fullmatch(routing_text) and context.pending_question_type == "yes_no" and context.pending_action == "start_booking_enquiry":
            consent = replace(context, pending_question_type=None, pending_action=None)
            return self._booking("", consent, customer, conversation, source_message_id, language, now, availability_requested=False)
        if _BOOKING.search(routing_text) and not _PRICING.search(routing_text) and not _is_live_availability_request(routing_text):
            return self._booking_sales_handover(routing_text, context, customer, conversation, source_message_id, language)
        if context.pending_field:
            explicit = approved_primary_service_from_question(routing_text)
            if explicit is not None and context.pending_field != "requested_service_text":
                context = replace(context, details=replace(context.details, requested_service_text=explicit.name), last_service_name=explicit.name, last_service_code=explicit.slug.replace("-", "_"))
            return self._booking(text, context, customer, conversation, source_message_id, language, now, availability_requested=context.availability_requested)
        if plan.intent == "greeting":
            return self._save("answer_information", _greeting(language), "greeting", "greeting", language, False, customer, conversation, source_message_id, context, metadata={"response_basis": "deterministic", "customer_response_sanitized": True})
        if context.pending_clarification and context.pending_clarification_type == "destination_scope":
            if _RAIPUR_CITY.search(routing_text):
                resolved = replace(context, active_domain="raipur_city", active_topic="travel_to_raipur_city", active_entity_type="place", active_entity_name="Raipur city", pending_clarification=False, pending_clarification_type=None, pending_clarification_options=())
                return self._save("answer_information", _raipur_city_travel(language), "raipur_city_travel", "raipur_city_travel", language, False, customer, conversation, source_message_id, resolved, metadata={"response_basis": "general_stable_knowledge", "customer_response_sanitized": True})
            if _ENTARTICA_SCOPE.search(routing_text):
                resolved = replace(context, pending_clarification=False, pending_clarification_type=None, pending_clarification_options=())
                location_answer = _structured_location_answer(self._location, language)
                if location_answer:
                    return self._save("answer_information", location_answer, "structured_location", "location", language, False, customer, conversation, source_message_id, _location_context(resolved), metadata=_structured_metadata(False, False, False))
        if _FRUSTRATION.search(routing_text) and not repair_requested:
            if context.active_domain == "raipur_city" or context.pending_clarification_type == "destination_scope":
                repaired = replace(context, active_domain="raipur_city", active_topic="travel_to_raipur_city", pending_clarification=False, pending_clarification_type=None, pending_clarification_options=())
                return self._save("answer_information", _raipur_city_repair(language), "conversation_repair", "conversation_repair", language, False, customer, conversation, source_message_id, repaired, metadata={"response_basis": "conversation_repair", "customer_response_sanitized": True})
            return self._save("answer_information", _repair(language, context.active_entity_name), "conversation_repair", "conversation_repair", language, False, customer, conversation, source_message_id, context, metadata={"response_basis": "conversation_repair", "customer_response_sanitized": True})
        if _SELF_INTRO.search(routing_text):
            introduced = replace(context, active_domain="entartica", active_topic="chatbot_introduction", active_entity_type="chatbot", active_entity_name="Entartica virtual sales assistant")
            return self._save("answer_information", _self_introduction(language), "self_introduction", "self_introduction", language, False, customer, conversation, source_message_id, introduced, metadata={"response_basis": "deterministic", "structured_grounding": True, "customer_response_sanitized": True, "rag_called": False, "openai_called": False})
        if _CURRENT_AFFAIRS.search(routing_text):
            current = replace(context, active_domain="general", active_topic="current_information", active_entity_type="person", active_entity_name="current office holder")
            return self._save("answer_information", _current_information(language), "live_verification_required", "current_information", language, False, customer, conversation, source_message_id, current, metadata={"response_basis": "live_verification_required", "customer_response_sanitized": True})
        if context.active_topic == "current_information" and len(routing_text.split()) <= 6:
            return self._save("answer_information", _current_information(language), "live_verification_required", "current_information", language, False, customer, conversation, source_message_id, context, metadata={"response_basis": "live_verification_required", "customer_response_sanitized": True})
        if _RAIPUR_TRAVEL.search(routing_text):
            pending = replace(context, active_domain="general", active_topic="travel_to_raipur", active_entity_type="place", active_entity_name="Raipur", pending_clarification=True, pending_clarification_type="destination_scope", pending_clarification_options=("raipur_city", "entartica_raipur"))
            return self._save("answer_information", _destination_scope_question(language), "destination_scope_clarification", "destination_scope", language, False, customer, conversation, source_message_id, pending, metadata={"response_basis": "clarification", "customer_response_sanitized": True})
        if _is_raipur_city_geography_question(routing_text):
            city_context = replace(context, active_domain="raipur_city", active_topic="raipur_city_geography", active_entity_type="place", active_entity_name="Raipur city", pending_clarification=False, pending_clarification_type=None, pending_clarification_options=(), pending_question_type=None, pending_action=None, pending_service_code=None, pending_slots=None)
            return self._save("answer_information", _raipur_city_geography(language), "raipur_city_geography", "general", language, False, customer, conversation, source_message_id, city_context, metadata={"response_basis": "general_stable_knowledge", "customer_response_sanitized": True})
        if _H2O_PLAY_PARK.search(routing_text):
            h2o = replace(context, active_domain="entartica", active_topic="h2o_play_park", active_entity_type="concept", active_entity_name="H2O Play Park")
            return self._save("answer_information", _h2o_unavailable(language), "service_detail_unavailable", "service_detail", language, False, customer, conversation, source_message_id, h2o, metadata={"response_basis": "clarification", "customer_response_sanitized": True, "unavailable_term": True})
        if _UNSUPPORTED.search(routing_text):
            return self._save("unsupported_location_handover", _handover(language, self._sales_contact), "unsupported_location", "unsupported_location", language, True, customer, conversation, source_message_id, context)
        if _HUMAN.search(routing_text) and not _PRICING.search(routing_text):
            return self._save("general_human_handover", _handover(language, self._sales_contact), "human_support_required", "human", language, True, customer, conversation, source_message_id, context)
        explicit_service = approved_primary_service_from_question(routing_text)
        matched_service = explicit_service
        context_used = False
        venue_overview_requested = _is_venue_overview_question(routing_text, context)
        follow_up = _is_service_follow_up(
            routing_text,
            selected_service=matched_service,
            context=context,
        )
        full_overview_requested = _is_service_full_overview_request(routing_text)
        more_details_requested = _is_more_details_request(routing_text)
        if matched_service is None and (follow_up or full_overview_requested) and context.last_service_name:
            matched_service = next((item for item in _all_approved_services() if item.name == context.last_service_name), None)
            context_used = matched_service is not None
        live_availability_requested = _is_live_availability_request(routing_text) or bool(
            matched_service is not None and _is_follow_up_availability_request(routing_text)
        )
        eligibility_requested = matched_service is not None and is_participation_eligibility_question(routing_text)
        if _is_celebration_list_question(routing_text):
            services = self._active_celebration_services(conversation.get("location_id"))
            if services:
                logger.info("intent_detected intent=celebration_service_list")
                logger.info("deterministic_route_matched route=raipur_celebration_service_list")
                celebration_context = replace(_catalogue_context(context, "celebration_catalogue"), last_intent="celebration_service_list", service_selection_prompted=True)
                return self._save("answer_information", _celebration_service_list_answer(services, language), "structured_celebration_service_list", "celebration_service_list", language, False, customer, conversation, source_message_id, celebration_context, metadata=_structured_metadata(False, False, True) | {"deterministic_route": "raipur_celebration_service_list", "automatic_reply_category": "services", "awaiting_service_selection": True})
        if plan.intent == "service_list" or _is_service_list_question(routing_text):
            services = self._active_approved_services(conversation.get("location_id"))
            if services:
                return self._save("answer_information", _service_list_answer(services, language), "structured_service_list", "service_catalogue", language, False, customer, conversation, source_message_id, _catalogue_context(context, "service_catalogue"), metadata=_structured_metadata(False, False, True))
        previous_service_code = context.last_service_code
        if eligibility_requested and matched_service is not None:
            service_code = knowledge_service_code(matched_service)
            eligibility_context = replace(
                _with_service(context, matched_service, "participation_eligibility"),
                pending_question_type=None,
                pending_action=None,
                pending_service_code=None,
                service_selection_prompted=False,
                service_details_requested=True,
            )
            logger.info(
                "participation_eligibility_route original_message=%s normalized_message=%s "
                "intent_label=participation_eligibility detected_intent=participation_eligibility detected_language=%s mapped_category=information "
                "detected_service_code=%s response_basis=active_rag pending_action=%s rag_called=true "
                "retrieval_query=%s retrieval_filter_location_code=raipur retrieval_filter_service_code=%s "
                "retrieval_filter_priority=service_specific",
                text,
                routing_text,
                language,
                service_code,
                context.pending_action or "none",
                routing_text,
                service_code,
            )
            detail = self._service_detail(
                routing_text,
                matched_service.name,
                contextual_follow_up=context_used,
                detail_mode=_service_question_topic(routing_text) or "overview",
            )
            if detail is not None and _eligibility_response_addresses_subject(detail.text, routing_text):
                logger.info(
                    "participation_eligibility_result retrieval_result_count=%s retrieved_source_file=%s "
                    "retrieved_section_heading=%s mapped_category=information automatic_reply_eligibility_basis=active_rag "
                    "final_answer_mode=active_rag",
                    detail.retrieval_result_count if detail.retrieval_result_count is not None else 0,
                    detail.source_filename or "none",
                    detail.section_heading or "unknown",
                )
                return self._save(
                    "answer_information",
                    detail.text,
                    "approved_service_eligibility",
                    "participation_eligibility",
                    language,
                    False,
                    customer,
                    conversation,
                    source_message_id,
                    eligibility_context,
                    metadata=_service_detail_metadata(detail, context_used) | {"response_basis": "active_rag", "automatic_reply_category": "information", "eligibility_subject_addressed": True, "retrieval_service_code": service_code, "approved_active_exact_service": True, "question_topic": _service_question_topic(routing_text), "retrieval_query": routing_text},
                )
            fallback = _participation_eligibility_fallback(routing_text, language)
            logger.info(
                "participation_eligibility_result retrieval_result_count=0 retrieved_source_file=none "
                "retrieved_section_heading=none mapped_category=information automatic_reply_eligibility_basis=safe_fallback "
                "final_answer_mode=safe_fallback"
            )
            return self._save(
                "answer_information",
                fallback,
                "service_eligibility_unavailable",
                "participation_eligibility",
                language,
                False,
                customer,
                conversation,
                source_message_id,
                eligibility_context,
                metadata={
                    "response_basis": "clarification",
                    "customer_response_sanitized": True,
                    "rag_used": True,
                    "exact_service_chunk_match": False,
                    "eligibility_subject_addressed": True,
                    "approved_safe_fallback": True,
                    "automatic_reply_category": "information",
                },
            )
        if matched_service is not None:
            context = _with_service(context, matched_service, "availability" if live_availability_requested else "services")
        if matched_service is None and _AMBIGUOUS_SEATER.search(routing_text):
            return self._save("answer_information", "Please clarify which activity you mean: Aqua Cycle, Kayak, or another approved Raipur activity.", "service_clarification_required", "clarification", language, False, customer, conversation, source_message_id, context, metadata={"response_basis":"clarification","customer_response_sanitized":True, "ambiguous_service_reference":True})
        if _PRICING.search(routing_text):
            return self._pricing(text, context, customer, conversation, source_message_id, language, now)
        if _BOOKING.search(routing_text):
            return self._booking_sales_handover(routing_text, context, customer, conversation, source_message_id, language)
        if matched_service is not None and not live_availability_requested and (full_overview_requested or plan.intent == "service_full_overview"):
            service = self._active_service(conversation.get("location_id"), matched_service)
            if service is not None:
                full_context = replace(_with_service(context, matched_service, "service_full_overview"), service_details_requested=True, service_selection_prompted=False, pending_question_type=None, pending_action=None, pending_service_code=None)
                detail = self._service_detail(routing_text, matched_service.name, contextual_follow_up=context_used, full_overview=True)
                if detail is not None:
                    return self._save("answer_information", detail.text, "approved_service_full_overview", "service_full_overview", language, False, customer, conversation, source_message_id, full_context, metadata=_service_detail_metadata(detail, context_used) | {"automatic_reply_category": "information", "full_overview": True})
                return self._save("answer_information", _service_detail_fallback(matched_service.name, language), "service_full_overview_unavailable", "service_full_overview", language, False, customer, conversation, source_message_id, full_context, metadata=_structured_metadata(True, approved_service_alias_used(text), True) | {"automatic_reply_category": "information", "conversation_service_context_used": context_used})
        if matched_service is not None and not live_availability_requested and plan.answer_mode == "active_rag":
            service = self._active_service(conversation.get("location_id"), matched_service)
            if service is not None:
                service_code = knowledge_service_code(matched_service)
                question_topic = plan.question_topic or _service_question_topic(routing_text) or "service_overview"
                detail_context = replace(
                    _with_service(context, matched_service, plan.intent),
                    service_details_requested=True,
                    service_selection_prompted=False,
                    pending_question_type=None,
                    pending_action=None,
                    pending_service_code=None,
                    active_topic=question_topic,
                    active_entity_type="service",
                    active_entity_name=matched_service.name,
                )
                logger.info(
                    "service_question_route original_message=%s normalized_message=%s detected_service_code=%s "
                    "detected_intent=%s question_topic=%s retrieval_query=%s "
                    "retrieval_filter_location_code=raipur retrieval_filter_service_code=%s "
                    "retrieval_filter_priority=service_specific rag_called=true",
                    text,
                    routing_text,
                    service_code,
                    plan.intent,
                    question_topic or "general",
                    routing_text,
                    service_code,
                )
                detail_mode = (
                    "more_details"
                    if plan.intent == "service_more_details" or more_details_requested or repair_requested
                    else ("overview" if question_topic == "service_overview" else question_topic)
                )
                detail = self._service_detail(routing_text, matched_service.name, contextual_follow_up=context_used, detail_mode=detail_mode)
                answer_intent = "service_more_details" if detail_mode == "more_details" else plan.intent
                if detail is not None and _service_response_addresses_topic(detail.text, question_topic):
                    logger.info(
                        "service_question_result retrieval_result_count=%s retrieved_source_file=%s "
                        "retrieved_section_heading=%s response_basis=active_rag final_answer_mode=grounded_answer",
                        detail.retrieval_result_count if detail.retrieval_result_count is not None else 0,
                        detail.source_filename or "none",
                        detail.section_heading or "unknown",
                    )
                    return self._save(
                        "answer_information",
                        detail.text,
                        "approved_service_detail",
                        answer_intent,
                        language,
                        False,
                        customer,
                        conversation,
                        source_message_id,
                        detail_context,
                        metadata=_service_detail_metadata(detail, context_used) | {
                            "response_basis": "active_rag",
                            "automatic_reply_category": "information",
                            "retrieval_service_code": service_code,
                            "approved_active_exact_service": True,
                            "question_topic": "more_details" if detail_mode == "more_details" else question_topic,
                            "retrieval_query": routing_text,
                        },
                    )
                return self._save(
                    "answer_information",
                    _service_question_fallback(language, self._sales_contact),
                    "service_detail_unavailable",
                    plan.intent,
                    language,
                    False,
                    customer,
                    conversation,
                    source_message_id,
                    detail_context,
                    metadata={
                        "response_basis": "clarification",
                        "approved_safe_fallback": True,
                        "customer_response_sanitized": True,
                        "rag_used": True,
                        "exact_service_chunk_match": False,
                        "automatic_reply_category": "information",
                        "question_topic": question_topic,
                        "retrieval_query": routing_text,
                    },
                )
        if matched_service is not None and not live_availability_requested and (
            plan.intent in {"service_definition", "service_correction"}
            or (_is_service_definition_question(routing_text) and _service_question_topic(routing_text) is None)
        ):
            service = self._active_service(conversation.get("location_id"), matched_service)
            if service is not None:
                definition_context = replace(_with_service(context, matched_service, "generic_service_definition"), service_details_requested=True, service_selection_prompted=False, pending_question_type="yes_no", pending_action="provide_service_details", pending_entity_type="service", pending_entity_name=matched_service.name, pending_created_at=now.isoformat(), pending_service_code=matched_service.slug.replace("-", "_"))
                if matched_service.slug == "daycation-package":
                    return self._save("answer_information", _daycation_definition(language), "generic_service_definition", "generic_service_definition", language, False, customer, conversation, source_message_id, definition_context, metadata=_structured_metadata(True, approved_service_alias_used(routing_text), True) | {"response_basis": "deterministic", "customer_response_sanitized": True, "active_service_confirmed": True})
                definition = self._generic_service_definition(text, matched_service.name, language, definition_context, conversation)
                response = f"{definition} {_definition_follow_up(language)}"
                return self._save("answer_information", response, "generic_service_definition", "generic_service_definition", language, False, customer, conversation, source_message_id, definition_context, metadata=_structured_metadata(True, approved_service_alias_used(routing_text), True) | {"response_basis": "conversational_fallback", "general_knowledge_used": True, "customer_response_sanitized": True, "active_service_confirmed": True})
        selection_detail = bool(matched_service is not None and context.service_selection_prompted)
        explicit_service_detail = bool(
            matched_service is not None
            and matched_service.category == "floating_celebration"
            and not _is_service_confirmation_question(routing_text)
        )
        if matched_service is not None and not live_availability_requested and (_is_service_detail_question(routing_text) or follow_up or selection_detail or explicit_service_detail):
            service = self._active_service(conversation.get("location_id"), matched_service)
            if service is not None:
                previous_code = previous_service_code
                current_code = matched_service.slug.replace("-", "_")
                if previous_code and previous_code != current_code:
                    logger.info("context_service_switched previous_service_code=%s service_code=%s", previous_code, current_code)
                if context_used:
                    logger.info("context_service_resolved service_code=%s", matched_service.slug.replace("-", "_"))
                logger.info("intent_detected intent=%s", "celebration_service_detail" if matched_service.category == "floating_celebration" else "service_detail")
                if selection_detail and matched_service.category == "floating_celebration":
                    logger.info("deterministic_route_matched route=celebration_service_selection_detail")
                elif previous_code and previous_code != current_code and matched_service.category == "floating_celebration":
                    logger.info("deterministic_route_matched route=celebration_service_switch_detail")
                question_topic = _service_question_topic(routing_text) or "service_overview"
                detail_mode = "more_details" if more_details_requested or repair_requested else ("overview" if question_topic == "service_overview" else question_topic)
                detail = self._service_detail(text, matched_service.name, contextual_follow_up=context_used, detail_mode=detail_mode)
                detail_intent = "service_more_details" if detail_mode == "more_details" else ("celebration_service_detail" if matched_service.category == "floating_celebration" else "service_detail")
                detail_context = replace(
                    _with_service(context, matched_service, detail_intent),
                    service_details_requested=True,
                    service_selection_prompted=False,
                    active_topic=question_topic,
                    active_entity_type="service",
                    active_entity_name=matched_service.name,
                )
                if detail is not None:
                    return self._save(
                        "answer_information",
                        detail.text,
                        "approved_service_detail",
                        detail_context.last_intent or "service_detail",
                        language,
                        False,
                        customer,
                        conversation,
                        source_message_id,
                        detail_context,
                        metadata=_service_detail_metadata(detail, context_used) | {
                            "response_basis": "active_rag",
                            "automatic_reply_category": "information",
                            "retrieval_service_code": knowledge_service_code(matched_service),
                            "approved_active_exact_service": True,
                            "question_topic": question_topic,
                        },
                    )
                return self._save("answer_information", _service_detail_fallback(matched_service.name, language), "service_detail_unavailable", detail_context.last_intent or "service_detail", language, False, customer, conversation, source_message_id, detail_context, metadata=_structured_metadata(True, approved_service_alias_used(text), True) | {"automatic_reply_category": "information", "conversation_service_context_used": context_used})
        if matched_service is not None and not live_availability_requested:
            service = self._active_service(conversation.get("location_id"), matched_service)
            if service is not None:
                overview_context = replace(
                    _with_service(context, matched_service, "service_overview"),
                    service_details_requested=True,
                    service_selection_prompted=False,
                    active_topic="service_overview",
                    active_entity_type="service",
                    active_entity_name=matched_service.name,
                )
                detail = self._service_detail(routing_text, matched_service.name, contextual_follow_up=context_used, detail_mode="overview")
                if detail is not None:
                    return self._save(
                        "answer_information", detail.text, "approved_service_detail", "service_overview", language,
                        False, customer, conversation, source_message_id, overview_context,
                        metadata=_service_detail_metadata(detail, context_used) | {
                            "response_basis": "active_rag",
                            "automatic_reply_category": "information",
                            "retrieval_service_code": knowledge_service_code(matched_service),
                            "approved_active_exact_service": True,
                            "question_topic": "service_overview",
                        },
                    )
                return self._save(
                    "answer_information", _service_detail_fallback(matched_service.name, language),
                    "service_overview_unavailable", "service_overview", language, False, customer, conversation,
                    source_message_id, overview_context,
                    metadata={
                        "response_basis": "clarification", "approved_safe_fallback": True,
                        "customer_response_sanitized": True, "rag_used": True,
                        "exact_service_chunk_match": False, "automatic_reply_category": "information",
                        "question_topic": "service_overview",
                    },
                )

        availability_requested = live_availability_requested
        if context.pending_field or availability_requested:
            return self._booking(text, context, customer, conversation, source_message_id, language, now, availability_requested=availability_requested)
        if follow_up:
            clarification_context = replace(context, pending_clarification=True, pending_clarification_type="general_information")
            return self._save("answer_information", _clarification(language), "clarification_required", "clarification", language, False, customer, conversation, source_message_id, clarification_context, metadata=_structured_metadata(False, False, False, clarification=True))
        if venue_overview_requested:
            # A venue-level request is not a reference to a previously selected
            # ride.  Clear that service context before generic approved-Raipur
            # retrieval, while retaining the venue topic for a useful follow-up.
            context = replace(
                context,
                last_service_name=None,
                last_service_code=None,
                pending_question_type=None,
                pending_action=None,
                pending_service_code=None,
                active_domain="entartica",
                active_topic="entartica_raipur_overview",
                active_entity_type="place",
                active_entity_name="Entartica Sea World Raipur",
            )
        knowledge = self._knowledge.answer(text)
        customer_answer = compose_customer_response(knowledge.text, question=text, language=language) if isinstance(knowledge.text, str) else None
        if knowledge.low_confidence or not customer_answer:
            approved_excerpts = self._fallback_excerpts(text, knowledge)
            fallback = self._conversational_fallback.respond(
                question=text,
                language=language,
                selected_service=context.last_service_name,
                approved_excerpts=approved_excerpts,
                active_services=tuple(row["name"] for row in self._active_approved_services(conversation.get("location_id")) if isinstance(row.get("name"), str)),
                previous_response_summary=context.last_bot_action,
            )
            if fallback.valid and fallback.text:
                metadata = {
                    "customer_response_sanitized": True,
                    "response_basis": "conversational_fallback",
                    "fallback_retry_count": fallback.retries,
                    "fallback_grounded": fallback.reason == "grounded",
                    "conversation_service_context_used": bool(context.last_service_name),
                    "clarification_used": fallback.reason == "clarification",
                }
                if fallback.reason == "grounded":
                    return self._save("answer_information", fallback.text, "safe_conversational_fallback", "safe_conversational_fallback", language, False, customer, conversation, source_message_id, context, metadata=metadata)
                if context.pending_clarification:
                    return self._save("answer_information", approved_safe_fallback(self._sales_contact, language), "approved_safe_fallback", "safe_conversational_fallback", language, False, customer, conversation, source_message_id, context, metadata={"response_basis": "clarification", "approved_safe_fallback": True, "customer_response_sanitized": True})
                clarification_context = replace(context, pending_clarification=True, pending_clarification_type="general_information")
                return self._save("answer_information", fallback.text, "clarification_required", "clarification", language, False, customer, conversation, source_message_id, clarification_context, metadata=metadata)
            # The model has already received one corrective attempt. Do not drop
            # a safe customer message merely because it could not be answered.
            return self._save("answer_information", approved_safe_fallback(self._sales_contact, language), "approved_safe_fallback", "safe_conversational_fallback", language, False, customer, conversation, source_message_id, context, metadata={"response_basis": "clarification", "approved_safe_fallback": True, "customer_response_sanitized": True, "fallback_validation_failed": True})
        return self._save("answer_information", customer_answer, "approved_knowledge", "venue_overview" if venue_overview_requested else "knowledge", language, False, customer, conversation, source_message_id, context, metadata={"source_filename": knowledge.source_filename, "retrieval_confidence": knowledge.confidence, "customer_response_sanitized": True, "response_basis": "active_rag", "venue_overview": venue_overview_requested})

    def _pricing(self, text: str, context: ConversationContext, customer: dict[str, Any], conversation: dict[str, Any], source_id: str, language: str, now: datetime) -> ConversationResult:
        context = _apply_known_text(context, text, now, self._timezone)
        if not _BOOKING.search(text):
            consent = replace(context, pending_field=None, pending_question_type="yes_no", pending_action="start_booking_enquiry")
            response = f"{_pricing_text(language, self._sales_contact)}\n\nWould you like me to collect your booking enquiry for the sales team?"
            return self._save("pricing_sales_handover", response, "human_quotation_required", "pricing", language, True, customer, conversation, source_id, consent, availability="verification_required")
        missing = self._bookings.next_missing_field(context.details)
        if missing:
            response = f"{_pricing_text(language, self._sales_contact)}\n\n{_ask(missing, language)}"
            return self._save("pricing_sales_handover", response, "human_quotation_required", "pricing", language, True, customer, conversation, source_id, replace(context, pending_field=missing), next_field=missing, availability="verification_required")
        result = self._bookings.pricing_handover(context.details, customer_id=customer["id"], conversation_id=conversation["id"], location_id=conversation["location_id"], source_message_id=source_id, now=now)
        return self._save("pricing_sales_handover", _pricing_text(language, self._sales_contact), "human_quotation_required", "pricing", language, True, customer, conversation, source_id, replace(context, pending_field=None), created=result.created, availability=result.availability_status)

    def _booking(self, text: str, context: ConversationContext, customer: dict[str, Any], conversation: dict[str, Any], source_id: str, language: str, now: datetime, *, availability_requested: bool) -> ConversationResult:
        updated = _apply_reply(context, text, now, self._timezone)
        wants_availability = availability_requested or updated.availability_requested
        if wants_availability and all((updated.details.requested_service_text, updated.details.preferred_date, updated.details.preferred_time)):
            availability, _ = self._bookings.check_availability(updated.details, location_id=conversation["location_id"], now=now)
            missing = self._bookings.next_missing_field(updated.details)
            draft = _availability_text(availability.status, language, self._sales_contact)
            if missing: draft = f"{draft} {_ask(missing, language)}"
            return self._save("check_availability", draft, availability.safe_reason_code, "availability", language, True, customer, conversation, source_id, replace(updated, pending_field=missing, availability_requested=True), next_field=missing, availability=availability.status)
        missing = self._bookings.next_missing_field(updated.details)
        if missing:
            action: Action = "check_availability" if availability_requested else "ask_booking_field"
            thanks = f"Thank you, {updated.details.customer_name}. " if context.pending_field == "customer_name" and updated.details.customer_name else ""
            response = f"{thanks}{_ask(missing, language)}"
            return self._save(action, response, "booking_detail_required", "availability" if wants_availability else "booking", language, wants_availability, customer, conversation, source_id, replace(updated, pending_field=missing, availability_requested=wants_availability), next_field=missing, availability="verification_required")
        try:
            result = self._bookings.submit(updated.details, customer_id=customer["id"], conversation_id=conversation["id"], location_id=conversation["location_id"], source_message_id=source_id, now=now)
        except Exception:
            return self._save("general_human_handover", _handover(language, self._sales_contact), "availability_provider_error", "availability", language, True, customer, conversation, source_id, updated, availability="verification_required")
        if result.availability_status == "available": text_out = _available(language, self._sales_contact)
        elif result.availability_status == "not_available": text_out = _not_available(language, self._sales_contact)
        else: text_out = _verify(language, self._sales_contact)
        return self._save("booking_enquiry_saved", text_out, "booking_enquiry_saved", "availability" if availability_requested else "booking", language, True, customer, conversation, source_id, replace(updated, pending_field=None), created=result.created, availability=result.availability_status)

    def _booking_sales_handover(self, text: str, context: ConversationContext, customer: dict[str, Any], conversation: dict[str, Any], source_id: str, language: str) -> ConversationResult:
        """End an explicit booking request safely; no enquiry details are collected."""

        explicit = approved_primary_service_from_question(text)
        service_name = explicit.name if explicit is not None else context.last_service_name
        cleared = _clear_booking_state(context, service_name=service_name, service_code=explicit.slug.replace("-", "_") if explicit is not None else context.last_service_code)
        return self._save(
            "general_human_handover",
            booking_sales_handover(self._sales_contact, language, service_name),
            "booking_sales_handover",
            "booking",
            language,
            True,
            customer,
            conversation,
            source_id,
            cleared,
            metadata={"response_basis": "deterministic", "structured_grounding": True, "customer_response_sanitized": True, "response_mode": "human_handover", "automatic_reply_category": "information"},
        )

    def _save(self, action: Action, draft: str, reason: str, intent: str, language: str, handover: bool, customer: dict[str, Any], conversation: dict[str, Any], source_id: str, context: ConversationContext, *, next_field: str | None = None, created: bool = False, availability: str | None = None, metadata: dict[str, Any] | None = None) -> ConversationResult:
        response = present(RaipurResponseRequest(
            action=action, language=language, reason_code=reason,
            grounded_answer=draft,
            availability_status=availability, next_required_field=next_field,
            human_handover_required=handover,
        ))
        draft = _clean_response_script(response.text)
        context = replace(context, last_intent=intent, last_user_intent=intent, last_bot_action=action, preferred_language=language, last_assistant_answer_summary=_safe_summary(draft), last_assistant_question=draft if draft.rstrip().endswith("?") else None)
        response_basis = "restricted_handover" if handover else ("clarification" if reason == "clarification_required" else "deterministic")
        safe = {"raw_intent": intent, "detected_intent": intent, "reason_code": reason, "response_language": language, "availability_status": availability, "generated_by": "raipur_draft_orchestrator", "detected_language": language, "context_service_present": bool(context.last_service_name), "context_service_used": bool((metadata or {}).get("conversation_service_context_used")), "resolved_service_present": bool(context.last_service_name), "clarification_required": reason == "clarification_required", "handover_required": handover, "response_basis": response_basis, "customer_response_sanitized": True, "active_entity_type": context.active_entity_type, "active_entity_name": context.active_entity_name} | (metadata or {})
        safe["response_mode"] = (
            "direct_contact_details" if safe.get("response_mode") == "direct_contact_details" else
            "human_handover" if handover else
            "approved_safe_fallback" if safe.get("approved_safe_fallback") is True else
            "clarification_question" if safe.get("clarification_used") is True or safe.get("response_basis") == "clarification" else
            "grounded_answer" if safe.get("response_basis") == "active_rag" or safe.get("structured_grounding") is True else
            "clarification"
        )
        logger.info(
            "raipur_route_decision message_id_present=%s selected_route=%s intent=%s service_code=%s topic=%s used_previous_service=%s answer_source=%s",
            bool(source_id), safe["response_mode"], intent, context.last_service_code or "none",
            context.active_topic or "none", safe.get("context_service_used", False), safe.get("response_basis", "none"),
        )
        saved = False
        if self._persist_drafts:
            _, saved = self._drafts.create_outbound_draft(customer_id=customer["id"], conversation_id=conversation["id"], related_inbound_message_id=source_id, content=draft, metadata=safe)
        return ConversationResult(action, draft, reason, intent, "raipur" if intent != "unsupported_location" else "unsupported", language, handover, created, False, availability, next_field, True, saved, context, safe, response.template_key.value, response.response_valid, response.safe_validation_reason)

    def _active_approved_services(self, location_id: object) -> list[dict[str, Any]]:
        if self._services is None or not isinstance(location_id, str):
            return []
        try:
            rows = self._services.list_active_for_location(location_id)
        except Exception:
            return []
        return [row for row in rows if isinstance(row, dict) and any(is_active_approved_service(row, approved) for approved in _all_approved_services())]

    def _active_service(self, location_id: object, approved: Any) -> dict[str, Any] | None:
        return next((row for row in self._active_approved_services(location_id) if is_active_approved_service(row, approved)), None)

    def _active_celebration_services(self, location_id: object) -> list[dict[str, Any]]:
        return [row for row in self._active_approved_services(location_id) if getattr(approved_service_from_message(row.get("name")), "category", None) == "floating_celebration"]

    def _service_detail(self, text: str, service_name: str, *, contextual_follow_up: bool = False, full_overview: bool = False, detail_mode: str = "overview") -> KnowledgeDraft | None:
        try:
            method = getattr(self._knowledge, "answer_service_details", None)
            approved = approved_service_from_message(service_name)
            service_code = knowledge_service_code(approved) if approved is not None else None
            retrieval_query = _service_detail_retrieval_query(text, service_name, contextual_follow_up=contextual_follow_up)
            if callable(method):
                try:
                    result = method(retrieval_query, service_name, service_code, full_overview=full_overview, detail_mode=detail_mode)
                except TypeError:
                    try:
                        result = method(retrieval_query, service_name, service_code)
                    except TypeError:
                        result = method(retrieval_query, service_name)
            else:
                result = self._knowledge.answer(f"{text} {service_name}")
        except Exception:
            return None
        if not isinstance(result, KnowledgeDraft) or result.low_confidence or not isinstance(result.text, str) or not result.text.strip():
            return None
        # RaipurKnowledgeProvider has already composed and sanitized the
        # customer response.  Re-composition here used to discard later,
        # topic-specific facts through a second truncation pass.
        return result

    def _generic_service_definition(self, text: str, service_name: str, language: str, context: ConversationContext, conversation: dict[str, Any]) -> str:
        fallback = self._conversational_fallback.respond(
            question=text,
            language=language,
            selected_service=service_name,
            approved_excerpts=self._fallback_excerpts(text, KnowledgeDraft(None)),
            active_services=tuple(row["name"] for row in self._active_approved_services(conversation.get("location_id")) if isinstance(row.get("name"), str)),
            previous_response_summary=context.last_bot_action,
            generic_definition=True,
        )
        if fallback.valid and fallback.text:
            return fallback.text
        return _generic_definition_fallback(service_name, language)

    def _fallback_excerpts(self, text: str, knowledge: KnowledgeDraft) -> tuple[str, ...]:
        method = getattr(self._knowledge, "fallback_context", None)
        if callable(method):
            try:
                value = method(text)
                if isinstance(value, (list, tuple)):
                    return tuple(item[:800] for item in value if isinstance(item, str) and item.strip())[:3]
            except Exception:
                pass
        return (knowledge.text,) if isinstance(knowledge.text, str) and knowledge.text.strip() else ()

def _language(text: str) -> str:
    if re.search(r"[\u0900-\u097f]", text): return "hi"
    if re.search(r"\b(kal|hai|kya|mein|ka|karna|karni|mujhe|kro|bhejo|nmbr)\b", text, re.I): return "hinglish"
    return "en"


def _requested_language(text: str) -> str | None:
    if _LANGUAGE_HINDI.search(text): return "hi"
    if _LANGUAGE_ENGLISH.search(text): return "en"
    if _LANGUAGE_HINGLISH.search(text): return "hinglish"
    return None


def _language_changed(language: str) -> str:
    if language == "hi": return "ज़रूर, अब मैं हिंदी में बात करूँगा।"
    if language == "hinglish": return "Sure, ab main Hinglish mein baat karunga."
    return "Sure, I will continue in English."


def _greeting(language: str) -> str:
    if language == "hi": return "नमस्ते! मैं Entartica Sea World का virtual assistant हूँ। मैं Raipur की rides, celebration options और booking enquiries में मदद कर सकता हूँ।"
    if language == "hinglish": return "Namaste! Main Entartica Sea World ka virtual assistant hoon. Main Raipur ki rides, celebration options aur booking enquiries mein madad kar sakta hoon."
    return "Hello! I am Entartica Sea World's virtual assistant. I can help with Raipur rides, celebration options, and booking enquiries."
def _is_availability_request(text: str) -> bool:
    return _is_live_availability_request(text)


def _is_live_availability_request(text: str) -> bool:
    return bool(_AVAILABILITY.search(text) and _LIVE_AVAILABILITY_SIGNAL.search(text) and approved_service_from_message(text) is not None)


def _is_follow_up_availability_request(text: str) -> bool:
    return bool(_AVAILABILITY.search(text) and _LIVE_AVAILABILITY_SIGNAL.search(text))


def _is_service_follow_up(
    text: str,
    *,
    selected_service: Any | None = None,
    context: ConversationContext | None = None,
) -> bool:
    """Return true only when a service-detail signal has a resolved subject."""

    detail_signal = (
        _is_service_detail_question(text)
        or _service_question_topic(text) is not None
        or _is_service_full_overview_request(text)
        or _is_more_details_request(text)
        or _is_service_definition_question(text)
        or bool(_PRICING.search(text) or _BOOKING.search(text) or _is_follow_up_availability_request(text))
    )
    has_service_subject = selected_service is not None or bool(
        context is not None and context.last_service_name and context.last_service_code
    )
    return detail_signal and has_service_subject


def _is_venue_overview_question(text: str, context: ConversationContext) -> bool:
    """Recognize a broad request about Entartica Raipur, not an unnamed ride."""

    value = text.casefold()
    explicit_venue = "entartica" in value or "sea world" in value
    raipur_scope = "raipur" in value
    broad_request = any(
        phrase in value
        for phrase in (
            "information about",
            "information regarding",
            "provide information",
            "info regarding",
            "provide info",
            "tell me about",
            "details about",
            "full information",
            "full details",
            "what is entartica",
            "what can we do",
            "please explain this place",
        )
    )
    contextual_place = context.active_entity_type == "place" and context.active_entity_name == "Entartica Sea World Raipur"
    hinglish_place = any(phrase in value for phrase in ("ke bare mein batao", "ke baare mein batao", "is jagah", "yahan kya kya hai"))
    return bool((explicit_venue and (raipur_scope or broad_request)) or (raipur_scope and broad_request) or (contextual_place and hinglish_place))


def _is_service_full_overview_request(text: str) -> bool:
    value = text.casefold()
    return any(phrase in value for phrase in ("everything", "tell me everything", "full information", "complete details", "complete information", "all details", "full details", "sab batao", "puri details", "iske bare mein sab", "iske baare mein sab"))


def _is_more_details_request(text: str) -> bool:
    value = text.casefold()
    return any(phrase in value for phrase in ("tell me more", "more information", "more details", "more info", "know more", "explain further", "aur batao", "thodi aur information", "iske bare mein aur", "iske baare mein aur"))


def _is_service_repair_request(text: str, context: ConversationContext) -> bool:
    if not _FRUSTRATION.search(text):
        return False
    has_service = approved_primary_service_from_question(text) is not None or bool(context.last_service_name and context.last_service_code)
    requests_information = _is_service_detail_question(text) or _is_more_details_request(text) or "details" in text.casefold() or "information" in text.casefold() or "info" in text.casefold()
    return has_service and requests_information


def _with_service(context: ConversationContext, service: Any, intent: str) -> ConversationContext:
    return replace(
        context,
        details=replace(context.details, requested_service_text=service.name),
        last_service_name=service.name,
        last_service_code=service.slug.replace("-", "_"),
        last_intent=intent,
    )


def _is_location_question(text: str) -> bool:
    value = text.casefold()
    explicit_request = any(phrase in value for phrase in (
        "location bhejo", "address batao", "address bhejo", "map link",
        "google maps", "google maps link", "location send", "where is it",
        "where are you located", "how can i reach entartica", "venue location",
    ))
    scoped = "raipur" in value or "entartica" in value or "\u090f\u0902\u091f\u093e\u0930" in text or "\u0930\u093e\u092f\u092a\u0941\u0930" in text
    direct_location_words = ("kaha", "kahaan", "location", "address", "map", "स्थान", "कहाँ")
    return bool(scoped and (_LOCATION_QUESTION.search(text) or any(word in value or word in text for word in direct_location_words))) or explicit_request


def _is_direct_contact_request(text: str) -> bool:
    return bool(_DIRECT_CONTACT.search(text))


def _is_location_follow_up(text: str, context: ConversationContext) -> bool:
    if context.active_entity_type != "place" or context.active_entity_name != "Entartica Sea World Raipur":
        return False
    value = text.casefold()
    return any(term in value for term in ("link", "map", "google maps", "exact location", "location")) or "उसकी" in text or "इसका" in text


def _is_location_correction(text: str) -> bool:
    value = text.casefold()
    mentions_location = any(term in value for term in ("location", "address", "map", "google maps", "link")) or "स्थान" in text
    correction = any(term in value for term in ("baat nahi", "service nahi", "mera matlab", "maine location"))
    return mentions_location and correction


def _is_pending_location_map_action(context: ConversationContext) -> bool:
    return bool(
        context.pending_question_type == "yes_no"
        and context.pending_action == "send_location_map_link"
        and context.pending_entity_type == "place"
        and context.pending_entity_name == "Entartica Sea World Raipur"
        and isinstance(context.pending_created_at, str)
        and context.pending_created_at
    )


def _is_raipur_city_geography_question(text: str) -> bool:
    return bool(_RAIPUR_CITY_GEOGRAPHY.search(text) and not _ENTARTICA_SCOPE.search(text))


def _is_service_list_question(text: str) -> bool:
    return bool(_SERVICE_LIST_QUESTION.search(text)) and approved_service_from_message(text) is None and not _is_inclusion_question(text)


def _is_inclusion_question(text: str) -> bool:
    return bool(re.search(r"\b(?:included|include|inclusion|comes\s+with|isme)\b", text, re.I))


def _is_celebration_list_question(text: str) -> bool:
    return bool(_CELEBRATION_LIST_QUESTION.search(text)) and approved_service_from_message(text) is None


def _is_service_detail_question(text: str) -> bool:
    return bool(_SERVICE_DETAIL.search(text))


def _service_detail_retrieval_query(text: str, service_name: str, *, contextual_follow_up: bool) -> str:
    """Give a pronoun-only follow-up its existing, exact service subject."""

    if not contextual_follow_up:
        return text
    value = text.casefold()
    if any(phrase in value for phrase in ("tell me more", "know more", "more about it", "more information on this", "more information about this", "aur batao", "iske bare", "iske baare", "isme", "this package", "this ride", "this activity", "what is included", "is breakfast included", "what about children", "how long", "is swimming required")):
        return f"Provide additional approved details about {service_name}. {text}"
    return text


def _is_service_confirmation_question(text: str) -> bool:
    return bool(_SERVICE_CONFIRMATION.search(text))


def _is_service_definition_question(text: str) -> bool:
    return bool(_SERVICE_DEFINITION.search(text))


def _normalize_intent_text(text: str) -> str:
    """Apply only narrowly approved typo normalizations before intent matching."""
    value = text.casefold().strip()
    value = re.sub(r"^(?:(?:hi|hello|hey|lp)[\s,;:-]+)+", "", value).strip()
    value = re.sub(r"\b(?:matalab|matalb)\b", "matlab", value)
    value = re.sub(r"\btell\s+em\b", "tell me", value)
    value = re.sub(r"\bcanbyou\b", "can you", value)
    value = re.sub(r"\babut\b", "about", value)
    value = re.sub(r"\bkya\s+hain\b", "kya hai", value)
    value = re.sub(r"\bpregnent\b", "pregnant", value)
    value = re.sub(r"\bpregnency\b", "pregnancy", value)
    value = re.sub(r"\bpragnant\b", "pregnant", value)
    value = re.sub(r"\s+", " ", value)
    return re.sub(r"\?+", "?", value)


def _service_response_addresses_topic(answer: str | None, topic: str | None) -> bool:
    """Reject a generic catalogue confirmation for a specific service question."""

    if not isinstance(answer, str) or not answer.strip():
        return False
    value = answer.casefold()
    if topic == "service_overview":
        return not bool(re.fullmatch(r"(?:yes,?\s+)?[^.]+\s+is\s+(?:offered|available)(?:\s+at\s+entartica\s+raipur)?\.?", value.strip()))
    if topic is None:
        return value != "yes, jet ski is offered at entartica raipur."
    expected = {
        "self_driving": ("self-driven", "self driven", "control", "operate"),
        "swimming_requirement": ("swimming", "life jacket"),
        "pregnancy": ("pregnan", "pregnancy"),
        "fall_safety": ("fall", "engine", "lanyard"),
        "capacity": ("accommodat", "rider", "capacity", "one"),
        "duration": ("minute", "duration", "session"),
        "inclusions": ("include", "inclusion", "package", "feature"),
        "eligibility": ("eligible", "eligibil", "suitable", "participat", "safety", "require"),
        "operating_hours": ("hour", "timing", "open", "schedule"),
        "safety": ("safe", "safety", "life jacket", "instruction"),
        "how_it_works": ("works", "process", "experience", "ride"),
        "service_comparison": ("difference", "self-driven", "passenger", "water bike"),
    }
    return any(term in value for term in expected.get(topic, ()))


def _service_question_fallback(language: str, contact: SalesContact) -> str:
    return approved_safe_fallback(contact, language)


def _eligibility_response_addresses_subject(answer: str | None, question: str) -> bool:
    """Reject a catalogue confirmation when an eligibility subject was asked."""

    if not isinstance(answer, str) or not answer.strip():
        return False
    value = answer.casefold()
    question_value = question.casefold()
    subject_terms = {
        "pregnancy": ("pregnant", "pregnancy", "pregnent", "pregnency", "pragnant"),
        "health": ("health", "heart", "back", "neck", "surgery", "medical"),
        "children": ("child", "children", "baccha"),
        "swimming": ("swimming",),
        "age": ("age",),
        "weight": ("weight",),
    }
    requested = [terms for terms in subject_terms.values() if any(term in question_value for term in terms)]
    if requested and not any(any(term in value for term in terms) for terms in requested):
        return False
    return any(term in value for term in ("participation", "eligib", "safety", "recommended", "required", "allowed", "confirm"))


def _participation_eligibility_fallback(question: str, language: str) -> str:
    value = question.casefold()
    if any(term in value for term in ("pregnant", "pregnancy", "pregnent", "pregnency", "pragnant")):
        if language == "hinglish":
            return "Pregnancy ke dauran participation applicable safety requirements aur staff assessment par depend karta hai. Experience se pehle Entartica team se current eligibility confirm karein."
        return "Participation during pregnancy depends on the applicable safety requirements and staff assessment. Please confirm the current eligibility requirements with the Entartica team before the experience."
    if any(term in value for term in ("child", "children", "baccha", "age")):
        return "Child participation depends on the applicable safety requirements and staff assessment. Please confirm the current eligibility requirements with the Entartica team before the experience."
    if "swimming" in value:
        return "Whether swimming is required depends on the applicable safety requirements and staff assessment. Please confirm the current eligibility requirements with the Entartica team before the experience."
    if "weight" in value:
        return "Weight eligibility depends on the applicable safety requirements and staff assessment. Please confirm the current eligibility requirements with the Entartica team before the experience."
    return "Participation with a health condition depends on the applicable safety requirements and staff assessment. Please confirm the current eligibility requirements with the Entartica team before the experience."


def _structured_location_answer(location: dict[str, Any] | None, language: str) -> str | None:
    if not isinstance(location, dict):
        return None
    metadata = location.get("metadata") if isinstance(location.get("metadata"), dict) else {}
    name = metadata.get("location_name", location.get("name"))
    address = metadata.get("address_line", location.get("address"))
    landmark = metadata.get("landmark")
    maps_url = metadata.get("maps_url")
    if not all(isinstance(value, str) and value.strip() for value in (name, address, landmark, maps_url)):
        return None
    landmark_name = re.sub(r"^near\s+", "", landmark.strip(), flags=re.I)
    if language == "hi":
        return f"{name.strip()}, {address.strip()} में, {landmark_name} के पास स्थित है।\n\nGoogle Maps:\n{maps_url.strip()}"
    if language == "hinglish":
        return f"{name.strip()}, {address.strip()} mein, {landmark_name} ke paas located hai.\n\nGoogle Maps:\n{maps_url.strip()}"
    return f"{name.strip()} is located at {address.strip()}, near {landmark_name}.\n\nGoogle Maps:\n{maps_url.strip()}"


def _location_context(context: ConversationContext) -> ConversationContext:
    """Prioritize an explicit place request without discarding service history."""

    return replace(
        context,
        details=replace(context.details, customer_name=None, preferred_date=None, preferred_time=None, adults_count=None, children_count=None, total_guests=None, special_requirements=None, special_requirements_collected=False),
        pending_field=None,
        availability_requested=False,
        service_selection_prompted=False,
        service_details_requested=False,
        active_domain="entartica",
        active_topic="entartica_raipur_location",
        active_entity_type="place",
        active_entity_name="Entartica Sea World Raipur",
        last_intent="location",
        pending_clarification=False,
        pending_clarification_type=None,
        pending_clarification_options=(),
        pending_question_type=None,
        pending_action=None,
        pending_entity_type=None,
        pending_entity_name=None,
        pending_created_at=None,
        pending_service_code=None,
        pending_slots=None,
    )


def _clear_booking_state(context: ConversationContext, *, service_name: str | None, service_code: str | None) -> ConversationContext:
    """Clear incomplete collection fields while retaining only a named service."""

    return replace(
        context,
        details=replace(context.details, customer_name=None, requested_service_text=service_name, requested_service_id=None, preferred_date=None, preferred_time=None, adults_count=None, children_count=None, total_guests=None, special_requirements=None, special_requirements_collected=False),
        pending_field=None,
        availability_requested=False,
        last_service_name=service_name,
        last_service_code=service_code,
        pending_question_type=None,
        pending_action=None,
        pending_entity_type=None,
        pending_entity_name=None,
        pending_created_at=None,
        pending_service_code=None,
        pending_slots=None,
        pending_clarification=False,
        pending_clarification_type=None,
        pending_clarification_options=(),
    )


def _catalogue_context(context: ConversationContext, topic: str) -> ConversationContext:
    """A clear venue/category request must not inherit an old service subject."""

    return replace(
        context,
        details=replace(context.details, requested_service_text=None),
        last_service_name=None,
        last_service_code=None,
        last_intent="services",
        service_selection_prompted=False,
        service_details_requested=False,
        active_domain="entartica",
        active_topic=topic,
        active_entity_type="catalogue",
        active_entity_name="Entartica Sea World Raipur",
        pending_question_type=None,
        pending_action=None,
        pending_service_code=None,
    )


def _all_approved_services():
    return APPROVED_RAIPUR_SERVICES


def _service_list_answer(services: list[dict[str, Any]], language: str) -> str:
    names = [row["name"].strip() for row in services if isinstance(row.get("name"), str) and row["name"].strip()]
    if language == "hinglish":
        return f"Raipur mein {', '.join(names)} aur anya activities available hain. Aap kis activity ke baare mein details chahte hain?"
    if language == "hi":
        return f"रायपुर में {', '.join(names)} और अन्य गतिविधियाँ उपलब्ध हैं। आप किस गतिविधि की जानकारी चाहते हैं?"
    return f"We offer these Raipur activities: {', '.join(names)}. Which activity would you like to know about?"


def _celebration_service_list_answer(services: list[dict[str, Any]], language: str) -> str:
    names = [row["name"].strip() for row in services if isinstance(row.get("name"), str) and row["name"].strip()]
    if language == "hinglish":
        return f"Entartica Sea World, Raipur mein celebration options hain: {', '.join(names)}. Aap kis option ke baare mein details chahte hain?"
    if language == "hi":
        return f"Entartica Sea World, Raipur mein celebration options hain: {', '.join(names)}. Aap kis option ke baare mein jaanna chahte hain?"
    return f"At Entartica Sea World, Raipur, the available celebration options include {', '.join(names)}. Which option would you like to know more about?"


def _service_detail_fallback(name: str, language: str) -> str:
    if name == "Houseboat Celebration":
        return "Houseboat Celebration is an active celebration option at Entartica Sea World, Raipur. Detailed approved information is not currently available in the chatbot. Duration, guest capacity, inclusions, pricing, and availability must be confirmed by the Entartica team."
    if language == "hi":
        return f"{name} ki detailed approved information chatbot knowledge mein abhi available nahi hai, isliye team assistance required hai."
    if language == "hinglish":
        return f"{name} ki detailed approved information chatbot knowledge mein abhi available nahi hai; is query ke liye team assistance chahiye."
    return f"Detailed approved information for {name} is not available in the chatbot knowledge at the moment, so this query requires Entartica team assistance."


def _generic_definition_fallback(name: str, language: str) -> str:
    if name == "Daycation Package":
        return _daycation_definition(language)
    if name == "Bumper Boat":
        if language == "hinglish":
            return "Bumper Boat generally ek chhoti recreational water boat hoti hai jise guest water par gently control karta hai."
        if language == "hi":
            return "बम्पर बोट आम तौर पर पानी पर चलने वाली एक छोटी मनोरंजक नाव होती है।"
        return "A bumper boat is generally a small recreational boat that a guest gently steers on water."
    return f"{name} is generally a recreational water activity; exact operation can vary by equipment model."


def _daycation_definition(language: str) -> str:
    if language == "hinglish":
        return "Daycation generally ek same-day leisure experience hota hai, bina overnight stay ke. Entartica Raipur Daycation Package offer karta hai, lekin current timings, included activities, meals, room access, pricing aur availability Entartica team se confirm karni hogi."
    if language == "hi":
        return "Daycation आम तौर पर बिना रात रुकने वाला same-day leisure experience होता है। Entartica Raipur में Daycation Package उपलब्ध है, लेकिन वर्तमान समय, शामिल गतिविधियाँ, भोजन, room access, मूल्य और उपलब्धता की पुष्टि Entartica टीम से करनी होगी।"
    return "Daycation generally means a same-day leisure experience without an overnight stay. Entartica Raipur offers a Daycation Package, but its current timings, included activities, meals, room access, pricing, and availability must be confirmed through the Entartica team."


def _definition_follow_up(language: str) -> str:
    if language == "hinglish":
        return "Kya aap participation details ya booking enquiry ke baare mein jaanna chahenge?"
    if language == "hi":
        return "क्या आप भागीदारी विवरण या बुकिंग पूछताछ के बारे में जानना चाहेंगे?"
    return "Would you like participation details or to make a booking enquiry?"


def _self_introduction(language: str) -> str:
    if language == "hinglish":
        return "Main Entartica Sea World ka virtual assistant hoon. Main aapko Raipur activities, celebration experiences, location aur sales contact details ke baare mein help kar sakta hoon. Pricing, availability aur final booking confirmation Entartica sales team provide karegi."
    if language == "hi":
        return "मैं Entartica Sea World का virtual sales assistant हूँ। मैं Raipur की activities, celebration options, service details और booking enquiries में मदद करता हूँ। Current price, live availability और final booking confirmation टीम verify करती है।"
    return "I'm Entartica Sea World's virtual assistant. I can help you with information about our Raipur activities, celebration experiences, location, and sales contact details. For pricing, availability, and final booking confirmation, the Entartica sales team will assist you."


def _current_information(language: str) -> str:
    if language == "hinglish":
        return "Current information ko accurately verify karne ke liye live source required hai. Main Entartica services aur stable general information mein help kar sakta hoon."
    if language == "hi":
        return "Current information ko accurately verify karne ke liye live source required hai. Main Entartica services aur stable general information mein help kar sakta hoon."
    return "A live source is required to verify current information accurately. I can help with Entartica services and stable general information."


def _destination_scope_question(language: str) -> str:
    if language == "hinglish":
        return "Aap Raipur city ka route pooch rahe hain ya Entartica Sea World Raipur ka?"
    return "Are you asking how to reach Raipur city or Entartica Sea World Raipur?"


def _raipur_city_travel(language: str) -> str:
    if language == "hinglish":
        return "Raipur city flight, train, bus aur road travel se pahunch sakte hain. Aap kis city se travel kar rahe hain?"
    return "Raipur city can generally be reached by flight, train, bus, or road. Which city are you travelling from?"


def _raipur_city_geography(language: str) -> str:
    if language == "hinglish":
        return "Raipur city Chhattisgarh mein hai. Agar aap Entartica Sea World Raipur ka exact location chahte hain, to location ya map link pooch sakte hain."
    if language == "hi":
        return "रायपुर शहर छत्तीसगढ़ में है। यदि आप Entartica Sea World Raipur का सटीक स्थान चाहते हैं, तो location या map link पूछ सकते हैं।"
    return "Raipur city is in Chhattisgarh. If you need the exact Entartica Sea World Raipur location, please ask for the location or map link."


def _raipur_city_repair(language: str) -> str:
    if language == "hinglish":
        return "Ji, aap Raipur city ke travel route ke baare mein pooch rahe hain, Entartica location ke baare mein nahi. Aap kis city se Raipur aana chahte hain?"
    return "You are asking about travel to Raipur city, not the Entartica location. Which city are you travelling from?"


def _repair(language: str, entity: str | None) -> str:
    suffix = f" {entity} ke baare mein" if language == "hinglish" and entity else ""
    if language == "hinglish":
        return f"Maaf kijiye, maine aapka sawaal sahi context mein nahi samjha.{suffix} Aap ek baar short mein bata dein ki aap kya jaana chahte hain?"
    return "Sorry, I did not understand your question in the right context. Please tell me briefly what you would like to know."


def _h2o_unavailable(language: str) -> str:
    if language == "hinglish":
        return "H2O Play Park ka detailed approved information chatbot knowledge mein abhi available nahi hai. Team confirmation ke liye main enquiry note karne mein madad kar sakta hoon."
    return "Detailed approved information about H2O Play Park is not currently available in the chatbot knowledge. I can help note an enquiry for team confirmation."


def _safe_summary(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:160]


def _clean_response_script(text: str) -> str:
    """Remove unrelated Gujarati-script characters without touching Latin/Devanagari text."""
    return re.sub(r"[\u0a80-\u0aff]", "", text).strip()


def _clarification(language: str) -> str:
    if language == "hinglish":
        return "Raipur mein aap kis activity ya service ke baare mein jaanna chahte hain?"
    return "Please tell me which Raipur activity you would like information about."


def _safe_clarification_needed(text: str) -> bool:
    value = text.casefold()
    return bool(value and (any(term in value for term in ("activity", "activities", "service", "services", "water sport")) or ("tell me about" in value and "raipur" in value)))


def _structured_metadata(matched: bool, alias: bool, lookup: bool, *, clarification: bool = False) -> dict[str, Any]:
    return {
        "response_basis": "deterministic",
        "structured_grounding": True,
        "customer_response_sanitized": True,
        "deterministic_answer_used": True,
        "matched_service_present": matched,
        "alias_match_used": alias,
        "structured_service_lookup_used": lookup,
        "rag_used": False,
        "rag_confidence_band": "none",
        "clarification_used": clarification,
    }


def _service_detail_metadata(detail: KnowledgeDraft, context_used: bool) -> dict[str, Any]:
    return {
        "source_filename": detail.source_filename,
        "retrieved_section_heading": detail.section_heading,
        "retrieval_result_count": detail.retrieval_result_count,
        "retrieval_confidence": detail.confidence,
        "customer_response_sanitized": True,
        "deterministic_answer_used": False,
        "matched_service_present": True,
        "alias_match_used": False,
        "structured_service_lookup_used": True,
        "rag_used": True,
        "exact_service_chunk_match": True,
        "conversation_service_context_used": context_used,
        "rag_confidence_band": "service_detail",
        "clarification_used": False,
    }
def _apply_known_text(context: ConversationContext, text: str, now: datetime, tz: ZoneInfo) -> ConversationContext:
    approved = approved_service_from_message(text)
    service = approved.name if approved else context.details.requested_service_text
    parsed_date = _date(text, now.date()) or context.details.preferred_date
    parsed_time = _time(text) or context.details.preferred_time
    return replace(context, details=replace(context.details, requested_service_text=service, preferred_date=parsed_date, preferred_time=parsed_time))
def _apply_reply(context: ConversationContext, text: str, now: datetime, tz: ZoneInfo) -> ConversationContext:
    field = context.pending_field
    if not field: return _apply_known_text(context, text, now, tz)
    value: Any = text.strip()
    if field == "preferred_date": value = _date(text, now.date())
    elif field == "preferred_time": value = _time(text)
    elif field in {"adults_count", "children_count", "total_guests"}:
        match = re.search(r"\d+", text); value = int(match.group()) if match else None
    elif field == "special_requirements":
        no_requirement = re.search(r"\b(no|none|nothing|not required|nahi|kuch nahi|koi requirement nahi)\b|नहीं|कुछ नहीं|कोई विशेष आवश्यकता नहीं", text, re.I)
        value = None if no_requirement else text.strip()
    if value is None and field in {"preferred_date", "preferred_time"}: return context
    changes = {field: value}
    if field == "special_requirements": changes["special_requirements_collected"] = True
    return replace(context, details=replace(context.details, **changes), pending_field=None)
def _date(text: str, today: date) -> date | None:
    v=text.casefold()
    if "tomorrow" in v or "kal" in v: return date.fromordinal(today.toordinal()+1)
    if "today" in v or "aaj" in v: return today
    if "sunday" in v:
        return date.fromordinal(today.toordinal() + ((6 - today.weekday()) % 7 or 7))
    match=re.search(r"(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})",v)
    if match:
        try:
            parsed = datetime.strptime(" ".join(match.groups()), "%d %B %Y").date()
            return parsed if parsed >= today else None
        except ValueError: return None
    return None
def _time(text: str) -> time | None:
    match=re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",text,re.I)
    if not match: return None
    hour=int(match.group(1))%12 + (12 if match.group(3).casefold()=="pm" else 0); return time(hour, int(match.group(2) or 0))
def _ask(field: str, language: str) -> str:
    english={"customer_name":"Please share your name.","requested_service_text":"Which activity would you like to enquire about?","preferred_date":"What date would you prefer?","preferred_time":"What time would you prefer? Please include AM or PM.","adults_count":"How many adults will be joining?","children_count":"How many children will be joining?","total_guests":"What is the total number of guests?","special_requirements":"Do you have any special requirements? You can reply 'No' if there are none."}
    hinglish={"preferred_date":"Aap kis date ko aana chahenge?","preferred_time":"Aap kis time aana chahenge? Please AM ya PM bhi batayein.","special_requirements":"Koi special requirement hai? Nahi ho to 'No' reply karein."}
    hindi={"preferred_date":"आप किस तारीख को आना चाहेंगे?","preferred_time":"आप किस समय आना चाहेंगे? कृपया AM या PM भी बताएं।","special_requirements":"क्या आपकी कोई विशेष आवश्यकता है? नहीं हो तो 'No' लिखें।"}
    if language=="hi": return hindi.get(field,english[field])
    if language=="hinglish": return hinglish.get(field,english[field])
    return english[field]
def _handover(language: str, contact: SalesContact) -> str: return direct_human_handover(contact, language)
def _pricing_text(language: str, contact: SalesContact) -> str: return controlled_sales_handover(contact, language)
def _verify(language: str, contact: SalesContact) -> str: return controlled_sales_handover(contact, language)
def _available(language: str, contact: SalesContact) -> str: return controlled_sales_handover(contact, language)
def _not_available(language: str, contact: SalesContact) -> str: return controlled_sales_handover(contact, language)
def _availability_text(status: str, language: str, contact: SalesContact) -> str:
    if status == "available": return _available(language, contact)
    if status == "limited": return _verify(language, contact)
    if status == "not_available": return _not_available(language, contact)
    return _verify(language, contact)
