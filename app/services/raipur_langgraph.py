"""Feature-flagged LangGraph routing adapter for Raipur conversations.

The graph deliberately delegates customer-facing policy and persistence to the
existing conversation service.  It adds an inspectable typed route decision,
without creating a second booking, retrieval, or outbound-send implementation.
"""
from __future__ import annotations

import logging
import re
from uuid import uuid4
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field
from langgraph.graph import END, START, StateGraph

from app.services.raipur_dialogue_planner import RaipurDialoguePlanner, _service_question_topic, is_service_catalogue_question
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, approved_service_from_message, knowledge_service_code
from app.services.raipur_conversation import ConversationContext, ConversationResult, KnowledgeDraft, _greeting, _is_location_question, _language, _structured_location_answer
from app.services.booking_enquiries import BookingDetails
from app.services.raipur_sales_contact import SalesContact, approved_safe_fallback, booking_sales_handover, controlled_sales_handover, direct_human_handover

logger = logging.getLogger("uvicorn.error")


GraphIntent = Literal[
    "greeting", "location", "venue_overview", "service_catalogue",
    "service_overview", "service_topic", "venue_facility", "general_question", "pricing",
    "booking", "availability", "payment", "cancellation_refund",
    "human_support", "unknown_entartica_fact", "contextual_service_followup",
]


class MessagePlan(BaseModel):
    """Validated, safe route fields; deterministic policy always wins."""

    model_config = ConfigDict(extra="forbid")
    intent: GraphIntent
    location_code: Literal["raipur"] = "raipur"
    entity_type: Literal["venue", "catalogue", "service", "general", "unknown"] = "unknown"
    service_code: str | None = None
    topic: Literal["overview", "capacity", "duration", "inclusions", "safety", "swimming", "operating_hours", "how_it_works", "eligibility", "location", "more_details", "technical_specification"] | None = None
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
    _runtime: NotRequired[dict[str, Any]]


_RESTRICTED = {"pricing", "booking", "availability", "payment", "cancellation_refund", "human_support"}
_TOPIC_WORDS = {
    "capacity": ("capacity", "seater", "kitne log", "how many people"),
    "duration": ("duration", "how long", "how long does it last", "kitni der", "kitne time", "kitna time", "kitne minute", "kab tak"),
    "inclusions": ("included", "inclusion", "isme kya", "what is included"),
    "safety": ("safety", "life jacket"),
    "swimming": ("swimming", "swim"),
    "operating_hours": ("operating hours", "opening", "closing", "hours"),
    "eligibility": ("pregnant", "pregnancy", "child", "children", "eligible"),
    "how_it_works": ("how does it work", "how it works", "what happens", "kaise hota", "kaise chalta"),
}

_FACILITY_WORDS = ("parking", "washroom", "toilet", "locker", "changing room", "food", "restaurant", "wheelchair", "entry gate", "seating", "wi-fi", "wifi", "first aid")


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
    r"manufacturer|make|model\s+number|serial\s+number|technical\s+specification|"
    r"propeller|battery\s+model|equipment\s+model|current\s+operator|who\s+is\s+operating|registration\s+number)\b",
    re.I,
)


def _is_greeting_or_closing(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(?:hi+|hello|hey|namaste|thank\s+you|thanks|okay\s+thanks|great|got\s+it|bye|goodbye)\s*[.!]?\s*", text, re.I))


def _is_gratitude(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(?:thank\s+you|thanks|okay\s+thanks|great\s*,?\s*thanks|that\s+helped|got\s+it)\s*[.!]?\s*", text, re.I))


def _is_generic_service_concept_question(text: str, topic: str | None) -> bool:
    value=text.casefold()
    if topic is not None or any(term in value for term in ("entartica","raipur","offered","offer","available","price","booking","book","location")):
        return False
    return bool(re.search(r"\b(?:what\s+is|how\s+does)\b", value))


def _acknowledgement(language: str) -> str:
    if language == "hinglish": return "Aapka swagat hai. Agar aapko kisi Raipur activity ya service ke baare mein aur help chahiye, bataiye."
    if language == "hi": return "आपका स्वागत है। अगर आपको किसी रायपुर गतिविधि या सेवा के बारे में और सहायता चाहिए, तो बताइए।"
    return "You’re welcome. Let me know if you would like help with any Raipur activity or service."


def _greeting_reply(language: str) -> str:
    if language == "hinglish":
        return "Hello! Entartica Sea World, Raipur ke baare mein main aapki kaise help kar sakta hoon?"
    return "Hello! How may I help you with Entartica Sea World, Raipur?"


def approved_facts_from_draft(draft: KnowledgeDraft, *, service_code: str | None, service_name: str | None, topic: str | None) -> ApprovedFacts:
    """Normalize provider output for narrow consistency checks only.

    The facts are derived from composed answer text, not raw retrieved chunks;
    this is deliberately not an independent evidence-validation boundary.
    """
    text = draft.text.strip() if isinstance(draft.text, str) else ""
    facts = tuple(dict.fromkeys(item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", text) if item.strip()))
    heading = draft.section_heading.strip().casefold() if isinstance(draft.section_heading, str) and draft.section_heading.strip() else ""
    return ApprovedFacts("raipur", service_code, service_name, topic, facts, (heading,) if heading else ())


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
        if not re.search(r"\b(?:\d+\s*(?:to|-)?\s*\d*\s*(?:minutes?|hours?)|duration|session)\b", first):
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
    elif intent == "service_list": mapped = "service_catalogue"
    elif intent in {"service_overview", "service_full_overview", "service_definition"}: mapped = "service_overview"
    elif intent in {"service_detail", "service_more_details", "participation_eligibility", "service_operation_question"}: mapped = "service_topic"
    elif intent == "live_availability": mapped = "availability"
    elif intent == "restricted": mapped = "human_support"
    else: mapped = "general_question"
    topic = getattr(plan, "question_topic", None)
    allowed_topics = {"overview", "capacity", "duration", "inclusions", "safety", "swimming", "operating_hours", "how_it_works", "eligibility", "location"}
    return MessagePlan(
        intent=mapped, entity_type="service" if getattr(plan, "service_code", None) else "general",
        service_code=getattr(plan, "service_code", None), topic=topic if topic in allowed_topics else None,
        use_previous_service=getattr(plan, "reference_resolution", "current_message") == "previous_service",
        requires_sales_handover=mapped in _RESTRICTED, confidence=0.7,
        handover_reason=mapped if mapped in _RESTRICTED else None,
    )


class RaipurLangGraphWorkflow:
    """Run one existing conversation pass through an explicit LangGraph route."""

    def __init__(self, conversation_service: Any = None, *, planner: RaipurDialoguePlanner | None = None, knowledge: Any = None, services: Any = None, location: dict[str, Any] | None = None, sales_contact: SalesContact | None = None, conversational_fallback: Any = None) -> None:
        self._conversation_service = conversation_service
        self._planner = planner or RaipurDialoguePlanner()
        self._knowledge = knowledge if knowledge is not None else getattr(conversation_service, "_knowledge", None)
        self._services = services if services is not None else getattr(conversation_service, "_services", None)
        self._location = location if location is not None else getattr(conversation_service, "_location", None)
        self._sales_contact = sales_contact if sales_contact is not None else getattr(conversation_service, "_sales_contact", None)
        self._fallback = conversational_fallback if conversational_fallback is not None else getattr(conversation_service, "_conversational_fallback", None)
        graph = StateGraph(RaipurGraphState)
        graph.add_node("load_conversation_state", self.load_conversation_state)
        graph.add_node("plan_message", self.plan_message)
        graph.add_node("answer_greeting", self.answer_existing)
        graph.add_node("answer_location", self.answer_existing)
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
            "answer_catalogue": "answer_catalogue", "answer_service_knowledge": "answer_service_knowledge",
            "answer_venue_knowledge": "answer_venue_knowledge", "answer_general_openai": "answer_general_openai",
            "answer_unknown_entartica_fact": "answer_unknown_entartica_fact",
            "handover_to_sales": "handover_to_sales",
        })
        for node in ("answer_greeting", "answer_location", "answer_catalogue", "answer_service_knowledge", "answer_venue_knowledge", "answer_general_openai", "answer_unknown_entartica_fact", "handover_to_sales"):
            graph.add_edge(node, "validate_customer_response")
        graph.add_edge("validate_customer_response", "save_conversation_state")
        graph.add_edge("save_conversation_state", END)
        self._graph = graph.compile()

    def invoke(self, state: RaipurGraphState, *, message: Any, customer: dict[str, Any], conversation: dict[str, Any], source_message_id: str, current_state: Any = None) -> Any:
        runtime = {"message": message, "customer": customer, "conversation": conversation, "source_message_id": source_message_id, "current_state": current_state}
        # LangGraph state stays safe/serializable; runtime-only objects never persist in it.
        final = self._graph.invoke(self._fresh_turn_state(state, runtime))  # type: ignore[arg-type]
        return final.get("result")

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
        mapped = self._deterministic_plan(text, state.get("previous_service_code"))
        if mapped is None:
            plan = self._planner.plan(text, state.get("_runtime", {}).get("current_state"), language=state["language"])
            mapped = _plan_to_message_plan(plan)
        mapped, repaired = self._repair_plan_consistency(text, mapped, state.get("previous_service_code"))
        selected_route = self._route_for(mapped.intent, mapped.requires_sales_handover)
        update = {
            "intent": mapped.intent, "entity_type": mapped.entity_type,
            "service_code": mapped.service_code, "topic": mapped.topic,
            "selected_route": selected_route, "route": selected_route,
            "use_previous_service": mapped.use_previous_service,
            "requires_handover": mapped.requires_sales_handover,
            "handover_reason": mapped.handover_reason,
            "answer_source": None, "source_filename": None,
            "validation_errors": [], "plan_consistency_repaired": repaired,
        }
        self._log_node("plan_message", {**state, **update})
        return update

    def _deterministic_plan(self, text: str, previous_service_code: str | None) -> MessagePlan | None:
        """High-confidence policy ordering; never allow stale context to win."""
        if _is_location_question(text) or bool(re.search(r"\b(?:address|location|google\s+maps|map\s+link)\b", text, re.I)):
            return MessagePlan(intent="location", entity_type="venue", topic=None, confidence=1.0)
        if is_service_catalogue_question(text):
            return MessagePlan(intent="service_catalogue", entity_type="catalogue", confidence=1.0)
        if _is_greeting_or_closing(text):
            return MessagePlan(intent="greeting", entity_type="general", use_previous_service=False, confidence=1.0)
        service = approved_service_from_message(text)
        if _is_technical_specification_question(text):
            return MessagePlan(
                intent="unknown_entartica_fact", entity_type="service" if service is not None else "general",
                service_code=knowledge_service_code(service) if service is not None else None, topic="technical_specification",
                use_previous_service=False, confidence=1.0,
            )
        if any(term in text for term in _FACILITY_WORDS):
            return MessagePlan(intent="venue_facility", entity_type="venue", use_previous_service=False, confidence=1.0)
        restricted = (("pricing", ("price", "pricing", "quote", "quotation")), ("booking", ("book", "booking", "reserve")), ("availability", ("available", "availability", "slot", "tomorrow")), ("payment", ("payment", "pay")), ("cancellation_refund", ("cancel", "refund")), ("human_support", ("human", "agent", "sales", "contact")))
        for intent, terms in restricted:
            if any(term in text for term in terms):
                return MessagePlan(intent=intent, entity_type="service", requires_sales_handover=True, handover_reason=intent, confidence=1.0)
        topic = next((name for name, terms in _TOPIC_WORDS.items() if any(term in text for term in terms)), None)
        if service is not None and _is_generic_service_concept_question(text, topic):
            return MessagePlan(intent="general_question", entity_type="general", use_previous_service=False, confidence=1.0)
        if service is not None:
            return MessagePlan(intent="service_topic" if topic else "service_overview", entity_type="service", service_code=knowledge_service_code(service), topic=topic or "overview", confidence=0.98)
        followup = any(term in text for term in ("tell me more", "more details", "how long is it", "isme", "usme", "it?"))
        if previous_service_code and (followup or topic is not None):
            return MessagePlan(intent="contextual_service_followup", entity_type="service", service_code=previous_service_code, topic=topic or "more_details", use_previous_service=True, confidence=0.9)
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
        if intent == "service_catalogue": return "answer_catalogue"
        if intent in {"service_overview", "service_topic", "contextual_service_followup"}: return "answer_service_knowledge"
        if intent in {"venue_overview", "venue_facility"}: return "answer_venue_knowledge"
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
        if mapped.intent in _RESTRICTED or mapped.intent in {"unknown_entartica_fact", "general_question", "greeting"}:
            return mapped, False
        service = approved_service_from_message(text)
        explicit_topic = next((name for name, terms in _TOPIC_WORDS.items() if any(term in text for term in terms)), None)
        if service is not None:
            code = knowledge_service_code(service)
            expected_intent = "service_topic" if explicit_topic else "service_overview"
            expected_topic = explicit_topic or "overview"
            if (mapped.service_code, mapped.topic, mapped.intent, mapped.use_previous_service) != (code, expected_topic, expected_intent, False):
                return MessagePlan(intent=expected_intent, entity_type="service", service_code=code, topic=expected_topic, use_previous_service=False, confidence=1.0), True
        if explicit_topic and mapped.topic != explicit_topic and mapped.service_code == previous_service_code:
            return MessagePlan(intent="contextual_service_followup", entity_type="service", service_code=previous_service_code, topic=explicit_topic, use_previous_service=True, confidence=1.0), True
        return mapped, False

    @staticmethod
    def _log_node(node_name: str, state: dict[str, Any]) -> None:
        logger.info(
            "raipur_graph_node message_id=%s node_name=%s normalized_message=%s current_intent=%s current_service_code=%s current_topic=%s previous_service_code=%s previous_topic=%s use_previous_service=%s selected_route=%s plan_consistency_repaired=%s invocation_id=%s",
            state.get("message_id", ""), node_name, state.get("normalized_message", ""),
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
        route = self.route(state)
        response_basis, handover, source = "deterministic", False, route
        grounding: dict[str, Any] = {
            "service_code": state.get("service_code"),
            "topic": state.get("topic"),
        }
        if route == "answer_greeting":
            draft, intent = (_acknowledgement(language) if _is_gratitude(state["normalized_message"]) else _greeting_reply(language)), "greeting"
            context = self._clear_service_context(context)
        elif route == "answer_location":
            draft, intent = _structured_location_answer(self._location, language) or self._safe_fallback(language), "location"
            context = self._clear_service_context(context)
        elif route == "answer_catalogue":
            draft, intent = self._catalogue(language, runtime["conversation"].get("location_id")), "service_catalogue"
            context = self._clear_service_context(context)
        elif route == "handover_to_sales":
            draft, intent, handover = self._handover(state, language), state["intent"], True
            context = self._clear_service_context(context)
        elif route == "answer_service_knowledge":
            draft, context, response_basis, grounding = self._service_answer(state, context, text, language)
            intent = state["intent"]
        elif route == "answer_venue_knowledge":
            if state["intent"] == "venue_facility":
                draft, grounding = "This facility information is not confirmed in the approved knowledge currently available.", {"answer_source": "facility_not_confirmed"}
                intent, response_basis = "venue_facility", "deterministic"
            else:
                draft, grounding = self._venue_answer(text, language)
                intent, response_basis = "venue_overview", "active_rag"
            context = self._clear_service_context(context)
        else:
            draft, intent, response_basis = self._general_or_unknown(state, text, language)
        grounding.setdefault("service_code", state.get("service_code"))
        grounding.setdefault("topic", state.get("topic"))
        grounding.update({"selected_route": route, "plan_consistency_repaired": bool(state.get("plan_consistency_repaired"))})
        result = self._result(draft, intent, language, handover, context, response_basis, source, grounding)
        self._log_node("answer_existing", state)
        return {"result": result, "draft_response": draft, "answer_source": source}

    def _result(self, draft: str, intent: str, language: str, handover: bool, context: ConversationContext, basis: str, source: str, grounding: dict[str, Any] | None = None) -> ConversationResult:
        modes={"answer_location":"deterministic_location","answer_catalogue":"deterministic_catalogue","handover_to_sales":"human_handover","answer_unknown_entartica_fact":"unknown_fact","answer_greeting":"conversational_acknowledgement"}
        mode=modes.get(source,"grounded_answer" if basis=="active_rag" else "clarification_question" if basis=="clarification" else "grounded_answer")
        metadata = {"response_basis": basis, "customer_response_sanitized": True, "response_mode": mode, "graph_answer_source": source, "answer_source": source, "automatic_reply_category": "information"}
        if isinstance(grounding, dict):
            metadata.update({key: value for key, value in grounding.items() if value is not None})
        return ConversationResult("general_human_handover" if handover else "answer_information", draft, "graph_route", intent, "raipur", language, handover, False, False, None, None, True, False, context, metadata, None, bool(draft.strip()), "safe" if draft.strip() else "empty")

    def _service_answer(self, state: RaipurGraphState, context: ConversationContext, text: str, language: str) -> tuple[str, ConversationContext, str, dict[str, Any]]:
        code = state.get("service_code"); service = next((item for item in APPROVED_RAIPUR_SERVICES if knowledge_service_code(item) == code), None)
        if service is None or self._knowledge is None: return self._safe_fallback(language), context, "clarification", {}
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
            updated = context.__class__(**{**context.__dict__, "last_service_name": service.name, "last_service_code": code, "active_topic": state.get("topic"), "active_entity_type": "service", "active_entity_name": service.name, "last_intent": state["intent"], "last_answer_source": "provider_composition" if not errors else "deterministic_fact_fallback", "last_answer_sections": sections})
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
        return context.__class__(**{**context.__dict__, "last_service_name": None, "last_service_code": None, "active_topic": None, "active_entity_type": None, "active_entity_name": None})

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
