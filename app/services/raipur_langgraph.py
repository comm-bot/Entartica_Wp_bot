"""LangGraph workflow for Raipur conversations.

Customer-facing policy is implemented through focused handlers and explicitly
injected providers.  The workflow is independent of the legacy conversation
service retained by the orchestrator for emergency rollback only.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from dataclasses import dataclass, replace
from datetime import date
from time import perf_counter
from uuid import uuid4
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field
from langgraph.graph import END, START, StateGraph

from app.services.raipur_dialogue_planner import RaipurDialoguePlanner, is_service_catalogue_question
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, approved_service_from_message, knowledge_service_code, normalize_service_text
from app.services.raipur.category_handler import (
    catalogue_type_from_topic,
    handle_raipur_category_request,
    is_activity_preference_followup,
    is_celebration_category_request,
    is_package_category_request,
    is_service_catalogue_request as is_approved_activity_catalogue_request,
    requested_catalogue_type,
)
from app.services.raipur.service_resolver import resolve_service
from app.services.raipur.topic_resolver import resolve_topic, topic_for_graph
from app.services.raipur.language import detect_language
from app.services.raipur.greeting_handler import acknowledgement_response, greeting_response, is_acknowledgement, is_greeting
from app.services.raipur.h2o_handler import asks_individual_turn_duration, h2o_playpark_answer, h2o_service_duration_answer, is_h2o_playpark_question, is_h2o_service_code
from app.services.raipur.location_handler import is_location_question, structured_location_answer
from app.services.raipur.context_state import apply_customer_understanding, clear_for_non_service_turn, clear_pending_celebration, reset_for_new_celebration_journey, set_catalogue_context, set_celebration_occasion_pending, should_reset_for_new_celebration_journey
from app.services.raipur.response_models import ConversationContext, ConversationResult, KnowledgeDraft
from app.services.raipur.customer_understanding import CustomerUnderstanding, CustomerUnderstandingService, compact_understanding_context, deterministic_celebration_understanding, parse_planned_date_text
from app.services.raipur.pontoon_package import pontoon_date_is_past, pontoon_media_message, pontoon_missing_details_question, pontoon_package_configured, pontoon_package_question_response, pontoon_post_qualification_response, pontoon_selection_response
from app.services.raipur.sales_agent import SalesAgent, SalesAgentBrief
from app.services.raipur.service_recommendation import CelebrationRecommendationPolicy, RecommendationDecision
from app.services.raipur.sales_state import SalesNextAction, SalesStage, evaluate_sales_next_action
from app.services.raipur.sales_response_composer import CustomerFacts, ResponseGoal, SalesResponseBrief, SalesResponseComposer
from app.services.raipur.conversation_telemetry import build_conversation_telemetry
from app.services.latency import current_latency_trace, latency_stage
from app.services.booking_enquiries import BookingDetails
from app.services.raipur.contact_handler import is_contact_information_request
from app.services.raipur_sales_contact import SalesContact, approved_contact_information, approved_safe_fallback, booking_sales_handover, controlled_sales_handover, direct_human_handover

logger = logging.getLogger("uvicorn.error")


GraphIntent = Literal[
    "greeting", "location", "venue_overview", "service_catalogue",
    "activity_service_list", "celebration_service_list",
    "service_overview", "service_topic", "venue_facility", "h2o_playpark", "general_question", "pricing",
    "booking", "availability", "payment", "cancellation_refund",
    "human_support", "contact_information", "unknown_entartica_fact", "contextual_service_followup",
    "venue_duration_timing", "venue_timing_confirmation", "family_activity_discovery",
    "celebration_occasion_clarification", "celebration_cancel",
    "celebration_guest_count", "celebration_planned_date", "celebration_preference",
    "customer_understanding_update",
    "service_confirmation", "service_confirmation_rejected",
    "category_media", "venue_media",
]

_SERVICE_CONFIRM_YES = re.compile(r"^\s*(?:yes|yeah|yep|correct|right|that'?s right|haan|ha|hanji|ji|yes that'?s it)\s*[.!]*\s*$", re.I)
_SERVICE_CONFIRM_NO = re.compile(r"^\s*(?:no|nope|nahi|nahin|not that one)\s*[.!]*\s*$", re.I)


def _fuzzy_service_candidate(text: str):
    """Return one strong manifest candidate; never turn it into a selection."""
    normalized = normalize_service_text(text) or ""
    if not re.search(r"\b(?:tell|about|bata|bare|service|offer|details?|explain)\b", normalized):
        return None
    tokens = normalized.split()
    scored = []
    for service in APPROVED_RAIPUR_SERVICES:
        name = normalize_service_text(service.name) or ""
        size = len(name.split())
        windows = (" ".join(tokens[index:index + size]) for index in range(max(1, len(tokens) - size + 1)))
        score = max((SequenceMatcher(None, window, name).ratio() for window in windows), default=0.0)
        scored.append((score, service))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] >= 0.78 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08) else None


class MessagePlan(BaseModel):
    """Validated, safe route fields; deterministic policy always wins."""

    model_config = ConfigDict(extra="forbid")
    intent: GraphIntent
    location_code: Literal["raipur"] = "raipur"
    entity_type: Literal["venue", "catalogue", "service", "general", "unknown"] = "unknown"
    service_code: str | None = None
    topic: Literal["overview", "suitable_for", "inclusions", "key_characteristics", "capacity", "duration", "swimming", "safety", "operating_hours", "conduct_rules", "onboard_environment", "how_it_works", "eligibility", "location", "more_details", "highlights", "technical_specification"] | None = None
    use_previous_service: bool = False
    requires_sales_handover: bool = False
    handover_reason: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class RaipurGraphState(TypedDict):
    message_id: str
    conversation_id: str
    customer_id: str
    customer_message: str
    normalized_message: str
    language: str
    location_code: str
    previous_service_code: str | None
    previous_topic: str | None
    intent: str | None
    entity_type: str
    service_code: str | None
    topic: str | None
    use_previous_service: bool
    requires_handover: bool
    handover_reason: str | None
    retrieved_context: NotRequired[tuple[str, ...]]
    retrieved_sources: NotRequired[tuple[str, ...]]
    selected_route: str | None
    answer_source: str | None
    source_filename: str | None
    validation_errors: list[str]
    plan_consistency_repaired: bool
    invocation_id: str
    draft_response: str | None
    validation_status: str
    error: str | None
    route: str | None
    result: NotRequired[Any]
    customer_understanding_shadow: NotRequired[dict[str, Any]]
    customer_understanding: NotRequired[dict[str, Any]]
    understanding_invoked: NotRequired[bool]
    understanding_failed: NotRequired[bool]
    use_sales_agent: NotRequired[bool]
    _runtime: NotRequired[dict[str, Any]]


_RESTRICTED = {"pricing", "booking", "availability", "payment", "cancellation_refund", "human_support"}
_TOPIC_WORDS = {
    "capacity": ("capacity", "seater", "kitne log", "kitna log", "kitne aadmi", "kitna aadmi", "kitne person", "how many people", "how many persons", "how many can sit", "aa sakte", "ja sakte", "baith sakte", "beth sakte", "maximum kitne", "minimum kitne", "à¤•à¤¿à¤¤à¤¨à¥‡ à¤²à¥‹à¤—", "à¤†à¤¦à¤®à¥€ à¤¬à¥ˆà¤ "),
    "duration": ("duration", "how long", "how long does it last", "kitni der", "kitne time", "kitna time", "kitne minute", "extend", "extension"),
    "suitable_for": ("suitable for", "for whom", "kiske liye"),
    "inclusions": ("included", "inclusion", "isme kya", "what is included"),
    "key_characteristics": ("key characteristics", "key features", "features"),
    "conduct_rules": ("not allowed", "not permitted", "conduct rules"),
    "onboard_environment": ("air conditioning", "is there ac", "onboard environment"),
    "safety": ("safety", "life jacket"),
    "swimming": ("swimming", "swim"),
    "operating_hours": ("operating hours", "opening", "closing", "hours", "kab tak", "timing"),
    "eligibility": ("pregnant", "pregnancy", "child", "children", "eligible"),
    "how_it_works": ("how does it work", "how it works", "what happens", "kaise hota", "kaise chalta"),
}

_FACILITY_WORDS = ("facility", "facilities", "parking", "washroom", "toilet", "locker", "changing room", "food", "restaurant", "wheelchair", "entry gate", "seating", "wi-fi", "wifi", "first aid")

_VENUE_DURATION_TIMING_SUBJECT = re.compile(r"\b(?:water\s+rides?|rides?|activities|water\s+sports?|celebration\s+services?)\b", re.I)
_VENUE_DURATION_TIMING_PRONOUN = re.compile(r"^\s*(?:the\s+)?(?:it|this|that)\b", re.I)
_GENERAL_VENUE_TIMING_PHRASE = re.compile(
    r"\b(?:opening\s+hours?|closing\s+hours?|operating\s+hours?|visiting\s+hours?|"
    r"what\s+are\s+(?:your|the\s+venue(?:'s)?)\s+timings?|"
    r"what\s+time\s+does\s+(?:it|entartica|sea\s+world|the\s+park|raipur)\s+(?:open|close|opens|closes)|"
    r"when\s+(?:does|is)\s+(?:entartica|sea\s+world|the\s+park|raipur)\s+(?:open|close|opens|closes)|"
    r"kab\s+(?:tak|se\s+kab\s+tak)?\s*(?:khulta|band|open|close|khula|\u0916\u0941\u0932\u0924\u093e|\u092c\u0902\u0926|\u0916\u0941\u0932\u093e)|"
    r"kitne\s+baje\s*(?:khulta|band|open|close)|"
    r"\u0915\u093f\u0924\u0928\u0947\s+\u092c\u091c\u0947\s*(?:\u0916\u0941\u0932\u0924\u093e|\u092c\u0902\u0926|\u0916\u0941\u0932\u093e)|"
    r"\u0938\u092e\u092f\s+\u0915\u094d\u092f\u093e\s+\u0939\u0948|\u0915\u094d\u092f\u093e\s+\u0938\u092e\u092f)",
    re.I,
)
_VENUE_TIMING_WINDOW = re.compile(
    r"\b10\s*(?:am|a\.?m\.?|baje|\u092c\u091c\u0947)?\s*(?:to|-|\u2013|se|\u0938\u0947|tak)\s*6:?30(?:\s*(?:pm|p\.?m\.?|baje|\u092c\u091c\u0947))?\b",
    re.I,
)
_VENUE_TIMING_CONFIRMATION = re.compile(
    r"\b(?:isn'?t\s+it|is\s+it|(?:the\s+)?timing\s+is|timings?\s+are|right\?|hai\s+na|haina|\u0915\u094d\u092f\u093e\s+\u0938\u092e\u092f|\u0938\u092e\u092f\s+\u0939\u0948)\b",
    re.I,
)
_VENUE_TIMING_VENUE_REFERENCE = re.compile(r"\b(?:raipur|entartica|sea\s+world|venue|park|\u0930\u093e\u092f\u092a\u0941\u0930)\b", re.I)

_FAMILY_ACTIVITY_SUBJECT = re.compile(
    r"\b(?:family|kids|children|bachch\w*)\b|"
    r"\u092c\u091a\u094d\u091a\u094b\u0902|\u092c\u091a\u094d\u091a\u0947|\u092c\u091a\u094d\u091a\u093e|\u092a\u0930\u093f\u0935\u093e\u0930"
)
_FAMILY_ACTIVITY_ACTION = re.compile(
    r"\b(?:activit\w*|rides?|fun|adventure|kar\s+sakte\w*|kar\s+sakti|kya\s+kar\w*|kya\s+karein\w*)\b|"
    r"\u0915\u094d\u092f\u093e\s+\u0915\u0930\s*\u0938\u0915\u0924\u0947|\u0915\u0930\s+\u0938\u0915\u0924\u0947"
)

_CELEBRATION_INTENT_ASK = re.compile(
    r"^\s*(?:i\s+want\s+to\s+(?:have\s+)?(?:a\s+)?(?:celebration|celebrate)|"
    r"i\s+wanna\s+(?:have\s+)?(?:a\s+)?(?:celebration|celebrate)|"
    r"mu(?:jh|j)e\s+celebration\s+(?:karvana|karvani|karna|karni)\s+(?:hain|hai|he)|"
    r"mujhe\s+celebration\s+chahiye|"
    r"celebration\s+(?:karvana|karvani|karna|karni|chahiye)(?:\s+(?:hain|hai))?|"
    r"celebrate\s+(?:karna|karvana)(?:\s+(?:hain|hai))?|"
    r"party\s+(?:karni|karvani|karna|karvana)(?:\s+(?:hain|hai))?|"
    r"\u092e\u0941\u091d\u0947\s+\u0938\u0947\u0932\u093f\u092c\u094d\u0930\u0947\u0936\u0928\s+(?:\u0915\u0930\u0928\u093e|\u0915\u0930\u0935\u093e\u0928\u093e)\s+\u0939\u0948|"
    r"\u092e\u0941\u091d\u0947\s+\u0938\u0947\u0932\u093f\u092c\u094d\u0930\u0947\u0936\u0928\s+\u091a\u093e\u0939\u093f\u090f|"
    r"\u0938\u0947\u0932\u093f\u092c\u094d\u0930\u0947\u0936\u0928\s+(?:\u0915\u0930\u0928\u093e|\u0915\u0930\u0935\u093e\u0928\u093e)\s+\u0939\u0948)\s*[?.!]*\s*$",
    re.I,
)
_GENERAL_CELEBRATION_EVENT = re.compile(
    r"\b(?:celebrat(?:e|ion)|birthday\s+party|anniversary\s+celebration|"
    r"corporate\s+event|client\s+event|office\s+event|family\s+function|"
    r"special\s+event|something\s+special)\b|"
    r"(?:\u0938\u093e\u0932\u0917\u093f\u0930\u0939\s+\u092e\u0928\u093e\u0928\u0940|"
    r"\u091c\u0928\u094d\u092e\u0926\u093f\u0928\s+\u0938\u0947\u0932\u093f\u092c\u094d\u0930\u0947\u091f)",
    re.I,
)
_CELEBRATION_CANCEL_REQUEST = re.compile(
    r"^\s*(?:cancel|cancel\s+it|cancel\s+karo|stop|stop\s+it|band\s+karo|nahi\s+chahiye|exit|"
    r"\u0915\u0948\u0902\u0938\u0932|\u0930\u094b\u0915\u094b|\u092c\u0902\u0926\s+\u0915\u0930\u094b)\s*[?.!]*\s*$",
    re.I,
)


def _is_general_celebration_intent(text: str) -> bool:
    """Recognize a general celebration/event request for deterministic options."""
    value = text.casefold().strip()
    if not value or approved_service_from_message(value) is not None:
        return False
    typo_request = bool(
        re.search(r"\b(?:want|plan|karna|karvana|chahiye)\b", value)
        and any(len(token) >= 7 and SequenceMatcher(None, token, "celebration").ratio() >= 0.70 for token in re.findall(r"[a-z]+", value))
    )
    return bool(_CELEBRATION_INTENT_ASK.fullmatch(value) or _GENERAL_CELEBRATION_EVENT.search(value) or typo_request)


def _is_celebration_cancel_request(text: str) -> bool:
    """Recognize a short abandon/stop message while a celebration flow is pending."""
    value = text.casefold().strip()
    return bool(_CELEBRATION_CANCEL_REQUEST.fullmatch(value))


def _celebration_guest_count(text: str) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,4})(?:\s+(?:guests?|people|persons?|log|members?))?\s*[.!]?\s*", text, re.I)
    value = int(match.group(1)) if match else None
    return value if value is not None and 0 < value <= 999 else None


def _celebration_date(text: str, today: date | None = None) -> date | None:
    return parse_planned_date_text(text, today)


def _celebration_guest_question(language: str) -> str:
    if language == "hinglish":
        return "Aapke saath approx kitne guests honge?"
    if language == "hi":
        return "Aapke saath lagbhag kitne guests honge?"
    return "Approximately how many guests will join the celebration?"


def _celebration_date_question(language: str, guests: int) -> str:
    if language == "hinglish":
        return f"Perfect! {guests} guests note kar liye. Aap kis date ko celebration plan kar rahe hain?"
    if language == "hi":
        return f"Bahut achha! {guests} guests note kar liye. Aap kis date ko celebration plan kar rahe hain?"
    return f"Perfect! I've noted {guests} guests. What date are you planning the celebration?"


def _celebration_preference_question(language: str, planned: date, guests: int) -> str:
    shown = planned.strftime("%d %B %Y").lstrip("0")
    if language == "hinglish":
        return f"Great — {shown} aur {guests} guests note kar liye. Aap lively party-style, private/intimate, ya relaxed celebration prefer karenge?"
    if language == "hi":
        return f"Bahut achha — {shown} aur {guests} guests note kar liye. Aap lively party-style, private/intimate, ya relaxed celebration pasand karenge?"
    return f"Great — {shown} for {guests} guests. Would you prefer a lively party-style, private/intimate, or relaxed celebration?"


def _celebration_sales_followup(context: ConversationContext, language: str) -> str:
    if (
        context.active_topic != "celebration_catalogue"
        and context.active_entity_name != "celebration"
        and context.pending_action != "celebration_sales"
    ):
        return _celebration_guest_question(language)
    decision = evaluate_sales_next_action(context)
    if decision.action is SalesNextAction.ASK_GUEST_COUNT:
        return _celebration_guest_question(language)
    if decision.action is SalesNextAction.ASK_DATE:
        return _celebration_date_question(language, context.details.total_guests or 0)
    if decision.action is SalesNextAction.ASK_PREFERENCE:
        return _celebration_preference_question(
            language, context.details.preferred_date, context.details.total_guests or 0
        )
    if language == "hinglish":
        return "Thanks — celebration details note kar liye. Approved next step ke liye team help karegi."
    return "Thank you — I've noted the celebration details. Our team can help with the approved next step."


def _progress_celebration_sales_context(context: ConversationContext) -> ConversationContext:
    decision = evaluate_sales_next_action(context)
    pending = {
        SalesNextAction.ASK_GUEST_COUNT: ("total_guests", "sales_guest_count"),
        SalesNextAction.ASK_DATE: ("preferred_date", "sales_planned_date"),
        SalesNextAction.ASK_PREFERENCE: ("celebration_preference", "sales_preference"),
    }.get(decision.action)
    return replace(
        context,
        pending_field=pending[0] if pending else None,
        pending_question_type=pending[1] if pending else None,
        pending_action="celebration_sales",
        sales_stage=decision.next_stage,
    )


@dataclass(frozen=True)
class ApprovedFacts:
    """Internal, bounded evidence passed to graph validation/composition only."""
    location_code: str
    service_code: str | None
    service_name: str | None
    requested_topic: str | None
    facts: tuple[str, ...]
    section_headings: tuple[str, ...]
    source_document_ids: tuple[str, ...] = ()


_INTERNAL_RESPONSE = re.compile(r"\b(?:rag|chunk|embedding|database|source[_ ]filename|\.md\b)\b", re.I)
_EXISTENCE_ONLY = re.compile(r"^\s*yes,?\s+.+\s+is\s+(?:offered|available).*$", re.I)
_VENUE_OVERVIEW = re.compile(
    r"\b(?:tell\s+me\s+about|information\s+about|what\s+is|what\s+can\s+we\s+do\s+at|"
    r"details?\s+(?:about|of)|about)\s+(?:the\s+)?(?:entartica(?:\s+sea\s+world)?|raipur\s+venue)\b"
    r"|\bentartica\s+(?:raipur|ke\s+baare\s+mein\s+batao)\b",
    re.I,
)
_TECHNICAL_SPECIFICATION = re.compile(
    r"\b(?:engine(?:\s+model)?|motor|horsepower|\bhp\b|fuel(?:\s+capacity|\s+level)?|"
    r"manufacturer|(?:what|which)\s+make|model\s+number|serial\s+number|technical\s+specification|"
    r"propeller|battery\s+model|equipment\s+model|current\s+operator|who\s+is\s+operating|registration\s+number)\b",
    re.I,
)


def _is_greeting_or_closing(text: str) -> bool:
    return is_greeting(text) or is_acknowledgement(text)


def _is_generic_service_concept_question(text: str, topic: str | None) -> bool:
    value=text.casefold()
    if topic is not None or any(term in value for term in ("entartica","raipur","offered","offer","available","price","booking","book","location")):
        return False
    return bool(re.search(r"\b(?:what\s+is|how\s+does)\b", value))


def _has_near_celebration_token(text: str) -> bool:
    """Recognize one likely celebration token for understanding activation only."""
    return any(
        len(token) >= 7 and SequenceMatcher(None, token, "celebration").ratio() >= 0.75
        for token in re.findall(r"[a-z]+", text.casefold())
    )


def _acknowledgement(language: str) -> str:
    if language == "hinglish": return "Aapka swagat hai. Agar aapko kisi Raipur activity ya service ke baare mein aur help chahiye, bataiye."
    if language == "hi": return "आपका स्वागत है। अगर आपको किसी रायपुर गतिविधि या सेवा के बारे में और सहायता चाहिए, तो बताइए।"
    return "You’re welcome. Let me know if you would like help with any Raipur activity or service."


def _greeting_reply(language: str) -> str:
    if language == "hinglish":
        return "Hello! Entartica Sea World, Raipur ke baare mein main aapki kaise help kar sakta hoon?"
    return "Hello! How may I help you with Entartica Sea World, Raipur?"


def _celebration_occasion_question(language: str) -> str:
    if language == "hi":
        return (
            "\u092c\u093f\u0932\u094d\u0915\u0941\u0932! Entartica Sea World, \u0930\u093e\u092f\u092a\u0941\u0930 \u092e\u0947\u0902 celebration \u0915\u0940 \u092f\u094b\u091c\u0928\u093e \u092c\u0928\u093e\u0928\u0947 \u092e\u0947\u0902 \u092e\u0948\u0902 \u0906\u092a\u0915\u0940 \u092e\u0926\u0926 \u0915\u0930 \u0938\u0915\u0924\u093e \u0939\u0942\u0901\u0964 "
            "\u0915\u094c\u0928 \u0938\u093e \u0905\u0935\u0938\u0930 \u0939\u0948 \u2014 \u0938\u093e\u0932\u0917\u093f\u0930\u0939, \u091c\u0928\u094d\u092e\u0926\u093f\u0928, \u0915\u0949\u0930\u094d\u092a\u094b\u0930\u0947\u091f \u0915\u093e\u0930\u094d\u092f\u0915\u094d\u0930\u092e, \u092f\u093e \u0915\u0941\u091b \u0914\u0930?"
        )
    if language == "hinglish":
        return "Bilkul! Entartica Sea World, Raipur mein celebration plan karne mein main aapki madad kar sakta hoon. Kaunsa occasion hai \u2014 anniversary, birthday, corporate event, ya koi aur?"
    return "Sure, I can help you plan a celebration at Entartica Sea World Raipur! Which occasion would you like to celebrate \u2014 anniversary, birthday, corporate event, or another occasion?"


def _celebration_cancel_answer(language: str) -> str:
    if language == "hi":
        return "\u0920\u0940\u0915 \u0939\u0948, \u092e\u0948\u0902\u0928\u0947 \u0935\u0939 \u0930\u0926\u094d\u0926 \u0915\u0930 \u0926\u093f\u092f\u093e\u0964 \u0905\u0917\u0930 \u0906\u092a celebration \u092f\u093e \u0915\u094b\u0908 \u0930\u093e\u092f\u092a\u0941\u0930 \u0917\u0924\u093f\u0935\u093f\u0927\u093f \u0915\u0940 \u092f\u094b\u091c\u0928\u093e \u092c\u0928\u093e\u0928\u093e \u091a\u093e\u0939\u0947\u0902 \u0924\u094b \u092c\u0924\u093e\u0907\u090f\u0964"
    if language == "hinglish":
        return "Theek hai, maine wo cancel kar diya. Agar aapko celebration ya koi Raipur activity plan karni ho toh bataiye."
    return "Okay, I have cancelled that. Let me know if you would like to plan a celebration or any Raipur activity."


def approved_facts_from_draft(draft: KnowledgeDraft, *, service_code: str | None, service_name: str | None, topic: str | None) -> ApprovedFacts:
    """Normalize provider output for narrow consistency checks only.

    The facts are derived from composed answer text, not raw retrieved chunks;
    this is deliberately not an independent evidence-validation boundary.
    """
    text = draft.text.strip() if isinstance(draft.text, str) else ""
    facts = tuple(dict.fromkeys(item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", text) if item.strip()))
    heading = draft.section_heading.strip().casefold() if isinstance(draft.section_heading, str) and draft.section_heading.strip() else ""
    return ApprovedFacts("raipur", service_code, service_name, topic, facts, (heading,) if heading else ())


def customer_facts_from_approved(facts: ApprovedFacts) -> CustomerFacts:
    """Project approved prose into typed, customer-only fact slots."""
    text = " ".join(facts.facts)
    duration = re.search(r"\b(?:approximately\s+)?\d+(?:\s*(?:to|-|–)\s*\d+)?\s*(?:minutes?|hours?)\b", text, re.I)
    hours = re.search(r"\b\d{1,2}:\d{2}\s*[AP]M\s*(?:to|-|–)\s*\d{1,2}:\d{2}\s*[AP]M\b", text, re.I)
    return CustomerFacts(
        experience_summary=facts.facts[0] if facts.facts and facts.requested_topic in {None, "overview"} else None,
        benefits=facts.facts[1:4] if facts.requested_topic in {None, "overview", "more_details", "key_characteristics"} else (),
        duration_type="full_day_access" if "full-day" in text.casefold() else "starting_duration" if "starting" in text.casefold() else "ride_duration" if duration else None,
        duration_value=duration.group(0) if duration else None,
        operating_hours=hours.group(0) if hours else None,
        access_type="h2o_play_park" if "h2o play" in text.casefold() else None,
        approved_inclusions=facts.facts[:4] if facts.requested_topic == "inclusions" else (),
        suitability=facts.facts[:4] if facts.requested_topic == "suitable_for" else (),
        relevant_highlights=facts.facts[:4] if facts.requested_topic in {"more_details", "key_characteristics"} else (),
    )


def validate_response_against_facts(plan: MessagePlan, response: str, facts: ApprovedFacts) -> tuple[str, ...]:
    """Deterministic answer checks; no second model is used for validation."""
    value = response.strip() if isinstance(response, str) else ""
    errors: list[str] = []
    if not value: errors.append("empty_response")
    if _INTERNAL_RESPONSE.search(value): errors.append("internal_reference")
    if _EXISTENCE_ONLY.fullmatch(value): errors.append("existence_only")
    approved = " ".join(facts.facts).casefold()
    # Approved numeric facts must survive a model composition unchanged.
    approved_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", approved))
    response_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", value))
    if approved_numbers and not approved_numbers.issubset(response_numbers): errors.append("approved_number_missing")
    if response_numbers - approved_numbers: errors.append("unsupported_number")
    topic = plan.topic
    topic_terms = {
        "capacity": ("capacity", "person", "people", "passenger", "seater", "guest"),
        "duration": ("duration", "minute", "hour", "session", "timing"),
        "inclusions": ("include", "inclusion", "included"),
        "safety": ("safety", "life jacket", "precaution"),
        "swimming": ("swim", "swimming"),
    }
    if topic in topic_terms and not any(term in value.casefold() for term in topic_terms[topic]): errors.append(f"missing_{topic}_answer")
    if "not required" in approved and "mandatory" in value.casefold(): errors.append("negation_changed")
    return tuple(dict.fromkeys(errors))


def deterministic_fact_fallback(facts: ApprovedFacts, language: str) -> str:
    """Last safe answer when a composed answer cannot be validated."""
    if not facts.facts: return "The exact information is not confirmed in the approved information currently available."
    if facts.requested_topic == "swimming":
        return _naturalize_topic_response(" ".join(facts.facts), facts.service_name or "the activity", "swimming")
    if facts.requested_topic == "duration":
        return facts.facts[0]
    lead = f"{facts.service_name} {facts.requested_topic}: " if facts.service_name and facts.requested_topic else ""
    if facts.requested_topic == "inclusions" and len(facts.facts) > 1:
        return lead + "\n• " + "\n• ".join(facts.facts)
    return lead + facts.facts[0]


def normalize_section_heading(value: object) -> str:
    """Compare headings safely across punctuation/case variants."""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip() if isinstance(value, str) else ""


def _is_venue_overview_question(text: str) -> bool:
    """Recognize only broad venue questions, never technical service facts."""

    value = text.casefold()
    technical = bool(re.search(r"\b(?:engine|model|operating|operator|who\s+is|today)\b", value))
    venue_subject = "entartica" in value or ("raipur" in value and "venue" in value)
    broad_request = bool(_VENUE_OVERVIEW.search(value)) or any(
        phrase in value for phrase in (
            "can you give me information", "information about", "ke baare mein batao",
            "tell me about", "what is", "what can we do",
        )
    )
    return venue_subject and broad_request and not technical


def _is_family_activity_discovery_question(text: str) -> bool:
    """Recognize natural family/children fun-activity discovery questions.

    Requires both a family subject and a fun/activity action, so the combined
    approved discovery answer is offered without hijacking named-service,
    celebration-only, or availability questions.  Exact live-availability asks
    are intentionally excluded because they stay with the restricted routing.
    """

    value = text.casefold().strip()
    if not value or "available" in value or "availability" in value:
        return False
    return bool(_FAMILY_ACTIVITY_SUBJECT.search(value) and _FAMILY_ACTIVITY_ACTION.search(value))


def _is_venue_duration_timing_question(text: str, topic: str | None) -> bool:
    """Recognize a venue-level duration/timing question with no specific service.

    The subject must be a generic venue term (rides, activities, water sports,
    celebration services); a pronoun-only follow-up such as ``How long is it?``
    is resolved separately against the previous service context.
    """
    if topic not in {"duration", "operating_hours"}:
        return False
    value = text.casefold().strip()
    if not _VENUE_DURATION_TIMING_SUBJECT.search(value):
        return False
    if _VENUE_DURATION_TIMING_PRONOUN.match(value):
        return False
    return True


def _is_general_venue_timing_question(text: str, topic: str | None) -> bool:
    """Recognize a general venue operating-hours question without a specific
    service or the narrow ride/activity subject vocabulary."""
    if topic != "operating_hours":
        return False
    value = text.casefold().strip()
    if _VENUE_DURATION_TIMING_PRONOUN.match(value):
        return False
    if _GENERAL_VENUE_TIMING_PHRASE.search(value):
        return True
    return bool(_VENUE_TIMING_VENUE_REFERENCE.search(value))


def _is_venue_timing_confirmation(text: str, previous_topic: str | None, previous_service_code: str | None) -> bool:
    """Recognize a follow-up that confirms the general venue timing window.

    Only fires after a general (non-service) operating-hours turn so that
    service-specific timing confirmations stay with the service route.
    """
    if previous_topic != "operating_hours" or previous_service_code is not None:
        return False
    value = text.casefold().strip()
    return bool(_VENUE_TIMING_WINDOW.search(value) and _VENUE_TIMING_CONFIRMATION.search(value))


def _venue_duration_timing_answer(topic: str | None, language: str) -> str:
    """Deterministic venue-level duration/timing answer from approved facts."""
    if topic == "operating_hours":
        if language == "hi":
            return (
                "Entartica Sea World, \u0930\u093e\u092f\u092a\u0941\u0930 \u0915\u0940 operating hours \u0939\u0930 experience \u0915\u0947 \u0939\u093f\u0938\u093e\u092c \u0938\u0947 \u0905\u0932\u0917 \u0939\u0948\u0902:\n\n"
                "- Water sports \u0914\u0930 ride activities: \u0938\u0941\u092c\u0939 10:00 \u092c\u091c\u0947 \u0938\u0947 \u0936\u093e\u092e 6:30 \u092c\u091c\u0947 \u0924\u0915\n"
                "- Celebration services: \u0938\u0941\u092c\u0939 10:00 \u092c\u091c\u0947 \u0938\u0947 \u0930\u093e\u0924 9:00 \u092c\u091c\u0947 \u0924\u0915\n"
                "- Daycation package: \u0926\u094b\u092a\u0939\u0930 2:00 \u092c\u091c\u0947 \u0938\u0947 \u0936\u093e\u092e 6:00 \u092c\u091c\u0947 \u0924\u0915\n"
                "- Staycation package: \u0926\u094b\u092a\u0939\u0930 2:00 \u092c\u091c\u0947 \u0938\u0947 \u0905\u0917\u0932\u0947 \u0926\u093f\u0928 \u0926\u094b\u092a\u0939\u0930 12:00 \u092c\u091c\u0947 \u0924\u0915\n\n"
                "\u0938\u092d\u0940 \u0938\u092e\u092f \u092e\u094c\u0938\u092e \u0914\u0930 \u092a\u0930\u093f\u091a\u093e\u0932\u0928 \u0938\u094d\u0925\u093f\u0924\u093f\u092f\u094b\u0902 \u0915\u0947 \u0905\u0927\u0940\u0928 \u0939\u0948\u0902\u0964 \u0935\u093f\u091c\u093c\u093f\u091f \u0938\u0947 \u092a\u0939\u0932\u0947 Entartica \u091f\u0940\u092e \u0938\u0947 \u0935\u0930\u094d\u0924\u092e\u093e\u0928 \u0938\u092e\u092f \u0915\u0940 \u092a\u0941\u0937\u094d\u091f\u093f \u0915\u0930\u0947\u0902\u0964"
            )
        if language == "hinglish":
            return (
                "Entartica Sea World, Raipur ki operating hours har experience ke hisaab se alag hoti hain:\n\n"
                "- Water sports aur ride activities: 10:00 AM se 6:30 PM\n"
                "- Celebration services: 10:00 AM se 9:00 PM\n"
                "- Daycation package: 2:00 PM se 6:00 PM\n"
                "- Staycation package: 2:00 PM se 12:00 PM agle din tak\n\n"
                "Sabhi timings weather aur operational conditions ke adheen hain. Visit karne se pehle Entartica team se current timings confirm kar lein."
            )
        return (
            "Entartica Sea World, Raipur operating hours vary by experience:\n\n"
            "- Water sports and ride activities: 10:00 AM to 6:30 PM\n"
            "- Celebration services: 10:00 AM to 9:00 PM\n"
            "- Daycation package: 2:00 PM to 6:00 PM\n"
            "- Staycation package: 2:00 PM to 12:00 PM the next day\n\n"
            "All timings are subject to weather and operational conditions. Please confirm current timings with the Entartica team before visiting."
        )
    if language in {"hinglish", "hi"}:
        return "One-Time Access rides aam taur par 5 se 10 minutes tak chalti hain. H2O Playpark activities full-day access mein included hain, 10:00 AM se 6:30 PM tak. Celebration services ki starting duration 30 minutes se 2 hours tak hai."
    return "One-Time Access rides generally last around 5 to 10 minutes. H2O Playpark activities are included in full-day access from 10:00 AM to 6:30 PM, with no individual session duration separately confirmed. Celebration services have starting durations from 30 minutes to 2 hours."


def _venue_timing_confirmation_answer(language: str) -> str:
    """Deterministic confirmation response for the general venue timing window."""
    if language == "hi":
        return (
            "\u0939\u093e\u0901, \u0938\u0941\u092c\u0939 10:00 \u092c\u091c\u0947 \u0938\u0947 \u0936\u093e\u092e 6:30 \u092c\u091c\u0947 \u0924\u0915 Entartica \u0930\u093e\u092f\u092a\u0941\u0930 \u092e\u0947\u0902 water sports \u0914\u0930 ride activities \u0915\u093e \u0938\u093e\u092e\u093e\u0928\u094d\u092f operating window \u0939\u0948\u0964\n\n"
            "Celebration services \u0938\u0941\u092c\u0939 10:00 \u092c\u091c\u0947 \u0938\u0947 \u0930\u093e\u0924 9:00 \u092c\u091c\u0947 \u0924\u0915, Daycation \u0926\u094b\u092a\u0939\u0930 2:00 \u092c\u091c\u0947 \u0938\u0947 \u0936\u093e\u092e 6:00 \u092c\u091c\u0947 \u0924\u0915, \u0914\u0930 Staycation \u0926\u094b\u092a\u0939\u0930 2:00 \u092c\u091c\u0947 \u0938\u0947 \u0905\u0917\u0932\u0947 \u0926\u093f\u0928 \u0926\u094b\u092a\u0939\u0930 12:00 \u092c\u091c\u0947 \u0924\u0915 \u091a\u0932\u0924\u0940 \u0939\u0948\u0902\u0964\n\n"
            "\u0938\u092d\u0940 \u0938\u092e\u092f \u092e\u094c\u0938\u092e \u0914\u0930 \u092a\u0930\u093f\u091a\u093e\u0932\u0928 \u0938\u094d\u0925\u093f\u0924\u093f\u092f\u094b\u0902 \u0915\u0947 \u0905\u0927\u0940\u0928 \u0939\u0948\u0902\u0964"
        )
    if language == "hinglish":
        return (
            "Haan, 10:00 AM se 6:30 PM water sports aur ride activities ka general operating window hai Entartica Raipur mein.\n\n"
            "Celebration services 10:00 AM se 9:00 PM, Daycation 2:00 PM se 6:00 PM, aur Staycation 2:00 PM se 12:00 PM agle din tak chalti hain.\n\n"
            "Sabhi timings weather aur operational conditions ke adheen hain."
        )
    return (
        "Yes, 10:00 AM to 6:30 PM is the general operating window for water sports and ride activities at Entartica Raipur.\n\n"
        "Celebration services generally operate from 10:00 AM to 9:00 PM, Daycation from 2:00 PM to 6:00 PM, and Staycation from 2:00 PM to 12:00 PM the next day.\n\n"
        "All timings are subject to weather and operational conditions."
    )


def _grounding_metadata(answer: KnowledgeDraft, service_code: str | None, topic: str | None) -> dict[str, Any]:
    """Keep available provider grounding internally; never invent source fields."""

    return {
        "source_filename": answer.source_filename if isinstance(answer.source_filename, str) and answer.source_filename.strip() else None,
        "source_document_id": answer.source_document_id if isinstance(answer.source_document_id, str) and answer.source_document_id.strip() else None,
        "source_heading": answer.section_heading if isinstance(answer.section_heading, str) and answer.section_heading.strip() else None,
        "selected_section_heading": answer.section_heading if isinstance(answer.section_heading, str) and answer.section_heading.strip() else None,
        "retrieved_section_headings": list(answer.retrieved_section_headings),
        "retrieval_confidence": answer.confidence if isinstance(answer.confidence, (int, float)) else None,
        "service_code": service_code,
        "topic": topic,
        "answer_source": "provider_composition",
    }


def _is_valid_venue_overview(answer: str) -> bool:
    """Require a venue identity plus multiple experiences before direct delivery."""

    value = answer.casefold().strip()
    if not value or any(term in value for term in (
        "please contact the entartica sales team",
        "please let me know which activity",
        "exact detail is not confirmed",
    )):
        return False
    identity = "entartica sea world" in value and any(term in value for term in ("destination", "activity", "celebration", "water"))
    experiences = sum(term in value for term in ("jet ski", "speed boat", "kayak", "water sports", "celebration", "package", "activities")) >= 2
    return identity and experiences


def _is_technical_specification_question(text: str) -> bool:
    return bool(_TECHNICAL_SPECIFICATION.search(text))


def _topic_isolation_errors(topic: str | None, response: str) -> tuple[str, ...]:
    """Reject adjacent-topic additions for an explicit service question."""

    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", response) if item.strip()]
    if not sentences:
        return ("empty_response",)
    first = sentences[0].casefold()
    rest = " ".join(sentences[1:]).casefold()
    if topic == "duration":
        # An approved H2O Playpark duration answer is the full-day access
        # window policy; it must be accepted as a duration answer and never
        # silently reduced to one sentence by a strict numeric check.
        if not re.search(r"\b(?:\d+\s*(?:to|-)?\s*\d*\s*(?:minutes?|hours?)|duration|session|full-day access)\b", first):
            return ("missing_duration_answer",)
        if any(term in (first + " " + rest) for term in ("current hours", "operating hour", "opening time", "closing time")):
            return ("operating_hours_not_duration",)
        if any(term in rest for term in ("capacity", "guest", "operating hour", "opening", "closing")):
            return ("unrelated_topic_content",)
    if topic == "swimming" and not ("swim" in first and any(term in first for term in ("not required", "required", "yes", "no"))):
        return ("missing_swimming_answer",)
    return ()


def _naturalize_topic_response(response: str, service_name: str, topic: str | None) -> str:
    """Improve only presentation; preserve the provider's approved fact."""

    text = response.strip()
    if topic == "swimming" and re.match(r"^swimming ability is not required\.?", text, re.I):
        display_name = service_name if service_name.casefold().endswith("ride") else f"{service_name} Ride"
        safety = ""
        if "high-buoyancy life jacket" in text.casefold():
            safety = " All passengers are provided with mandatory high-buoyancy life jackets before boarding."
        return f"No, swimming ability is not required for the {display_name}.{safety}"
    return text


def _media_response(label: str, urls: tuple[str, ...]) -> str:
    """Render approved URLs directly so WhatsApp keeps them clickable."""
    if not urls:
        return f"I don't have approved media for {label} yet."
    intro = f"Sure 😊 Here’s a quick look at {label}:"
    return intro + "\n" + "\n".join(urls)


def rank_sections_for_followup(headings: list[str] | tuple[str, ...], used_sections: list[str] | tuple[str, ...], *, explicit_topic: str | None = None) -> list[str]:
    """Keep same-service support, but put unused approved headings first."""
    used = {normalize_section_heading(item) for item in used_sections}
    if explicit_topic:
        wanted = normalize_section_heading(explicit_topic)
        return sorted(headings, key=lambda item: (0 if wanted in normalize_section_heading(item) else 1, normalize_section_heading(item)))
    return sorted(headings, key=lambda item: (normalize_section_heading(item) in used, normalize_section_heading(item)))


def _plan_to_message_plan(plan: Any) -> MessagePlan:
    """Map the current deterministic planner onto the smaller graph contract."""
    intent = getattr(plan, "intent", "general")
    if intent == "greeting": mapped = "greeting"
    elif intent == "contact_information": mapped = "contact_information"
    elif intent == "service_list": mapped = "service_catalogue"
    elif intent in {"service_overview", "service_full_overview", "service_definition"}: mapped = "service_overview"
    elif intent in {"service_detail", "service_more_details", "participation_eligibility", "service_operation_question"}: mapped = "service_topic"
    elif intent == "live_availability": mapped = "availability"
    elif intent == "restricted": mapped = "human_support"
    else: mapped = "general_question"
    topic = getattr(plan, "question_topic", None)
    allowed_topics = {"overview", "suitable_for", "inclusions", "key_characteristics", "capacity", "duration", "swimming", "safety", "operating_hours", "conduct_rules", "onboard_environment", "how_it_works", "eligibility", "location", "more_details", "highlights"}
    return MessagePlan(
        intent=mapped, entity_type="service" if getattr(plan, "service_code", None) else "general",
        service_code=getattr(plan, "service_code", None), topic=topic if topic in allowed_topics else None,
        use_previous_service=getattr(plan, "reference_resolution", "current_message") == "previous_service",
        requires_sales_handover=mapped in _RESTRICTED, confidence=0.7,
        handover_reason=mapped if mapped in _RESTRICTED else None,
    )


class RaipurLangGraphWorkflow:
    """Run one Raipur conversation turn through an explicit LangGraph route."""

    def __init__(self, _legacy_compatibility_container: Any = None, *, planner: RaipurDialoguePlanner | None = None, knowledge: Any = None, services: Any = None, location: dict[str, Any] | None = None, sales_contact: SalesContact | None = None, conversational_fallback: Any = None, customer_understanding: CustomerUnderstandingService | None = None, understanding_enabled: bool = True, understanding_shadow_enabled: bool = False, recommendation_policy: CelebrationRecommendationPolicy | None = None, sales_response_composer: SalesResponseComposer | None = None, sales_agent: SalesAgent | None = None) -> None:
        # The ignored positional argument preserves older test/evaluation call
        # sites during migration.  It is never inspected, stored, or invoked;
        # production wiring supplies every dependency below explicitly.
        self._planner = planner or RaipurDialoguePlanner()
        self._knowledge = knowledge
        self._services = services
        self._location = location
        self._sales_contact = sales_contact
        self._fallback = conversational_fallback
        self._customer_understanding = customer_understanding
        self._understanding_enabled = understanding_enabled
        self._understanding_shadow_enabled = understanding_shadow_enabled
        self._recommendation_policy = recommendation_policy or CelebrationRecommendationPolicy(knowledge)
        self._sales_composer = sales_response_composer
        self._sales_agent = sales_agent
        graph = StateGraph(RaipurGraphState)
        graph.add_node("load_conversation_state", self.load_conversation_state)
        graph.add_node("plan_message", self.plan_message)
        graph.add_node("answer_greeting", self.answer_existing)
        graph.add_node("answer_location", self.answer_existing)
        graph.add_node("approved_sales_contact", self.answer_existing)
        graph.add_node("answer_catalogue", self.answer_existing)
        graph.add_node("answer_service_knowledge", self.answer_existing)
        graph.add_node("answer_venue_knowledge", self.answer_existing)
        graph.add_node("answer_general_openai", self.answer_existing)
        graph.add_node("answer_unknown_entartica_fact", self.answer_existing)
        graph.add_node("handover_to_sales", self.answer_existing)
        graph.add_node("validate_customer_response", self.validate_customer_response)
        graph.add_node("save_conversation_state", self.save_conversation_state)
        graph.add_edge(START, "load_conversation_state")
        graph.add_edge("load_conversation_state", "plan_message")
        graph.add_conditional_edges("plan_message", self.route, {
            "answer_greeting": "answer_greeting", "answer_location": "answer_location",
            "approved_sales_contact": "approved_sales_contact",
            "answer_catalogue": "answer_catalogue", "answer_service_knowledge": "answer_service_knowledge",
            "answer_venue_knowledge": "answer_venue_knowledge", "answer_general_openai": "answer_general_openai",
            "answer_unknown_entartica_fact": "answer_unknown_entartica_fact",
            "handover_to_sales": "handover_to_sales",
        })
        for node in ("answer_greeting", "answer_location", "approved_sales_contact", "answer_catalogue", "answer_service_knowledge", "answer_venue_knowledge", "answer_general_openai", "answer_unknown_entartica_fact", "handover_to_sales"):
            graph.add_edge(node, "validate_customer_response")
        graph.add_edge("validate_customer_response", "save_conversation_state")
        graph.add_edge("save_conversation_state", END)
        self._graph = graph.compile()

    def _approved_pontoon_package(self):
        method = getattr(self._knowledge, "approved_pontoon_package", None)
        if not callable(method):
            return None
        try:
            return method()
        except Exception:
            return None

    def invoke(self, state: RaipurGraphState, *, message: Any, customer: dict[str, Any], conversation: dict[str, Any], source_message_id: str, current_state: Any = None) -> Any:
        started = perf_counter()
        runtime = {"message": message, "customer": customer, "conversation": conversation, "source_message_id": source_message_id, "current_state": current_state}
        # LangGraph state stays safe/serializable; runtime-only objects never persist in it.
        final = self._graph.invoke(self._fresh_turn_state(state, runtime))  # type: ignore[arg-type]
        result = final.get("result")
        if not isinstance(result, ConversationResult):
            return result
        metadata = dict(result.safe_metadata or {})
        metadata.update({
            "understanding_invoked": bool(final.get("understanding_invoked")),
            "understanding_failed": bool(final.get("understanding_failed")),
        })
        if isinstance(final.get("customer_understanding"), dict):
            metadata["customer_understanding"] = final["customer_understanding"]
        result = replace(result, safe_metadata=metadata)
        event = build_conversation_telemetry(
            conversation_id=str(conversation.get("id") or state.get("conversation_id") or ""),
            message_id=source_message_id,
            before=current_state if isinstance(current_state, ConversationContext) else None,
            result=result,
            trace=current_latency_trace(),
            local_total_ms=round((perf_counter() - started) * 1000),
        )
        return replace(result, safe_metadata={**metadata, "conversation_telemetry": event.as_safe_dict()})

    def load_conversation_state(self, state: RaipurGraphState) -> dict[str, Any]:
        self._log_node("load_conversation_state", state)
        # Current-turn values are deliberately reset even if a caller reused a
        # state mapping.  Persisted context is limited to the explicit
        # ``previous_*`` fields constructed for this invocation.
        return {
            "intent": None, "entity_type": "unknown", "service_code": None,
            "topic": None, "selected_route": None, "route": None,
            "use_previous_service": False, "requires_handover": False,
            "handover_reason": None, "retrieved_context": (), "retrieved_sources": (),
            "answer_source": None, "source_filename": None, "draft_response": None,
            "validation_status": "pending", "validation_errors": [], "error": None,
            "plan_consistency_repaired": False,
        }

    def plan_message(self, state: RaipurGraphState) -> dict[str, Any]:
        text = state["normalized_message"]
        current = state.get("_runtime", {}).get("current_state")
        celebration_occasion_pending = bool(
            getattr(current, "pending_clarification", False)
            and getattr(current, "pending_clarification_type", None) == "celebration_occasion"
        )
        deterministic = self._deterministic_plan(
            text,
            state.get("previous_service_code"),
            state.get("previous_topic"),
            celebration_occasion_pending=celebration_occasion_pending,
            celebration_pending_field=getattr(current, "pending_field", None),
            pending_service_code=getattr(current, "pending_service_code", None),
        )
        use_sales_agent = self._should_use_combined_sales_agent(text, current, deterministic)
        understanding = None
        understanding_failed = False
        should_understand = self._should_use_customer_understanding(text, current, deterministic) and not use_sales_agent
        if self._customer_understanding is not None and (
            (self._understanding_enabled and should_understand) or self._understanding_shadow_enabled
        ):
            with latency_stage("customer_understanding"):
                understanding, understanding_failed = self._customer_understanding.understand_observed(text, current)
        mapped = deterministic
        if self._understanding_enabled and should_understand and understanding is not None:
            assisted = self._plan_from_understanding(understanding, current, deterministic)
            if assisted is not None:
                mapped = assisted
        if mapped is None:
            plan = self._planner.plan(text, state.get("_runtime", {}).get("current_state"), language=state["language"])
            mapped = _plan_to_message_plan(plan)
        mapped, repaired = self._repair_plan_consistency(text, mapped, state.get("previous_service_code"))
        selected_route = self._route_for(mapped.intent, mapped.requires_sales_handover)
        shadow = understanding.model_dump(mode="json") if understanding is not None and self._understanding_shadow_enabled else None
        update = {
            "intent": mapped.intent, "entity_type": mapped.entity_type,
            "service_code": mapped.service_code, "topic": mapped.topic,
            "selected_route": selected_route, "route": selected_route,
            "use_previous_service": mapped.use_previous_service,
            "requires_handover": mapped.requires_sales_handover,
            "handover_reason": mapped.handover_reason,
            "answer_source": None, "source_filename": None,
            "validation_errors": [], "plan_consistency_repaired": repaired,
            "understanding_invoked": understanding is not None,
            "understanding_failed": understanding_failed,
            "use_sales_agent": use_sales_agent,
        }
        if shadow is not None:
            update["customer_understanding_shadow"] = shadow
        if understanding is not None and self._understanding_enabled and should_understand:
            update["customer_understanding"] = understanding.model_dump(mode="json")
        self._log_node("plan_message", {**state, **update})
        return update

    def _should_use_combined_sales_agent(
        self, text: str, context: ConversationContext | None, deterministic: MessagePlan | None,
    ) -> bool:
        """Combine only turns that would otherwise understand then compose."""
        if self._sales_agent is None or not self._sales_agent.configured or deterministic is None:
            return False
        if deterministic.intent not in {"celebration_service_list", "service_catalogue", "family_activity_discovery"}:
            return False
        return self._should_use_customer_understanding(text, context, deterministic)

    def _should_use_customer_understanding(
        self,
        text: str,
        context: ConversationContext | None,
        deterministic: MessagePlan | None,
    ) -> bool:
        """Gate structured extraction away from obvious deterministic routes."""
        if self._customer_understanding is None:
            return False
        fast_intents = {
            "greeting", "location", "contact_information", "pricing", "booking",
            "availability", "payment", "cancellation_refund", "human_support",
            "service_overview", "service_topic", "contextual_service_followup",
            "venue_duration_timing", "venue_timing_confirmation", "h2o_playpark",
            "celebration_guest_count", "celebration_planned_date", "celebration_cancel",
        }
        if deterministic is not None and deterministic.intent in fast_intents:
            return False
        active_sales = isinstance(context, ConversationContext) and (
            context.pending_action == "celebration_sales"
            or context.pending_field in {"total_guests", "preferred_date", "celebration_preference"}
            or context.active_topic in {"celebration_catalogue", "activity_catalogue"}
            or context.sales_stage in {SalesStage.OPTIONS_SHOWN, SalesStage.QUALIFYING, SalesStage.QUALIFIED}
        )
        if active_sales:
            return True
        value = text.casefold()
        sales_cue = re.search(
            r"\b(?:birthday|anniversary|celebrat\w*|special\s+event|corporate\s+event|client\s+event|"
            r"guests?|people|log|family|couple|private|intimate|lively|relaxed|water\s+fun)\b",
            value,
        )
        if not sales_cue and (_has_near_celebration_token(value) or _FAMILY_ACTIVITY_SUBJECT.search(value)):
            sales_cue = True
        multi_fact = bool(sales_cue and (re.search(r"\b\d{1,4}\b", value) or re.search(r"\b(?:on|tomorrow|this\s+\w+|august|september|october|november|december)\b", value)))
        return bool(multi_fact or (deterministic is None and sales_cue))

    @staticmethod
    def _plan_from_understanding(
        understanding: CustomerUnderstanding,
        context: ConversationContext | None,
        deterministic: MessagePlan | None,
    ) -> MessagePlan | None:
        """Translate clear sales meaning only; deterministic policy stays first."""
        if understanding.confidence < 0.65:
            return None
        active_sales = isinstance(context, ConversationContext) and (
            context.pending_action == "celebration_sales"
            or context.active_topic in {"celebration_catalogue", "activity_catalogue"}
        )
        has_current_sales_fact = any((
            understanding.occasion,
            understanding.guest_count,
            understanding.planned_date_text,
            understanding.preference,
        ))
        if active_sales and has_current_sales_fact:
            return MessagePlan(intent="customer_understanding_update", entity_type="catalogue", confidence=understanding.confidence)
        if understanding.intent == "celebration":
            if understanding.guest_count is not None and understanding.planned_date_text and understanding.preference:
                return MessagePlan(intent="customer_understanding_update", entity_type="catalogue", confidence=understanding.confidence)
            return deterministic or MessagePlan(intent="celebration_service_list", entity_type="catalogue", confidence=understanding.confidence)
        if understanding.intent == "family_discovery":
            return MessagePlan(intent="family_activity_discovery", entity_type="catalogue", confidence=understanding.confidence)
        if active_sales and understanding.preference is not None:
            return MessagePlan(intent="customer_understanding_update", entity_type="catalogue", confidence=understanding.confidence)
        return None

    def _deterministic_plan(
        self,
        text: str,
        previous_service_code: str | None,
        previous_topic: str | None = None,
        *,
        celebration_occasion_pending: bool = False,
        celebration_pending_field: str | None = None,
        pending_service_code: str | None = None,
    ) -> MessagePlan | None:
        """High-confidence policy ordering; never allow stale context to win."""
        if pending_service_code and _SERVICE_CONFIRM_YES.fullmatch(text):
            return MessagePlan(intent="service_confirmation", entity_type="service", service_code=pending_service_code, topic="overview", confidence=1.0)
        if pending_service_code and _SERVICE_CONFIRM_NO.fullmatch(text):
            return MessagePlan(intent="service_confirmation_rejected", entity_type="general", confidence=1.0)
        # Specific contact phrases (notably "email address") must not be
        # mistaken for a physical-address request.
        if is_contact_information_request(text):
            return MessagePlan(intent="contact_information", entity_type="venue", use_previous_service=False, confidence=1.0)
        if is_location_question(text) or bool(re.search(r"\b(?:address|location|google\s+maps|map\s+link)\b", text, re.I)):
            return MessagePlan(intent="location", entity_type="venue", topic=None, confidence=1.0)
        if _is_greeting_or_closing(text):
            return MessagePlan(intent="greeting", entity_type="general", use_previous_service=False, confidence=1.0)
        service_resolution = resolve_service(text)
        service = service_resolution.service
        topic = topic_for_graph(resolve_topic(text))
        if service is not None and is_h2o_service_code(knowledge_service_code(service)) and asks_individual_turn_duration(text):
            topic = "duration"
        if service is not None and previous_service_code is None and re.search(r"\b(?:in general|generally speaking|as a sport|as an activity)\b", text, re.I):
            return MessagePlan(intent="general_question", entity_type="general", confidence=1.0)
        catalogue_type = requested_catalogue_type(text, catalogue_type_from_topic(previous_topic))
        category_request = catalogue_type is not None or is_service_catalogue_question(text)
        activity_preference = re.fullmatch(
            r"\s*(?:adventure|water\s+adventure|private|intimate|relaxed|lively|couple)\s*[?.!]*\s*",
            text,
            re.I,
        )
        natural_activity_preference = is_activity_preference_followup(text)
        family_preference = re.fullmatch(
            r"\s*(?:family(?:\s+fun)?|kids?|children)\s*[?.!]*\s*",
            text,
            re.I,
        )
        if service is None and topic == "highlights":
            if catalogue_type in {"activity", "celebration"}:
                return MessagePlan(intent="category_media", entity_type="catalogue", topic="highlights", confidence=1.0)
            if re.search(r"\b(?:entartica|raipur|venue)\b", text, re.I):
                return MessagePlan(intent="venue_media", entity_type="venue", topic="highlights", confidence=1.0)
        # A short abandon message while a celebration flow is pending is an
        # in-flow cancel, not a refund/cancellation policy request.
        if previous_topic == "celebration_catalogue" and _is_celebration_cancel_request(text):
            return MessagePlan(intent="celebration_cancel", entity_type="general", use_previous_service=False, confidence=1.0)
        restricted = (("pricing", ("price", "pricing", "cost", "quote", "quotation")), ("booking", ("book", "booking", "reserve")), ("availability", ("available", "availability", "slot")), ("payment", ("payment", "pay")), ("cancellation_refund", ("cancel", "refund")), ("human_support", ("human", "agent", "sales", "contact")))
        if re.search(r"\b(?:custom(?:ize|ise|ization|isation)?|different\s+cake|special\s+(?:food|arrangement)|change(?:d)?\s+inclusions?)\b", text, re.I):
            return MessagePlan(intent="human_support", entity_type="service", service_code=previous_service_code, requires_sales_handover=True, handover_reason="customization", confidence=1.0)
        for intent, terms in restricted:
            # “What rides are available?” requests a catalogue; it is not a
            # live slot check. Exact availability requests still win here.
            if intent == "availability" and (
                category_request or (service is not None and topic == "operating_hours")
            ):
                continue
            if any(term in text for term in terms):
                return MessagePlan(intent=intent, entity_type="service", requires_sales_handover=True, handover_reason=intent, confidence=1.0)
        if _is_technical_specification_question(text):
            return MessagePlan(
                intent="unknown_entartica_fact", entity_type="service" if service is not None else "general",
                service_code=knowledge_service_code(service) if service is not None else None, topic="technical_specification",
                use_previous_service=False, confidence=1.0,
            )
        # Explicit service questions remain higher priority than an outstanding
        # sales question. Only a valid answer to the pending field is consumed.
        if service is None and celebration_pending_field == "total_guests" and _celebration_guest_count(text) is not None:
            return MessagePlan(intent="celebration_guest_count", entity_type="catalogue", confidence=1.0)
        if service is None and celebration_pending_field == "preferred_date" and _celebration_date(text) is not None:
            return MessagePlan(intent="celebration_planned_date", entity_type="catalogue", confidence=1.0)
        qualification = deterministic_celebration_understanding(text)
        if service is None and qualification is not None and (
            celebration_pending_field in {"total_guests", "preferred_date", "celebration_preference"}
            or previous_service_code == "pontoon_celebration"
        ):
            return MessagePlan(intent="customer_understanding_update", entity_type="catalogue", confidence=1.0)
        if (
            service is None
            and celebration_pending_field == "celebration_preference"
            and self._sales_agent is not None and self._sales_agent.configured
            and re.search(r"\b(?:private|intimate|lively|party-style|relaxed|calm|couple)\b", text, re.I)
        ):
            return MessagePlan(intent="celebration_service_list", entity_type="catalogue", confidence=1.0)
        if celebration_occasion_pending:
            if re.search(r"\bwhere\s+is\s+(?:entartica(?:\s+raipur)?|raipur)\b", text, re.I):
                return MessagePlan(intent="location", entity_type="venue", confidence=1.0)
            if re.search(r"\b(?:your|venue|entartica|raipur)\s+timings?\b", text, re.I):
                return MessagePlan(intent="venue_duration_timing", entity_type="venue", topic="operating_hours", confidence=1.0)
        # A persisted occasion prompt consumes the next non-empty free-text
        # answer deterministically. Restricted intents, cancel, and explicit
        # approved services have already won above, so the planner/OpenAI path
        # must never re-qualify the same occasion.
        if celebration_occasion_pending and text.strip():
            if service is not None:
                code = knowledge_service_code(service)
                topic = topic_for_graph(resolve_topic(text))
                return MessagePlan(
                    intent="service_topic" if topic else "service_overview",
                    entity_type="service", service_code=code, topic=topic or "overview",
                    confidence=1.0,
                )
            return MessagePlan(intent="celebration_service_list", entity_type="catalogue", confidence=1.0)
        if service is None and previous_topic == "activity_catalogue" and family_preference:
            return MessagePlan(intent="family_activity_discovery", entity_type="catalogue", use_previous_service=False, confidence=1.0)
        if service is None and previous_topic == "activity_catalogue" and (activity_preference or natural_activity_preference):
            return MessagePlan(intent="service_catalogue", entity_type="catalogue", use_previous_service=False, confidence=1.0)
        if service is None and catalogue_type != "kids_activity" and _is_family_activity_discovery_question(text):
            return MessagePlan(intent="family_activity_discovery", entity_type="catalogue", use_previous_service=False, confidence=1.0)
        if _is_venue_timing_confirmation(text, previous_topic, previous_service_code):
            return MessagePlan(intent="venue_timing_confirmation", entity_type="venue", topic="operating_hours", use_previous_service=False, confidence=1.0)
        if service is None and _is_venue_duration_timing_question(text, topic):
            return MessagePlan(intent="venue_duration_timing", entity_type="venue", topic=topic, use_previous_service=False, confidence=1.0)
        if service is None and _is_general_venue_timing_question(text, topic):
            return MessagePlan(intent="venue_duration_timing", entity_type="venue", topic=topic, use_previous_service=False, confidence=1.0)
        if service is None and catalogue_type == "celebration":
            return MessagePlan(intent="celebration_service_list", entity_type="catalogue", confidence=1.0)
        if service is None and catalogue_type in {"activity", "kids_activity"}:
            return MessagePlan(intent="service_catalogue", entity_type="catalogue", confidence=1.0)
        if service is None and (catalogue_type == "package" or category_request):
            return MessagePlan(intent="service_catalogue", entity_type="catalogue", confidence=1.0)
        if service is None and _is_general_celebration_intent(text):
            return MessagePlan(intent="celebration_service_list", entity_type="catalogue", use_previous_service=False, confidence=1.0)
        if service is not None:
            code = knowledge_service_code(service)
            mapped_topic = topic
            return MessagePlan(intent="service_topic" if mapped_topic else "service_overview", entity_type="service", service_code=code, topic=mapped_topic or "overview", confidence=0.98)
        candidate = _fuzzy_service_candidate(text)
        if candidate is not None:
            return MessagePlan(intent="service_confirmation", entity_type="service", service_code=knowledge_service_code(candidate), confidence=0.8)
        if is_h2o_playpark_question(text):
            return MessagePlan(intent="h2o_playpark", entity_type="general", use_previous_service=False, confidence=1.0)
        followup = any(term in text for term in ("tell me more", "more details", "how long is it", "isme", "usme", "it?"))
        if previous_service_code and (followup or topic is not None):
            followup_topic = topic
            return MessagePlan(intent="contextual_service_followup", entity_type="service", service_code=previous_service_code, topic=followup_topic or "more_details", use_previous_service=True, confidence=0.9)
        if any(term in text for term in _FACILITY_WORDS):
            return MessagePlan(intent="venue_facility", entity_type="venue", use_previous_service=False, confidence=1.0)
        if _is_venue_overview_question(text):
            return MessagePlan(intent="venue_overview", entity_type="venue", use_previous_service=False, confidence=0.9)
        if "entartica" in text or "sea world" in text:
            return MessagePlan(intent="unknown_entartica_fact", entity_type="venue", confidence=0.7)
        return None

    def route(self, state: RaipurGraphState) -> str:
        selected = state.get("selected_route")
        if isinstance(selected, str): return selected
        return self._route_for(state.get("intent"), bool(state.get("requires_handover")))

    @staticmethod
    def _route_for(intent: str | None, requires_handover: bool) -> str:
        if requires_handover or intent in _RESTRICTED: return "handover_to_sales"
        if intent == "greeting": return "answer_greeting"
        if intent == "location": return "answer_location"
        if intent == "contact_information": return "approved_sales_contact"
        if intent in {"service_catalogue", "activity_service_list", "celebration_service_list"}: return "answer_catalogue"
        if intent in {"service_overview", "service_topic", "contextual_service_followup"}: return "answer_service_knowledge"
        if intent in {"venue_overview", "venue_facility", "h2o_playpark", "venue_duration_timing", "venue_timing_confirmation", "family_activity_discovery", "celebration_occasion_clarification", "celebration_cancel", "celebration_guest_count", "celebration_planned_date", "celebration_preference", "customer_understanding_update", "service_confirmation", "service_confirmation_rejected", "category_media", "venue_media"}: return "answer_venue_knowledge"
        if intent == "unknown_entartica_fact": return "answer_unknown_entartica_fact"
        return "answer_general_openai"

    @staticmethod
    def _fresh_turn_state(state: RaipurGraphState, runtime: dict[str, Any]) -> RaipurGraphState:
        """Construct a new isolated graph state; never reuse current-turn data."""
        current = runtime.get("current_state")
        inbound = runtime.get("message")
        message = getattr(inbound, "content", "") if isinstance(getattr(inbound, "content", None), str) else ""
        return {
            "message_id": state.get("message_id", ""), "conversation_id": state.get("conversation_id", ""),
            "customer_id": state.get("customer_id", ""), "customer_message": message,
            "normalized_message": message.casefold().strip(),
            "language": state.get("language", "en"), "location_code": "raipur",
            "previous_service_code": getattr(current, "last_service_code", state.get("previous_service_code")),
            "previous_topic": getattr(current, "active_topic", state.get("previous_topic")),
            "intent": None, "entity_type": "unknown", "service_code": None, "topic": None,
            "selected_route": None, "route": None, "use_previous_service": False,
            "requires_handover": False, "handover_reason": None,
            "retrieved_context": (), "retrieved_sources": (), "answer_source": None,
            "source_filename": None, "draft_response": None, "validation_status": "pending",
            "validation_errors": [], "error": None, "plan_consistency_repaired": False,
            "invocation_id": uuid4().hex, "_runtime": runtime,
        }

    def _repair_plan_consistency(self, text: str, mapped: MessagePlan, previous_service_code: str | None) -> tuple[MessagePlan, bool]:
        """Current explicit entities deterministically override a stale planner result."""
        if mapped.intent in _RESTRICTED or mapped.intent in {"unknown_entartica_fact", "general_question", "greeting", "h2o_playpark", "venue_duration_timing", "venue_timing_confirmation", "family_activity_discovery", "celebration_occasion_clarification", "celebration_cancel"}:
            return mapped, False
        service_resolution = resolve_service(text)
        service = service_resolution.service
        raw_topic = topic_for_graph(resolve_topic(text))
        if service is not None and is_h2o_service_code(knowledge_service_code(service)) and asks_individual_turn_duration(text):
            raw_topic = "duration"
        if service is not None:
            code = knowledge_service_code(service)
            explicit_topic = raw_topic
            expected_intent = "service_topic" if explicit_topic else "service_overview"
            expected_topic = explicit_topic or "overview"
            if (mapped.service_code, mapped.topic, mapped.intent, mapped.use_previous_service) != (code, expected_topic, expected_intent, False):
                return MessagePlan(intent=expected_intent, entity_type="service", service_code=code, topic=expected_topic, use_previous_service=False, confidence=1.0), True
        if raw_topic and mapped.service_code == previous_service_code:
            explicit_topic = raw_topic
            if mapped.topic != explicit_topic:
                return MessagePlan(intent="contextual_service_followup", entity_type="service", service_code=previous_service_code, topic=explicit_topic, use_previous_service=True, confidence=1.0), True
        return mapped, False

    @staticmethod
    def _log_node(node_name: str, state: dict[str, Any]) -> None:
        logger.info(
            "raipur_graph_node message_id=%s node_name=%s message_character_count=%s current_intent=%s current_service_code=%s current_topic=%s previous_service_code=%s previous_topic=%s use_previous_service=%s selected_route=%s plan_consistency_repaired=%s invocation_id=%s",
            state.get("message_id", ""), node_name, len(state.get("normalized_message", "")),
            state.get("intent") or "none", state.get("service_code") or "none", state.get("topic") or "none",
            state.get("previous_service_code") or "none", state.get("previous_topic") or "none",
            bool(state.get("use_previous_service")), state.get("selected_route") or "none",
            bool(state.get("plan_consistency_repaired")), state.get("invocation_id", ""),
        )

    def answer_existing(self, state: RaipurGraphState) -> dict[str, Any]:
        """Graph-owned answers.  The legacy full conversation processor is never called here."""
        runtime = state["_runtime"]; text = state["customer_message"]; language = state["language"]
        context = runtime.get("current_state")
        if not isinstance(context, ConversationContext):
            context = ConversationContext(BookingDetails(runtime["customer"].get("name"), None, None, None, None, None, None, special_requirements_collected=False))
        if state.get("intent") == "celebration_service_list" and should_reset_for_new_celebration_journey(context, text):
            context = reset_for_new_celebration_journey(context)
        active_or_selected_pontoon = (
            context.last_service_code == "pontoon_celebration"
            or state.get("service_code") == "pontoon_celebration"
        )
        pontoon_past_date_rejected = False
        structured = state.get("customer_understanding")
        if isinstance(structured, dict):
            try:
                understanding = CustomerUnderstanding.model_validate(structured)
                planned = parse_planned_date_text(understanding.planned_date_text)
                if active_or_selected_pontoon and planned is not None and pontoon_date_is_past(planned):
                    understanding = understanding.model_copy(update={"planned_date_text": None})
                    context = replace(context, details=replace(context.details, preferred_date=None))
                    pontoon_past_date_rejected = True
                context = apply_customer_understanding(context, understanding)
            except Exception:
                pass
        if active_or_selected_pontoon:
            deterministic_slots = deterministic_celebration_understanding(text)
            if deterministic_slots is not None:
                planned = parse_planned_date_text(deterministic_slots.planned_date_text)
                if planned is not None and pontoon_date_is_past(planned):
                    deterministic_slots = deterministic_slots.model_copy(update={"planned_date_text": None})
                    context = replace(context, details=replace(context.details, preferred_date=None))
                    pontoon_past_date_rejected = True
                context = apply_customer_understanding(context, deterministic_slots)
        route = self.route(state)
        response_basis, handover, source = "deterministic", False, route
        grounding: dict[str, Any] = {
            "service_code": state.get("service_code"),
            "topic": state.get("topic"),
        }
        if isinstance(state.get("customer_understanding_shadow"), dict):
            grounding["customer_understanding_shadow"] = state["customer_understanding_shadow"]
        # A deterministic family-discovery decision must not be re-interpreted
        # by the shared category handler, which would otherwise reduce the
        # combined rides-plus-celebrations answer to a plain activity list.
        category = None
        catalogue_recommendation = None
        celebration_followup = None
        if state.get("intent") not in {"family_activity_discovery", "category_media", "venue_media"}:
            pending_occasion_answer = bool(
                context.pending_clarification
                and context.pending_clarification_type == "celebration_occasion"
                and state["intent"] == "celebration_service_list"
            )
            if state["intent"] == "celebration_service_list":
                celebration_followup, catalogue_recommendation = self._celebration_sales_response(
                    context, language, runtime["conversation"].get("location_id")
                )
            category = handle_raipur_category_request(
                text, language, self._active_service_rows(runtime["conversation"].get("location_id")),
                previous_catalogue_type=catalogue_type_from_topic(context.active_topic),
                consume_pending_celebration_occasion=pending_occasion_answer,
                force_celebration_catalogue=state["intent"] == "celebration_service_list",
                celebration_followup=celebration_followup,
            )
        if category is not None and category.handled:
            draft = category.response_text or self._safe_fallback(language)
            intent = "activity_service_list" if category.catalogue_type == "activity" else category.intent or "service_catalogue"
            source = category.answer_source or "approved_category"
            grounding.update({
                "shared_handler_used": True,
                "answer_source": source,
                "catalogue_route": category.route,
                "catalogue_type": category.catalogue_type,
                "catalogue_source": category.catalogue_source,
                "catalogue_filter": category.catalogue_filter,
                "catalogue_item_count": category.catalogue_item_count,
            })
            if isinstance(catalogue_recommendation, RecommendationDecision):
                grounding.update({
                    "recommended_service_codes": list(catalogue_recommendation.recommended_service_codes),
                    "recommendation_strength": catalogue_recommendation.strength,
                    "recommendation_reason": catalogue_recommendation.reason,
                    "recommendation_insufficient_evidence": catalogue_recommendation.insufficient_evidence,
                    "recommendation_invoked": True,
                    "occasion_evidence_used": catalogue_recommendation.occasion_evidence_used,
                    "preference_evidence_used": catalogue_recommendation.preference_evidence_used,
                    "capacity_compatibility": [
                        {"service_code": item.service_code, "guest_count": item.guest_count, "compatible": item.compatible, "capacity_status": item.capacity_status.value if item.capacity_status else None}
                        for item in catalogue_recommendation.capacity_compatibility
                    ],
                })
            combined_used = False
            if category.catalogue_type == "celebration":
                options = tuple(item.name for item in APPROVED_RAIPUR_SERVICES if item.category == "floating_celebration")
                slots = context.pending_slots or {}
                response_brief = SalesResponseBrief(
                        ResponseGoal.SERVICE_RECOMMENDATION if catalogue_recommendation else ResponseGoal.CELEBRATION_DISCOVERY,
                        language, approved_options=options,
                        approved_facts=(draft,),
                        known_occasion=slots.get("occasion"), known_guest_count=context.details.total_guests,
                        known_date=context.details.preferred_date.isoformat() if context.details.preferred_date else None,
                        known_preference=slots.get("celebration_preference") or slots.get("preference"),
                        recommended_service_codes=tuple(catalogue_recommendation.recommended_service_codes) if catalogue_recommendation else (),
                        next_action=evaluate_sales_next_action(context).action.value,
                        next_question=celebration_followup if not catalogue_recommendation else None,
                    )
                if state.get("use_sales_agent"):
                    draft, context, combined_used = self._compose_sales_agent(response_brief, text, context, draft, grounding)
                if not combined_used:
                    draft = self._compose_sales(response_brief, draft, grounding)
            elif category.catalogue_type == "activity":
                options = tuple(
                    row["name"] for row in self._active_service_rows(runtime["conversation"].get("location_id"))
                    if isinstance(row.get("name"), str)
                    and getattr(approved_service_from_message(row.get("name")), "category", None) == "water_ride"
                )
                response_brief = SalesResponseBrief(
                    ResponseGoal.ACTIVITY_DISCOVERY, language, approved_options=options,
                    approved_facts=(draft,),
                )
                if state.get("use_sales_agent"):
                    draft, context, combined_used = self._compose_sales_agent(response_brief, text, context, draft, grounding)
                if not combined_used:
                    draft = self._compose_sales(response_brief, draft, grounding)
            context = set_catalogue_context(context, category.catalogue_type or "").updated_context or context
            if category.catalogue_type == "celebration":
                context = _progress_celebration_sales_context(context)
                context = replace(context, last_assistant_question=self._celebration_sales_response(context, language, runtime["conversation"].get("location_id"))[0])
            if pending_occasion_answer:
                slots = dict(context.pending_slots or {})
                slots["occasion"] = text.strip()
                context = context.__class__(**{**context.__dict__, "pending_slots": slots})
        elif route == "answer_greeting":
            acknowledged = is_acknowledgement(state["normalized_message"])
            draft, intent = (acknowledgement_response(language) if acknowledged else greeting_response(language)), "greeting"
            if not acknowledged:
                context = self._clear_service_context(context)
        elif route == "answer_location":
            draft, intent = structured_location_answer(self._location, language) or self._safe_fallback(language), "location"
            context = self._clear_service_context(context)
        elif route == "approved_sales_contact":
            draft = approved_contact_information(self._sales_contact, language) if self._sales_contact is not None else self._safe_fallback(language)
            intent, source = "contact_information", "approved_sales_contact"
            grounding.update({"structured_grounding": True, "answer_source": source, "response_mode": "direct_contact_details"})
            context = self._clear_service_context(context)
        elif route == "answer_catalogue":
            draft, intent = self._catalogue(language, runtime["conversation"].get("location_id")), "service_catalogue"
            context = self._clear_service_context(context)
        elif route == "handover_to_sales":
            draft, intent, handover = self._handover(state, language), state["intent"], True
            if context.last_service_code == "pontoon_celebration":
                context = replace(
                    context, active_journey="celebration", pending_field=None,
                    pending_question_type=None, pending_action="celebration_sales",
                    sales_stage=SalesStage.HANDOVER,
                )
            else:
                context = self._clear_service_context(context)
        elif route == "answer_service_knowledge":
            draft, context, response_basis, grounding = self._service_answer(state, context, text, language)
            intent = state["intent"]
        elif route == "answer_venue_knowledge":
            if state["intent"] in {"category_media", "venue_media"}:
                scope = "venue" if state["intent"] == "venue_media" else requested_catalogue_type(text, catalogue_type_from_topic(context.active_topic))
                media = self._knowledge.experience_media(scope=scope or "venue", category=scope) if self._knowledge is not None and hasattr(self._knowledge, "experience_media") else None
                urls = tuple(getattr(media, "urls", ()))
                label = "Entartica Sea World Raipur" if scope == "venue" else "Raipur water activities" if scope == "activity" else "Raipur celebrations"
                draft = _media_response(label, urls)
                intent, response_basis, source = state["intent"], "active_rag", "approved_experience_media"
                grounding.update({"structured_grounding": True, "answer_source": source, "media_scope": getattr(media, "scope", scope), "media_source": getattr(media, "source_document", None), "media_url_count": len(urls)})
                if scope in {"activity", "celebration"}:
                    context = set_catalogue_context(context, scope).updated_context or context
                else:
                    context = self._clear_service_context(context)
            elif state["intent"] == "service_confirmation":
                candidate = next((item for item in APPROVED_RAIPUR_SERVICES if knowledge_service_code(item) == state.get("service_code")), None)
                confirming = bool(context.pending_service_code and _SERVICE_CONFIRM_YES.fullmatch(text))
                if candidate is not None and confirming:
                    service_state = {**state, "intent": "service_overview", "topic": "overview", "use_previous_service": False}
                    cleared = replace(context, pending_question_type=None, pending_action=None, pending_service_code=None, pending_entity_type=None, pending_entity_name=None)
                    draft, context, response_basis, grounding = self._service_answer(service_state, cleared, candidate.name, language)
                    intent, source = "service_overview", "service_confirmation_accepted"
                    grounding.update({"service_confirmation": "accepted", "answer_source": source})
                elif candidate is not None:
                    draft = f"Do you mean *{candidate.name}*?"
                    intent, response_basis, source = "service_confirmation", "clarification", "service_confirmation"
                    context = replace(
                        context, last_service_name=None, last_service_code=None, active_topic=None,
                        active_entity_type=None, active_entity_name=None, service_selection_prompted=False,
                        pending_question_type="yes_no", pending_action="provide_service_details",
                        pending_entity_type="service", pending_entity_name=candidate.name,
                        pending_service_code=knowledge_service_code(candidate),
                    )
                    grounding.update({"service_code": knowledge_service_code(candidate), "service_confirmation": "pending", "answer_source": source})
                else:
                    draft, intent, response_basis, source = self._safe_fallback(language), "service_confirmation", "clarification", "service_confirmation"
            elif state["intent"] == "service_confirmation_rejected":
                draft = "No problem. Which service would you like to know about? I can show the approved Raipur options if helpful."
                intent, response_basis, source = "service_confirmation_rejected", "clarification", "service_confirmation_rejected"
                context = replace(context, pending_question_type=None, pending_action=None, pending_service_code=None, pending_entity_type=None, pending_entity_name=None)
                grounding.update({"service_confirmation": "rejected", "answer_source": source})
            elif state["intent"] == "h2o_playpark":
                draft = h2o_playpark_answer(language)
                intent, response_basis = "h2o_playpark", "deterministic"
                source = "h2o_playpark"
                grounding.update({"structured_grounding": True, "answer_source": source, "response_mode": "h2o_playpark"})
                draft = self._compose_sales(SalesResponseBrief(
                    ResponseGoal.FACTUAL_ANSWER, language, approved_facts=(draft,),
                    customer_facts=CustomerFacts(duration_type="full_day_access", operating_hours="10:00 AM to 6:30 PM", access_type="h2o_play_park"),
                ), draft, grounding)
                context = self._clear_service_context(context)
            elif state["intent"] == "venue_facility":
                draft, grounding = "This facility information is not confirmed in the approved knowledge currently available.", {"answer_source": "facility_not_confirmed"}
                intent, response_basis = "venue_facility", "deterministic"
                context = self._clear_service_context(context)
            elif state["intent"] in {"venue_duration_timing", "venue_timing_confirmation"}:
                if state["intent"] == "venue_timing_confirmation":
                    draft = _venue_timing_confirmation_answer(language)
                    timing_topic = "operating_hours"
                else:
                    draft = _venue_duration_timing_answer(state.get("topic"), language)
                    timing_topic = state.get("topic")
                intent, response_basis = state["intent"], "deterministic"
                source = state["intent"]
                grounding.update({"structured_grounding": True, "answer_source": source, "response_mode": source})
                context = context.__class__(**{
                    **context.__dict__,
                    "last_service_name": None, "last_service_code": None,
                    "active_topic": timing_topic, "active_entity_type": "venue",
                    "active_entity_name": "Entartica Sea World Raipur",
                    "last_intent": state["intent"], "last_answer_source": source,
                    "service_selection_prompted": False, "service_details_requested": False,
                    "pending_service_code": None, "pending_clarification": False,
                })
            elif state["intent"] == "family_activity_discovery":
                draft = self._family_activity_discovery_answer(language, runtime["conversation"].get("location_id"), text)
                intent, response_basis = "family_activity_discovery", "deterministic"
                source = "family_activity_discovery"
                grounding.update({
                    "structured_grounding": True,
                    "answer_source": source,
                    "response_mode": source,
                    "catalogue_source": "active_raipur_services",
                    "catalogue_filter": "location=raipur;active=true;approved_manifest=true;category=water_ride|floating_celebration",
                })
                rides, celebrations = self._approved_family_catalogues(runtime["conversation"].get("location_id"))
                response_brief = SalesResponseBrief(
                    ResponseGoal.FAMILY_DISCOVERY, language, approved_options=tuple((*rides, *celebrations)),
                    approved_facts=(draft,),
                )
                combined_used = False
                if state.get("use_sales_agent"):
                    draft, context, combined_used = self._compose_sales_agent(response_brief, text, context, draft, grounding)
                if not combined_used:
                    draft = self._compose_sales(response_brief, draft, grounding)
                context = set_catalogue_context(context, "activity").updated_context or context
            elif state["intent"] == "celebration_occasion_clarification":
                draft = _celebration_occasion_question(language)
                intent, response_basis = "celebration_occasion_clarification", "deterministic"
                source = "celebration_occasion_clarification"
                grounding.update({"structured_grounding": True, "answer_source": source, "response_mode": source})
                context = set_celebration_occasion_pending(context).updated_context or context
                context = context.__class__(**{**context.__dict__, "last_intent": "celebration_occasion_clarification", "last_answer_source": source})
            elif state["intent"] == "celebration_cancel":
                draft = _celebration_cancel_answer(language)
                intent, response_basis = "celebration_cancel", "deterministic"
                source = "celebration_cancel"
                grounding.update({"structured_grounding": True, "answer_source": source, "response_mode": source})
                context = clear_pending_celebration(context, reason="celebration_cancel").updated_context or context
                context = context.__class__(**{**context.__dict__, "last_intent": "celebration_cancel", "last_answer_source": source})
            elif state["intent"] == "customer_understanding_update":
                recommendation = None
                pontoon_specific = context.last_service_code == "pontoon_celebration"
                if pontoon_specific:
                    pontoon_package = self._approved_pontoon_package()
                    context = _progress_celebration_sales_context(context)
                    if pontoon_past_date_rejected:
                        context = replace(
                            context, pending_field="preferred_date",
                            pending_question_type="sales_planned_date",
                            pending_action="celebration_sales", sales_stage=SalesStage.QUALIFYING,
                        )
                    draft = pontoon_post_qualification_response(
                        context, past_date_rejected=pontoon_past_date_rejected,
                    )
                    decision = evaluate_sales_next_action(context)
                    next_action = "reject_past_date" if pontoon_past_date_rejected else (
                        "show_pontoon_package" if context.details.preferred_date and context.details.total_guests
                        else decision.action.value
                    )
                elif context.pending_action == "celebration_sales" or context.active_entity_name == "celebration":
                    context = _progress_celebration_sales_context(context)
                    draft, recommendation = self._celebration_sales_response(context, language, runtime["conversation"].get("location_id"))
                    next_action = evaluate_sales_next_action(context).action.value
                else:
                    draft = (
                        "Thanks — I've noted that preference. Tell me what you would like to explore next."
                        if language == "en"
                        else "Thanks — maine aapki preference note kar li hai. Aap aage kya explore karna chahenge?"
                    )
                    next_action = "continue_discovery"
                intent, source = "customer_understanding_update", "customer_understanding_state_merge"
                grounding.update({"structured_grounding": True, "answer_source": source, "sales_next_action": next_action})
                if pontoon_specific:
                    source = "pontoon_post_qualification"
                    grounding.update({
                        "answer_source": source,
                        "pontoon_package_content_configured": pontoon_package_configured(pontoon_package),
                        "past_date_rejected": pontoon_past_date_rejected,
                    })
                if isinstance(recommendation, RecommendationDecision):
                    grounding.update({
                        "recommended_service_codes": list(recommendation.recommended_service_codes),
                        "recommendation_strength": recommendation.strength,
                        "recommendation_reason": recommendation.reason,
                        "recommendation_evidence": [
                            {"service_code": item.service_code, "section": item.section, "source_document_id": item.source_document_id}
                            for item in recommendation.evidence
                        ],
                        "recommendation_insufficient_evidence": recommendation.insufficient_evidence,
                        "recommendation_invoked": True,
                        "occasion_evidence_used": recommendation.occasion_evidence_used,
                        "preference_evidence_used": recommendation.preference_evidence_used,
                        "capacity_compatibility": [
                            {"service_code": item.service_code, "guest_count": item.guest_count, "compatible": item.compatible, "capacity_status": item.capacity_status.value if item.capacity_status else None}
                            for item in recommendation.capacity_compatibility
                        ],
                    })
                goal = None if pontoon_specific else ResponseGoal.SERVICE_RECOMMENDATION if recommendation and not recommendation.insufficient_evidence else {
                    "ask_guest_count": ResponseGoal.ASK_GUEST_COUNT,
                    "ask_date": ResponseGoal.ASK_DATE,
                    "ask_preference": ResponseGoal.ASK_PREFERENCE,
                }.get(next_action)
                if goal is not None:
                    slots = context.pending_slots or {}
                    draft = self._compose_sales(SalesResponseBrief(
                        goal, language, approved_facts=(draft,),
                        known_occasion=slots.get("occasion"), known_guest_count=context.details.total_guests,
                        known_date=context.details.preferred_date.isoformat() if context.details.preferred_date else None,
                        known_preference=slots.get("celebration_preference") or slots.get("preference"),
                        recommended_service_codes=tuple(recommendation.recommended_service_codes) if recommendation else (),
                        next_action=next_action, next_question=draft if goal is not ResponseGoal.SERVICE_RECOMMENDATION else None,
                    ), draft, grounding)
            elif state["intent"] == "celebration_guest_count":
                guests = _celebration_guest_count(text)
                if guests is None:
                    draft = _celebration_guest_question(language)
                else:
                    context = replace(
                        context,
                        details=replace(context.details, total_guests=guests),
                        pending_field="preferred_date",
                        pending_question_type="sales_planned_date",
                        pending_action="celebration_sales",
                        last_assistant_question="planned_date",
                        sales_stage=SalesStage.QUALIFYING,
                    )
                    draft = _celebration_date_question(language, guests)
                intent, source = "celebration_guest_count", "celebration_sales_state"
                grounding.update({"structured_grounding": True, "answer_source": source, "sales_next_action": "ask_date"})
                draft = self._compose_sales(SalesResponseBrief(ResponseGoal.ASK_DATE, language, approved_facts=(draft,), known_guest_count=guests, next_action="ask_date", next_question=draft), draft, grounding)
            elif state["intent"] == "celebration_planned_date":
                planned = _celebration_date(text)
                guests = context.details.total_guests
                if planned is None or guests is None:
                    draft = _celebration_date_question(language, guests or 0)
                else:
                    context = replace(
                        context,
                        details=replace(context.details, preferred_date=planned),
                        pending_field="celebration_preference",
                        pending_question_type="sales_preference",
                        pending_action="celebration_sales",
                        last_assistant_question="celebration_preference",
                        sales_stage=SalesStage.QUALIFYING,
                    )
                    draft = _celebration_preference_question(language, planned, guests)
                intent, source = "celebration_planned_date", "celebration_sales_state"
                grounding.update({"structured_grounding": True, "answer_source": source, "sales_next_action": "ask_preference"})
                draft = self._compose_sales(SalesResponseBrief(ResponseGoal.ASK_PREFERENCE, language, approved_facts=(draft,), known_guest_count=guests, known_date=planned.isoformat() if planned else None, next_action="ask_preference", next_question=draft), draft, grounding)
            elif state["intent"] == "celebration_preference":
                slots = dict(context.pending_slots or {})
                slots["celebration_preference"] = text.strip()
                context = replace(
                    context,
                    pending_slots=slots,
                    pending_field=None,
                    pending_question_type=None,
                    pending_action="celebration_sales",
                    sales_stage=SalesStage.QUALIFIED,
                )
                draft = "Thank you — I've noted your preference. Our team can help confirm the suitable approved option, availability, and pricing."
                intent, source = "celebration_preference", "celebration_sales_state"
                grounding.update({"structured_grounding": True, "answer_source": source, "sales_next_action": "handover_ready"})
            else:
                draft, grounding = self._venue_answer(text, language)
                intent, response_basis = "venue_overview", "active_rag"
                draft = self._compose_sales(SalesResponseBrief(
                    ResponseGoal.VENUE_OVERVIEW, language, approved_facts=(draft,),
                    customer_facts=CustomerFacts(experience_summary=draft),
                ), draft, grounding)
                context = self._clear_service_context(context)
        else:
            draft, intent, response_basis = self._general_or_unknown(state, text, language)
        grounding.setdefault("service_code", state.get("service_code"))
        grounding.setdefault("topic", state.get("topic"))
        grounding.update({"selected_route": route, "plan_consistency_repaired": bool(state.get("plan_consistency_repaired"))})
        result = self._result(draft, intent, language, handover, context, response_basis, source, grounding)
        self._log_node("answer_existing", state)
        return {"result": result, "draft_response": draft, "answer_source": source}

    def _active_service_rows(self, location_id: object) -> list[dict[str, Any]]:
        if self._services is None or not isinstance(location_id, str): return []
        try:
            return [row for row in self._services.list_active_for_location(location_id) if isinstance(row, dict)]
        except Exception:
            return []

    def _celebration_sales_response(
        self,
        context: ConversationContext,
        language: str,
        location_id: object,
    ) -> tuple[str, RecommendationDecision | None]:
        decision = evaluate_sales_next_action(context)
        if decision.action is not SalesNextAction.RECOMMEND_SERVICE:
            return _celebration_sales_followup(context, language), None
        slots = context.pending_slots or {}
        with latency_stage("celebration_recommendation"):
            recommendation = self._recommendation_policy.recommend(
                candidates=self._active_service_rows(location_id),
                occasion=slots.get("occasion"),
                preference=slots.get("celebration_preference") or slots.get("preference"),
                guest_count=context.details.total_guests,
            )
        if recommendation.insufficient_evidence:
            if language == "hinglish":
                return "Aapki details note hain. Approved evidence se ek option safely narrow nahi ho raha, isliye team suitable option confirm karne mein help karegi.", recommendation
            return "I've noted your details. The approved evidence does not safely narrow the options further, so our team can help confirm the most suitable option.", recommendation
        names = {}
        for row in self._active_service_rows(location_id):
            approved = approved_service_from_message(row.get("name") if isinstance(row, dict) else None)
            if approved is not None:
                names[knowledge_service_code(approved)] = approved.name
        bullets = []
        for code in recommendation.recommended_service_codes:
            evidence = next((item for item in recommendation.evidence if item.service_code == code), None)
            if evidence is None:
                continue
            snippet = re.sub(r"[*#]+", "", evidence.text).strip().split("\n", 1)[0]
            snippet = re.split(r"(?<=[.!?])\s+", snippet)[0][:240].strip()
            bullets.append(f"• {names.get(code, code)} — {snippet}")
        intro = (
            "Aapki shared details aur approved service information ke basis par ye options relevant lagte hain:"
            if language == "hinglish"
            else "Based on what you've shared and the approved service information, these options look most relevant:"
        )
        return intro + "\n\n" + "\n".join(bullets), recommendation

    def _approved_family_catalogues(self, location_id: object) -> tuple[list[str], list[str]]:
        """Approved water-ride and floating-celebration names from active rows.

        When the repository is unavailable the approved manifest is the source,
        mirroring the existing deterministic catalogue fallback.  No second
        hard-coded activity catalogue is introduced.
        """
        ride_names: list[str] = []
        celebration_names: list[str] = []
        for row in self._active_service_rows(location_id):
            name = row.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            service = approved_service_from_message(name)
            if service is None:
                continue
            if service.category == "water_ride":
                ride_names.append(name.strip())
            elif service.category == "floating_celebration":
                celebration_names.append(name.strip())
        if not ride_names:
            ride_names = [item.name for item in APPROVED_RAIPUR_SERVICES if item.category == "water_ride"]
        if not celebration_names:
            celebration_names = [item.name for item in APPROVED_RAIPUR_SERVICES if item.category == "floating_celebration"]
        return ride_names, celebration_names

    def _family_activity_discovery_answer(self, language: str, location_id: object, text: str) -> str:
        """Combined approved family discovery answer; never prices or availability."""
        ride_names, celebration_names = self._approved_family_catalogues(location_id)
        rides = "\n".join(f"\u2022 {name}" for name in ride_names)
        celebrations = "\n".join(f"\u2022 {name}" for name in celebration_names)
        children_mention = bool(re.search(r"\b(?:kids|children|bachch\w*|\u092c\u091a\u094d\u091a\u094b\u0902|\u092c\u091a\u094d\u091a\u0947|\u092c\u091a\u094d\u091a\u093e)\b", text, re.I))
        if language == "hi":
            followup = (
                "\u0938\u0939\u0940 \u0935\u093f\u0915\u0932\u094d\u092a \u0938\u0941\u091d\u093e\u0928\u0947 \u0915\u0947 \u0932\u093f\u090f \u0915\u0943\u092a\u092f\u093e \u092c\u0924\u093e\u0907\u090f: \u092c\u091a\u094d\u091a\u094b\u0902 \u0915\u0940 \u0906\u092f\u0941 \u0935\u0930\u094d\u0917, \u0915\u093f\u0924\u0928\u0947 \u092e\u0947\u0939\u092e\u093e\u0928 \u0906 \u0930\u0939\u0947 \u0939\u0948\u0902, \u0914\u0930 \u0906\u092a\u0915\u094b \u0915\u094d\u092f\u093e \u092a\u0938\u0902\u0926 \u0939\u0948 \u2014 adventure rides, kids activities \u092f\u093e celebration."
                if children_mention
                else "\u0938\u0939\u0940 \u0935\u093f\u0915\u0932\u094d\u092a \u0938\u0941\u091d\u093e\u0928\u0947 \u0915\u0947 \u0932\u093f\u090f \u0915\u0943\u092a\u092f\u093e \u092c\u0924\u093e\u0907\u090f: \u092a\u0930\u093f\u0935\u093e\u0930 \u0915\u0947 \u0938\u0926\u0938\u094d\u092f\u094b\u0902 \u0915\u0940 \u0906\u092f\u0941, \u0915\u093f\u0924\u0928\u0947 \u092e\u0947\u0939\u092e\u093e\u0928 \u0906 \u0930\u0939\u0947 \u0939\u0948\u0902, \u0914\u0930 \u0906\u092a\u0915\u094b \u0915\u094d\u092f\u093e \u092a\u0938\u0902\u0926 \u0939\u0948 \u2014 adventure rides, kids activities \u092f\u093e celebration."
            )
            return (
                "*Entartica Sea World, \u0930\u093e\u092f\u092a\u0941\u0930 \u2014 \u092a\u0930\u093f\u0935\u093e\u0930 \u0915\u0947 \u0932\u093f\u090f \u0917\u0924\u093f\u0935\u093f\u0927\u093f\u092f\u093e\u0901*\n\n"
                "Water rides \u0914\u0930 activities:\n" + rides + "\n\n"
                "Celebration experiences:\n" + celebrations + "\n\n" + followup
            )
        if language == "hinglish":
            followup = (
                "Best options suggest karne ke liye bataiye: bachchon ki age group, kitne guests aa rahe hain, aur aapko kya pasand hai \u2014 adventure rides, kids activities, ya celebration?"
                if children_mention
                else "Best options suggest karne ke liye bataiye: family members ki age, kitne guests aa rahe hain, aur aapko kya pasand hai \u2014 adventure rides, kids activities, ya celebration?"
            )
            return (
                "*Entartica Sea World, Raipur \u2014 Family Activities*\n\n"
                "Water rides aur activities:\n" + rides + "\n\n"
                "Celebration experiences:\n" + celebrations + "\n\n" + followup
            )
        followup = (
            "To help suggest the most suitable options, please share: the age group of the children in your family, how many guests are coming, and whether you prefer adventure rides, kids' activities, or a celebration."
            if children_mention
            else "To help suggest the most suitable options, please share: the age group of your family members, how many guests are coming, and whether you prefer adventure rides, kids' activities, or a celebration."
        )
        return (
            "*Fun Family Activities at Entartica Sea World Raipur*\n\n"
            "Water rides and activities:\n" + rides + "\n\n"
            "Celebration experiences:\n" + celebrations + "\n\n" + followup
        )

    def _result(self, draft: str, intent: str, language: str, handover: bool, context: ConversationContext, basis: str, source: str, grounding: dict[str, Any] | None = None) -> ConversationResult:
        modes={"answer_location":"deterministic_location","answer_catalogue":"deterministic_catalogue","handover_to_sales":"human_handover","answer_unknown_entartica_fact":"unknown_fact","answer_greeting":"conversational_acknowledgement"}
        mode=modes.get(source,"grounded_answer" if basis=="active_rag" else "clarification_question" if basis=="clarification" else "grounded_answer")
        metadata = {"response_basis": basis, "customer_response_sanitized": True, "response_mode": mode, "graph_answer_source": source, "answer_source": source, "automatic_reply_category": "information"}
        if isinstance(grounding, dict):
            metadata.update({key: value for key, value in grounding.items() if value is not None})
        return ConversationResult("general_human_handover" if handover else "answer_information", draft, "graph_route", intent, "raipur", language, handover, False, False, None, None, True, False, context, metadata, None, bool(draft.strip()), "safe" if draft.strip() else "empty")

    def _compose_sales(self, brief: SalesResponseBrief, fallback: str, grounding: dict[str, Any]) -> str:
        """One optional composition attempt; deterministic text always survives."""
        if self._sales_composer is None:
            grounding.update({"sales_composer_used": False, "sales_composer_fallback": True})
            return fallback
        with latency_stage("sales_response_composer"):
            result = self._sales_composer.compose(brief)
        grounding.update({
            "sales_composer_used": result.valid,
            "sales_composer_fallback": not result.valid,
            "sales_composer_reason": result.reason,
            "response_brief_goal": brief.response_goal.value,
        })
        return result.text if result.valid and result.text else fallback

    def _compose_sales_agent(
        self, brief: SalesResponseBrief, message: str, context: ConversationContext,
        fallback: str, grounding: dict[str, Any],
    ) -> tuple[str, ConversationContext, bool]:
        """Make one combined call; never cascade to another model on failure."""
        if self._sales_agent is None:
            return fallback, context, False
        with latency_stage("sales_agent"):
            result = self._sales_agent.respond(SalesAgentBrief(
                current_message=message,
                compact_context=compact_understanding_context(context),
                # The combined agent sees known and extracted facts together;
                # it may choose the useful allowed follow-up rather than being
                # constrained by a question computed before extraction.
                response_brief=replace(brief, next_question=None),
            ))
        grounding.update({
            "sales_agent_used": result.valid,
            "sales_agent_fallback": not result.valid,
            "sales_agent_reason": result.reason,
            "sales_composer_used": False,
            "sales_composer_fallback": False,
            "response_brief_goal": brief.response_goal.value,
        })
        if not result.valid or not result.reply or result.understanding is None:
            # The deterministic response is already approved. Do not make a
            # CustomerUnderstanding or composer retry after a failed agent call.
            return fallback, context, True
        updated = apply_customer_understanding(context, result.understanding)
        grounding["customer_understanding"] = result.understanding.model_dump(mode="json")
        if result.asked_for:
            grounding["sales_agent_asked_for"] = result.asked_for
        return result.reply, updated, True

    def _service_answer(self, state: RaipurGraphState, context: ConversationContext, text: str, language: str) -> tuple[str, ConversationContext, str, dict[str, Any]]:
        code = state.get("service_code"); service = next((item for item in APPROVED_RAIPUR_SERVICES if knowledge_service_code(item) == code), None)
        if service is None or self._knowledge is None: return self._safe_fallback(language), context, "clarification", {}
        if (
            code == "pontoon_celebration" and context.active_journey == "celebration"
            and state.get("use_previous_service") and state.get("topic")
        ):
            pontoon_package = self._approved_pontoon_package()
            updated = _progress_celebration_sales_context(replace(
                context, last_service_name=service.name, last_service_code=code,
                active_entity_type="service", active_entity_name=service.name,
                pending_action="celebration_sales", active_journey="celebration",
            ))
            return pontoon_package_question_response(updated, pontoon_package), updated, "deterministic", {
                "structured_grounding": True, "service_code": code, "topic": state.get("topic"),
                "answer_source": "pontoon_package_boundary",
                "pontoon_package_content_configured": pontoon_package_configured(pontoon_package),
            }
        if state.get("topic") == "highlights":
            category = "celebration" if service.category == "floating_celebration" else "activity" if service.category == "water_ride" else None
            media = self._knowledge.experience_media(scope="service", service_code=code, category=category) if hasattr(self._knowledge, "experience_media") else None
            urls = tuple(getattr(media, "urls", ()))
            draft = _media_response(service.name, urls)
            updated = replace(context, last_service_name=service.name, last_service_code=code, active_topic="highlights", active_entity_type="service", active_entity_name=service.name, last_intent=state["intent"], pending_clarification=False, pending_clarification_type=None, pending_clarification_options=(), sales_stage=SalesStage.SERVICE_SELECTED)
            return draft, updated, "active_rag", {"structured_grounding": True, "service_code": code, "topic": "highlights", "answer_source": "approved_experience_media", "media_scope": getattr(media, "scope", "none"), "media_source": getattr(media, "source_document", None), "media_url_count": len(urls)}
        if state.get("topic") == "duration" and is_h2o_service_code(code):
            individual = asks_individual_turn_duration(text)
            approved_text = h2o_service_duration_answer(service.name, individual_turn=individual)
            facts = ApprovedFacts("raipur", code, service.name, "duration", (approved_text,), ("Duration",))
            grounding = {
                "structured_grounding": True, "service_code": code, "topic": "duration",
                "answer_source": "h2o_access_semantics", "retrieved_section_headings": ["Duration"],
                "selected_section_heading": "Duration", "individual_turn_requested": individual,
            }
            draft = self._compose_sales(SalesResponseBrief(
                ResponseGoal.FACTUAL_ANSWER, language, service_code=code, service_name=service.name,
                approved_facts=facts.facts, customer_facts=customer_facts_from_approved(facts),
            ), approved_text, grounding)
            updated = replace(
                context, last_service_name=service.name, last_service_code=code, active_topic="duration",
                active_entity_type="service", active_entity_name=service.name, last_intent=state["intent"],
                last_answer_source="h2o_access_semantics", last_answer_sections=tuple(dict.fromkeys((*context.last_answer_sections, "Duration"))),
                pending_clarification=False, pending_clarification_type=None, pending_clarification_options=(), sales_stage=SalesStage.SERVICE_SELECTED,
            )
            return draft, updated, "active_rag", grounding
        try:
            # The provider performs an exact approved-section lookup before it
            # considers query embeddings or vector search for a known topic.
            answer = self._knowledge.answer_service_details(text, service.name, code, detail_mode=state.get("topic") or "overview")
        except Exception: answer = None
        if isinstance(answer, KnowledgeDraft) and not answer.low_confidence and isinstance(answer.text, str) and answer.text.strip():
            facts = approved_facts_from_draft(answer, service_code=code, service_name=service.name, topic=state.get("topic"))
            plan = MessagePlan(intent=state["intent"], entity_type="service", service_code=code, topic=state.get("topic"), use_previous_service=bool(state.get("use_previous_service")), confidence=1.0)
            errors = validate_response_against_facts(plan, answer.text, facts) + _topic_isolation_errors(state.get("topic"), answer.text)
            fallback_used = bool(errors)
            draft = deterministic_fact_fallback(facts, language) if fallback_used else _naturalize_topic_response(answer.text, service.name, state.get("topic"))
            grounding = _grounding_metadata(answer, code, state.get("topic"))
            if not fallback_used:
                goal = ResponseGoal.SERVICE_MORE_DETAILS if state.get("topic") == "more_details" else ResponseGoal.FACTUAL_ANSWER if state.get("topic") not in {None, "overview"} else ResponseGoal.SERVICE_OVERVIEW
                composed = self._compose_sales(SalesResponseBrief(
                    goal, language, service_code=code, service_name=service.name,
                    approved_facts=facts.facts, customer_facts=customer_facts_from_approved(facts),
                ), draft, grounding)
                composition_errors = validate_response_against_facts(plan, composed, facts) + _topic_isolation_errors(state.get("topic"), composed)
                if not composition_errors:
                    draft = composed
                elif composed != draft:
                    grounding.update({"sales_composer_used": False, "sales_composer_fallback": True, "sales_composer_reason": "fact_validation_failed"})
            grounding.update({
                "answer_source": "deterministic_fact_fallback" if fallback_used else "provider_composition",
                "validation_errors": list(errors),
                "deterministic_fallback_used": fallback_used,
            })
            if state.get("topic"):
                logger.info(
                    "raipur_topic_response service_code=%s topic=%s retrieved_section_headings=%s selected_section_heading=%s answer_source=%s validation_errors=%s deterministic_fallback_used=%s",
                    code, state.get("topic"), grounding["retrieved_section_headings"],
                    grounding["selected_section_heading"], grounding["answer_source"], grounding["validation_errors"], fallback_used,
                )
            sections = tuple(dict.fromkeys((*context.last_answer_sections, *facts.section_headings)))
            celebration = service.category == "floating_celebration"
            updated = context.__class__(**{**context.__dict__, "last_service_name": service.name, "last_service_code": code, "active_topic": state.get("topic"), "active_entity_type": "service", "active_entity_name": service.name, "last_intent": state["intent"], "last_answer_source": "provider_composition" if not errors else "deterministic_fact_fallback", "last_answer_sections": sections, "pending_clarification": False, "pending_clarification_type": None, "pending_clarification_options": (), "pending_action": "celebration_sales" if celebration else None, "pending_entity_type": None, "pending_entity_name": None, "active_journey": "celebration" if celebration else context.active_journey, "sales_stage": SalesStage.SERVICE_SELECTED})
            if celebration:
                updated = _progress_celebration_sales_context(updated)
            explicit_pontoon_selection = (
                code == "pontoon_celebration" and not state.get("use_previous_service")
                and state.get("topic") in {None, "overview"}
            )
            if explicit_pontoon_selection:
                pontoon_package = self._approved_pontoon_package()
                slots = dict(updated.pending_slots or {})
                media_already_sent = slots.get("pontoon_media_sent") == "true"
                if not media_already_sent and pontoon_package_configured(pontoon_package):
                    slots["pontoon_media_sent"] = "true"
                    updated = replace(updated, pending_slots=slots)
                    grounding["media_message"] = pontoon_media_message(pontoon_package)
                    grounding["pontoon_media_attached"] = True
                    draft = pontoon_missing_details_question(updated) or "What would you like to know about the Pontoon Boat Celebration Package?"
                else:
                    grounding["pontoon_media_attached"] = False
                    draft = pontoon_selection_response(updated, pontoon_package)
                grounding.update({
                    "answer_source": "pontoon_package_boundary",
                    "pontoon_package_content_configured": pontoon_package_configured(pontoon_package),
                    "approved_package": pontoon_package_configured(pontoon_package),
                    "package_source_file": getattr(pontoon_package, "source_file", None),
                })
            elif code == "pontoon_celebration":
                followup = pontoon_missing_details_question(updated)
                if followup:
                    draft = f"{draft}\n\n{followup}"
            return draft, updated, "active_rag", grounding
        return self._safe_fallback(language), context, "clarification", {}

    def _venue_answer(self, text: str, language: str) -> tuple[str, dict[str, Any]]:
        try:
            method = getattr(self._knowledge, "answer_venue_overview", None)
            answer = method(text) if callable(method) else self._knowledge.answer(text) if self._knowledge is not None else None
        except Exception: answer = None
        if isinstance(answer, KnowledgeDraft) and not answer.low_confidence and isinstance(answer.text, str) and _is_valid_venue_overview(answer.text):
            return answer.text.strip(), _grounding_metadata(answer, None, "overview")
        return self._deterministic_venue_fallback(language), {"structured_grounding": True, "answer_source": "venue_catalogue_fallback"}

    def _deterministic_venue_fallback(self, language: str) -> str:
        """Use structured location and the approved active catalogue; never sales handover."""
        names: list[str] = []
        if self._services is not None and isinstance(self._location, dict):
            location_id = self._location.get("id")
            if isinstance(location_id, str):
                try: names = [row["name"] for row in self._services.list_active_for_location(location_id) if isinstance(row,dict) and isinstance(row.get("name"),str)]
                except Exception: names = []
        if not names: names = [item.name for item in APPROVED_RAIPUR_SERVICES]
        location = self._location if isinstance(self._location, dict) else {}
        metadata = location.get("metadata") if isinstance(location.get("metadata"), dict) else {}
        name = metadata.get("location_name", location.get("name", "Entartica Sea World Raipur"))
        address = metadata.get("address_line", location.get("address"))
        location_text = f" located at {address}." if isinstance(address,str) and address.strip() else "."
        selection = ", ".join(names[:5])
        return f"{name} is a Raipur water-activity and celebration destination{location_text} Guests can explore approved experiences such as {selection}, along with other active Raipur offerings. You can ask about any particular activity for its approved details, duration, capacity, or safety information."

    def _catalogue(self, language: str, location_id: object) -> str:
        names: list[str] = []
        if self._services is not None and isinstance(location_id, str):
            try: names = [row["name"] for row in self._services.list_active_for_location(location_id) if isinstance(row, dict) and isinstance(row.get("name"), str)]
            except Exception: names = []
        if not names: names = [item.name for item in APPROVED_RAIPUR_SERVICES]
        return ("Raipur mein available experiences:\n• " + "\n• ".join(names[:16]))

    def _handover(self, state: RaipurGraphState, language: str) -> str:
        contact = self._sales_contact
        if contact is None: return "Please contact the Entartica sales team for assistance."
        return booking_sales_handover(contact, language) if state["intent"] == "booking" else direct_human_handover(contact, language) if state["intent"] == "human_support" else controlled_sales_handover(contact, language)

    def _general_or_unknown(self, state: RaipurGraphState, text: str, language: str) -> tuple[str, str, str]:
        if state["intent"] == "unknown_entartica_fact":
            service = next((item for item in APPROVED_RAIPUR_SERVICES if knowledge_service_code(item) == state.get("service_code")), None)
            if state.get("topic") == "technical_specification":
                contact = self._sales_contact.details() if self._sales_contact is not None else ""
                subject = service.name if service is not None else "the requested equipment"
                return f"The exact technical specification for {subject} is not confirmed in the approved information currently available to the chatbot. Please contact the Entartica team for verification.\n\n{contact}".strip(), "unknown_entartica_fact", "deterministic"
            return "The exact detail is not confirmed in the approved information currently available to the chatbot. Please contact the Entartica team for verification.", "unknown_entartica_fact", "deterministic"
        if self._fallback is not None:
            with latency_stage("conversational_fallback"):
                result = self._fallback.respond(question=text, language=language, selected_service=None)
            # The fallback has already passed the deterministic customer-output
            # validator.  Preserve that approved basis for the automatic-reply
            # gate; ``general_openai`` is not a trusted response basis.
            if getattr(result, "valid", False) and isinstance(getattr(result, "text", None), str): return result.text.strip(), "general_question", "conversational_fallback"
        return "Generally, I can help with information about water activities and venues. Please tell me what you would like to know.", "general_question", "deterministic"

    def _safe_fallback(self, language: str) -> str:
        return approved_safe_fallback(self._sales_contact, language) if self._sales_contact is not None else "The exact information is not confirmed. Please contact the Entartica team for verification."

    @staticmethod
    def _clear_service_context(context: ConversationContext) -> ConversationContext:
        return clear_for_non_service_turn(context, reason="graph_non_service").updated_context or context

    def validate_customer_response(self, state: RaipurGraphState) -> dict[str, Any]:
        result = state.get("result")
        valid = bool(result is not None and getattr(result, "response_valid", False) and isinstance(getattr(result, "draft_text", None), str) and result.draft_text.strip())
        errors = list(state.get("validation_errors", ()))
        if not valid: errors.append("response_validation_failed")
        update = {"validation_status": "valid" if valid else "invalid", "error": None if valid else "response_validation_failed", "validation_errors": errors}
        self._log_node("validate_customer_response", {**state, **update})
        return update

    def save_conversation_state(self, state: RaipurGraphState) -> dict[str, Any]:
        self._log_node("save_conversation_state", state)
        return {}
