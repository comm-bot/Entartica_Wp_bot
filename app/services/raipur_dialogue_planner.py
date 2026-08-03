"""Validated dialogue planning for Raipur; business workflows remain in the router."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Literal

from app.services.raipur_services import approved_primary_service_from_question, approved_service_from_message


Intent = Literal["greeting", "service_list", "service_overview", "service_more_details", "service_full_overview", "service_definition", "service_detail", "service_confirmation", "service_correction", "service_operation_question", "participation_eligibility", "live_availability", "restricted", "general"]
AnswerMode = Literal["service_list", "general_definition", "active_rag", "clarification", "live_availability", "restricted_handover", "general"]


@dataclass(frozen=True)
class DialoguePlan:
    domain: Literal["entartica", "raipur_city", "general"] = "entartica"
    intent: Intent = "general"
    service_code: str | None = None
    service_name: str | None = None
    reference_resolution: Literal["current_message", "previous_service", "pending_question"] = "current_message"
    language: Literal["en", "hi", "hinglish"] = "en"
    answer_mode: AnswerMode = "general"
    pending_action: str | None = None
    slots: dict[str, str | None] | None = None
    needs_clarification: bool = False
    question_topic: str | None = None
    requires_rag: bool = False


_ALLOWED_INTENTS = set(Intent.__args__)
_ALLOWED_MODES = set(AnswerMode.__args__)
_PARTICIPATION_ELIGIBILITY = re.compile(
    r"\b(?:pregnant|pregnancy|pregnent|pregnency|pragnant|expecting\s+mother|health\s+condition|health\s+problem|heart\s+(?:condition|patients?)|back\s+(?:problem|pain)|neck\s+(?:problem|pain)|(?:recent\s+)?surgery|medical(?:ly)?\s+(?:fit|condition)|safe\s+for\s+children|can\s+(?:a\s+)?child(?:ren)?\s+(?:ride|participate)|eligible|allowed\s+(?:to\s+ride|hai\s+kya)|can\s+i\s+participate|swimming\s+required|(?:need\s+to|know\s+how\s+to)\s+swim|swim\s+for|age\s+allowed|weight\s+allowed|pregnant\s+lady\s+kar\s+sakti\s+hai|pregnancy\s+mein\s+kar\s+sakte\s+hain|baccha\s+kar\s+sakta\s+hai|health\s+problem\s+hai|back\s+pain|eligible\s+hai\s+kya)\b",
    re.IGNORECASE,
)

# A catalogue request is intentionally stricter than merely mentioning a ride
# or activity.  A named approved service must remain an exact-service request.
_SERVICE_CATALOGUE_QUESTION = re.compile(
    r"\b(?:various|different|all|available|list|options?|show|tell\s+me)\b[^.?!]{0,40}\b(?:rides?|activities|services?)\b"
    r"|\b(?:rides?|activities|services?)\b[^.?!]{0,30}\b(?:available|list|options?|hain|hai|batao)\b"
    r"|\bwhat\s+(?:are\s+the\s+)?rides\b"
    r"|\bhow\s+many\s+(?:rides|activities|services)\b"
    r"|\b(?:can\s+you\s+provide|show\s+me|any)\s+(?:other\s+)?(?:rides?|activities|services?)\b"
    r"|\bwhat\s+else\s+do\s+you\s+have\b"
    r"|\b(?:aur\s+(?:kaun\s+si|kaun\s+kaun)\s+)?(?:rides?|activities)\s+(?:hain|hai|batao)\b"
    r"|\b(?:konsi|kaunsi)\s+service\b"
    r"|\b(?:services?\s+available|rides?\s+hain|activities\s+milti|rides?\s+ki\s+list|what\s+services\s+do\s+you\s+offer)\b",
    re.I,
)


def is_participation_eligibility_question(text: str) -> bool:
    """Recognize safety and participation questions before catalogue routing."""

    return isinstance(text, str) and bool(_PARTICIPATION_ELIGIBILITY.search(text))


def is_service_catalogue_question(text: str) -> bool:
    """Return true only for an unqualified request for multiple services."""

    return (
        isinstance(text, str)
        and approved_primary_service_from_question(text) is None
        # "How many rides are included?" is a package-inclusions follow-up,
        # not a request for the catalogue, even without a new service name.
        and not bool(re.search(r"\b(?:included|include|inclusion|comes\s+with|isme)\b", text, re.I))
        and bool(_SERVICE_CATALOGUE_QUESTION.search(text))
    )


class RaipurDialoguePlanner:
    def __init__(self, planner_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None) -> None:
        self._planner_fn = planner_fn

    def plan(self, message: str, context: Any, *, language: str) -> DialoguePlan:
        request = {"message": message, "selected_service_code": getattr(context, "last_service_code", None), "pending_action": getattr(context, "pending_action", None), "language": language}
        if self._planner_fn is not None:
            try:
                candidate = self._planner_fn(request)
                parsed = _validated(candidate)
                if parsed is not None:
                    return parsed
            except Exception:
                pass
        return _deterministic(request, context)


def _validated(value: object) -> DialoguePlan | None:
    if not isinstance(value, dict) or value.get("intent") not in _ALLOWED_INTENTS or value.get("answer_mode") not in _ALLOWED_MODES:
        return None
    if value.get("language") not in {"en", "hi", "hinglish"}:
        return None
    service = approved_service_from_message(value.get("service_name") or "")
    if value.get("service_code") and (service is None or service.slug.replace("-", "_") != value["service_code"]):
        return None
    return DialoguePlan(intent=value["intent"], answer_mode=value["answer_mode"], language=value["language"], service_code=value.get("service_code"), service_name=service.name if service else None, reference_resolution=value.get("reference_resolution") if value.get("reference_resolution") in {"current_message", "previous_service", "pending_question"} else "current_message", pending_action=value.get("pending_action") if isinstance(value.get("pending_action"), str) else None, slots=value.get("slots") if isinstance(value.get("slots"), dict) else None, needs_clarification=bool(value.get("needs_clarification")), question_topic=value.get("question_topic") if isinstance(value.get("question_topic"), str) else None, requires_rag=bool(value.get("requires_rag")))


def _deterministic(request: dict[str, Any], context: Any) -> DialoguePlan:
    text = request["message"].casefold(); service = approved_primary_service_from_question(text)
    lang = request["language"]
    if text.strip() in {"hi", "hii", "hello", "hey", "namaste"}:
        return DialoguePlan(intent="greeting", answer_mode="general", language=lang)
    if is_service_catalogue_question(text):
        return DialoguePlan(intent="service_list", answer_mode="service_list", language=lang)
    if service and is_participation_eligibility_question(text):
        return DialoguePlan(intent="participation_eligibility", answer_mode="active_rag", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name, question_topic=_service_question_topic(text), requires_rag=True)
    if service and _is_service_full_overview_question(text):
        return DialoguePlan(intent="service_full_overview", answer_mode="active_rag", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name, requires_rag=True)
    if service and _is_more_details_question(text):
        return DialoguePlan(intent="service_more_details", answer_mode="active_rag", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name, question_topic="more_details", requires_rag=True)
    if service and _is_service_overview_question(text):
        return DialoguePlan(intent="service_overview", answer_mode="active_rag", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name, question_topic=_service_question_topic(text), requires_rag=True)
    correction = any(value in text for value in ("actually", " nahi", "mera matlab", "po toon", "pontoon bahot"))
    definition = any(value in text for value in ("what is", "kya hai", "kya hota", "kya cheez", "kya chiz", "iska matlab", "ye ride kaise"))
    if service and correction:
        return DialoguePlan(intent="service_correction", answer_mode="general_definition", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name)
    if service and definition:
        if "how does it work" in text or _service_question_topic(text) is not None:
            return DialoguePlan(intent="service_detail", answer_mode="active_rag", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name, question_topic=_service_question_topic(text), requires_rag=True)
        return DialoguePlan(intent="service_definition", answer_mode="general_definition", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name)
    if service and any(value in text for value in ("available today", "available tomorrow", "slot", " at ")):
        return DialoguePlan(intent="live_availability", answer_mode="live_availability", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name)
    if service and _is_service_existence_question(text):
        # Presence is useful for internal routing, but it is never enough for
        # a customer-facing answer.  Route it through exact-service overview.
        return DialoguePlan(intent="service_overview", answer_mode="active_rag", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name, question_topic="service_overview", requires_rag=True)
    if service and _is_specific_service_question(text):
        return DialoguePlan(intent="service_operation_question" if _service_question_topic(text) == "self_driving" else "service_detail", answer_mode="active_rag", language=lang, service_code=service.slug.replace("-", "_"), service_name=service.name, question_topic=_service_question_topic(text), requires_rag=True)
    return DialoguePlan(language=lang, service_code=service.slug.replace("-", "_") if service else None, service_name=service.name if service else None, reference_resolution="previous_service" if service is None and getattr(context, "last_service_code", None) else "current_message")


def _service_question_topic(text: str) -> str | None:
    topics = (
        ("self_driving", ("drive", "myself", "self driven", "self-driven", "operate", "control")),
        ("swimming_requirement", ("swim", "swimming", "swimming aana", "non-swimmer", "swimming nahi aati", "swimming zaruri", "tairna", "tair sakte", "swim karna")),
        ("pregnancy", ("pregnant", "pregnancy", "pregnent", "pregnency", "pragnant")),
        ("fall_safety", ("fall", "falls", "fell")),
        ("capacity", ("how many", "capacity", "people can ride", "persons", "kitne log", "kitne aadmi", "kitne guest", "kitne person", "ek baar mein kitne", "ek ride mein kitne", "beth sakte", "baith sakte", "single or double", "solo or tandem")),
        ("duration", ("how long", "duration", "minutes", "time does", "kitni der", "kitne minute", "kitna time", "kitne time", "ride time", "session time")),
        ("inclusions", ("included", "include", "inclusion", "breakfast", "what comes with", "kya included", "isme kya milega", "isme kya milta", "kya kya milta", "package mein kya", "activities included", "rides included")),
        ("eligibility", ("who can participate", "age limit", "child allowed", "bacche kar", "kaun kar sakta", "allowed hai", "height", "weight", "suitable for")),
        ("operating_hours", ("timing", "opening time", "operating hours", "kab open", "kitne baje", "kab tak", "khulta", "band hota", "ride kab chalti")),
        ("safety", ("safe", "safety", "life jacket", "helmet", "safety equipment", "instructor available", "safe hai", "suraksha")),
        ("how_it_works", ("how does it work", "kaise hota", "kaise chalta", "ride ka process", "how do we ride", "khud chalana", "captain hoga")),
        ("service_comparison", ("difference", "compare", "versus", " vs ")),
    )
    return next((topic for topic, terms in topics if any(term in text for term in terms)), None)


def _is_service_existence_question(text: str) -> bool:
    return bool(re.search(r"\bdo\s+you\s+(?:offer|have)\b|\bis\s+.+\s+(?:offered|available\s+as\s+a\s+service)\b|\b(?:jet\s+ski|ride)\s+hai\s+kya\b|\baapke\s+yahan\s+.+\s+hoti\s+hai\b", text, re.I))


def _is_service_overview_question(text: str) -> bool:
    """Recognize broad service requests before existence/definition fallbacks."""

    if _service_question_topic(text) == "service_comparison":
        return False
    return bool(re.search(
        r"\b(?:tell\s+me\s+about|what\s+is|information\s+about|details?\s+(?:about|of)|"
        r"explain|i\s+want\s+to\s+(?:know|learn)\s+about|want\s+to\s+(?:know|learn)\s+about|"
        r"can\s+(?:you\s+)?(?:give|provide)\s+(?:me\s+)?(?:information|details)|"
        r"(?:ke|ki)\s+bare\s+mein\s+batao|(?:ke|ki)\s+baare\s+mein\s+batao|"
        r"kya\s+(?:hai|hota\s+hai|chiz\s+hai|cheez\s+hoti\s+hai)|matlab\s+kya\s+hai|mera\s+matlab)\b",
        text,
        re.I,
    )) or any(term in text for term in ("info of", "info on", "information", "details"))


def _is_service_full_overview_question(text: str) -> bool:
    return bool(re.search(
        r"\b(?:everything(?:\s+about(?:\s+it)?)?|tell\s+me\s+everything|full\s+information|"
        r"complete\s+(?:details|information)|all\s+details|full\s+details(?:\s+about\s+this)?|"
        r"sab\s+batao|puri\s+details\s+do|iske\s+bare\s+mein\s+sab\s+batao)\b",
        text,
        re.I,
    ))


def _is_more_details_question(text: str) -> bool:
    return bool(re.search(
        r"\b(?:tell\s+me\s+more|more\s+(?:information|details|info)(?:\s+(?:about|on))?\s*(?:it|this)?|"
        r"can\s+i\s+know\s+more(?:\s+about\s+it)?|explain\s+further|"
        r"give\s+(?:me\s+)?more\s+(?:details|information|info)|aur\s+batao|"
        r"thodi\s+aur\s+information|iske\s+bare\s+mein\s+aur\s+batao)\b",
        text,
        re.I,
    ))


def _is_specific_service_question(text: str) -> bool:
    return bool(
        _service_question_topic(text)
        or re.search(r"\b(?:how|what|why|can|is|are|does|do)\b.*\?|\b(?:how\s+does|what\s+should|is\s+it\s+safe)\b", text, re.I)
    )
