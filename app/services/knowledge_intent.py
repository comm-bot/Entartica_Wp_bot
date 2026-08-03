"""Deterministic, local routing for approved knowledge categories."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


KnowledgeIntent = Literal[
    "location", "services", "booking", "safety", "general_faq", "unsupported_location", "unknown"
]
Confidence = Literal["high", "medium", "low"]
ALL_RAIPUR_CATEGORIES = (
    "location_information", "services", "booking_policy", "safety_guidelines", "faq"
)


@dataclass(frozen=True)
class KnowledgeIntentResult:
    intent: KnowledgeIntent
    preferred_categories: tuple[str, ...]
    fallback_categories: tuple[str, ...]
    confidence: Confidence
    human_handover_required: bool = False


_PHRASE_RULES: tuple[tuple[KnowledgeIntent, tuple[str, ...]], ...] = (
    ("unsupported_location", ("in delhi", "at delhi", "in indore", "at indore", "delhi location", "indore location")),
    ("location", ("opening time", "closing time", "operating timing", "operating timings", "operating hours", "where is", "how to reach")),
    ("services", ("water sports", "family activities", "what can families do")),
    ("booking", ("how can i book", "advance booking", "booking confirmation", "final confirmation", "booking enquiry", "booking inquiry")),
    ("safety", ("life jacket", "life jackets", "bad weather", "medical condition", "age restriction")),
    ("general_faq", ("frequently asked", "common question")),
)
_WORD_RULES: tuple[tuple[KnowledgeIntent, tuple[str, ...]], ...] = (
    ("location", ("where", "address", "located", "location", "map", "opening", "closing", "timing", "hours")),
    ("services", ("activity", "activities", "service", "services", "ride", "boating", "water", "sports", "family", "families", "staycation", "daycation", "celebration")),
    ("booking", ("book", "booking", "enquiry", "inquiry", "confirmed", "confirmation", "price", "pricing", "quotation", "payment", "cancellation", "refund", "reschedule")),
    ("safety", ("safety", "child", "children", "age", "medical", "pregnancy", "alcohol", "weather", "restriction", "jacket", "jackets")),
    ("general_faq", ("faq",)),
)


def classify_knowledge_intent(question: str) -> KnowledgeIntentResult:
    """Classify locally using phrases before individual words; never logs input."""

    normalized = _normalize(question)
    for intent, phrases in _PHRASE_RULES:
        if any(_contains_phrase(normalized, phrase) for phrase in phrases):
            return _intent_result(intent, "high")
    words = set(normalized.split())
    for intent, keywords in _WORD_RULES:
        if words.intersection(keywords):
            return _intent_result(intent, "medium")
    return _intent_result("unknown", "low")


def _intent_result(intent: KnowledgeIntent, confidence: Confidence) -> KnowledgeIntentResult:
    if intent == "location":
        return KnowledgeIntentResult(intent, ("location_information",), ("faq",), confidence)
    if intent == "services":
        return KnowledgeIntentResult(intent, ("services",), ("faq",), confidence)
    if intent == "booking":
        return KnowledgeIntentResult(intent, ("booking_policy",), ("faq",), confidence)
    if intent == "safety":
        return KnowledgeIntentResult(intent, ("safety_guidelines",), ("faq",), confidence)
    if intent == "general_faq":
        return KnowledgeIntentResult(intent, ("faq",), ALL_RAIPUR_CATEGORIES[:-1], confidence)
    if intent == "unsupported_location":
        return KnowledgeIntentResult(intent, (), (), confidence, human_handover_required=True)
    return KnowledgeIntentResult(intent, (), ALL_RAIPUR_CATEGORIES, confidence)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None
