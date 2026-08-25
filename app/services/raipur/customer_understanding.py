"""Structured customer meaning extraction for Raipur shadow evaluation.

This module describes the current message only. It never selects a route,
executes policy, retrieves knowledge, or produces customer-facing text.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.raipur.language import detect_language
from app.services.raipur.response_models import ConversationContext
from app.services.latency import latency_openai_call
from app.services.raipur.service_resolver import resolve_service
from app.services.raipur.topic_resolver import resolve_topic, topic_for_graph


UnderstandingIntent = Literal[
    "celebration", "family_discovery", "service_question", "activity_discovery",
    "venue_information", "greeting", "acknowledgement", "contact", "location",
    "pricing", "booking", "availability", "cancellation_refund", "payment",
    "general", "unknown",
]
RestrictedIntent = Literal[
    "pricing", "booking", "availability", "payment", "cancellation_refund", "human_request"
]
UnderstandingTopic = Literal[
    "discovery", "overview", "capacity", "duration", "inclusions", "suitable_for",
    "operating_hours", "safety", "swimming", "eligibility", "how_it_works",
]
UnderstandingLanguage = Literal["en", "hi", "hinglish"]
UnderstandingPreference = Literal[
    "private_intimate", "lively_party", "relaxed", "water_adventure", "couple", "family"
]


class CustomerUnderstanding(BaseModel):
    """Validated description of facts expressed in one customer message."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    intent: UnderstandingIntent = "unknown"
    service_code: str | None = None
    occasion: str | None = None
    guest_count: int | None = Field(default=None, ge=1, le=999)
    adult_count: int | None = Field(default=None, ge=0, le=999)
    child_count: int | None = Field(default=None, ge=0, le=999)
    planned_date_text: str | None = Field(default=None, max_length=80)
    customer_location: str | None = Field(default=None, max_length=100)
    preference: UnderstandingPreference | None = None
    topic: UnderstandingTopic | None = None
    language: UnderstandingLanguage = "en"
    restricted_intent: RestrictedIntent | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class _ExtractedMeaning(BaseModel):
    """Model-facing schema; raw service text is canonicalized after extraction."""

    model_config = ConfigDict(extra="forbid")
    intent: UnderstandingIntent = "unknown"
    service_mention: str | None = Field(default=None, max_length=100)
    occasion: str | None = Field(default=None, max_length=80)
    guest_count: int | None = Field(default=None, ge=1, le=999)
    adult_count: int | None = Field(default=None, ge=0, le=999)
    child_count: int | None = Field(default=None, ge=0, le=999)
    planned_date_text: str | None = Field(default=None, max_length=80)
    customer_location: str | None = Field(default=None, max_length=100)
    preference: UnderstandingPreference | None = None
    topic: UnderstandingTopic | None = None
    language: UnderstandingLanguage | None = None
    restricted_intent: RestrictedIntent | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


StructuredExtractor = Callable[[str, dict[str, Any]], _ExtractedMeaning | dict[str, Any]]


class CustomerUnderstandingService:
    """Extract structured meaning and enforce existing canonical identities."""

    def __init__(self, extractor: StructuredExtractor | None = None) -> None:
        self._extractor = extractor

    def understand(
        self,
        message: str,
        context: ConversationContext | None = None,
    ) -> CustomerUnderstanding:
        return self.understand_observed(message, context)[0]

    def understand_observed(
        self,
        message: str,
        context: ConversationContext | None = None,
    ) -> tuple[CustomerUnderstanding, bool]:
        """Return structured meaning plus a safe extraction-failure flag."""
        language = detect_language(message)
        if self._extractor is None:
            return CustomerUnderstanding(language=language), False
        try:
            extracted_value = self._extractor(message, compact_understanding_context(context))
            return validate_customer_understanding(message, extracted_value), False
        except (Exception, ValidationError):
            return CustomerUnderstanding(language=language), True


def validate_customer_understanding(
    message: str,
    value: _ExtractedMeaning | dict[str, Any],
) -> CustomerUnderstanding:
    """Canonicalize and validate model-extracted fields through one boundary."""
    extracted = value if isinstance(value, _ExtractedMeaning) else _ExtractedMeaning.model_validate(value)
    resolution_input = " ".join(
        part for part in (message, extracted.service_mention) if isinstance(part, str) and part.strip()
    )
    service = resolve_service(resolution_input)
    topic = extracted.topic
    deterministic_topic = topic_for_graph(resolve_topic(message))
    if deterministic_topic in UnderstandingTopic.__args__:
        topic = deterministic_topic  # type: ignore[assignment]
    return CustomerUnderstanding(
        intent=extracted.intent,
        service_code=service.service_code if service.matched else None,
        occasion=extracted.occasion,
        guest_count=extracted.guest_count,
        adult_count=extracted.adult_count,
        child_count=extracted.child_count,
        planned_date_text=extracted.planned_date_text,
        customer_location=extracted.customer_location,
        preference=extracted.preference,
        topic=topic,
        language=extracted.language or detect_language(message),
        restricted_intent=extracted.restricted_intent,
        confidence=extracted.confidence,
    )


def compact_understanding_context(context: ConversationContext | None) -> dict[str, Any]:
    """Expose only state useful for interpreting a short current reply."""
    if context is None:
        return {}
    return {
        "pending_field": context.pending_field,
        "pending_question_type": context.pending_question_type,
        "selected_service_code": context.last_service_code,
        "selected_service_name": context.last_service_name,
        "sales_stage": context.sales_stage.value,
        "sales_intent": "celebration" if context.active_entity_name == "celebration" or context.pending_action == "celebration_sales" else None,
        "known_guest_count": context.details.total_guests,
        "known_planned_date": context.details.preferred_date.isoformat() if context.details.preferred_date else None,
        "known_adult_count": context.details.adults_count,
        "known_child_count": context.details.children_count,
        "known_customer_location": (context.form_values or {}).get("customer_location"),
    }


def parse_planned_date_text(value: str | None, today: date | None = None) -> date | None:
    """Parse supported customer date text without implying availability."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", value.strip().rstrip(".!"), flags=re.I)
    reference = today or date.today()
    lowered = text.casefold()
    if lowered == "tomorrow":
        return reference + timedelta(days=1)
    if lowered == "today":
        return reference
    weekday = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    if lowered.startswith("this ") and lowered[5:] in weekday:
        days = (weekday[lowered[5:]] - reference.weekday()) % 7
        return reference + timedelta(days=days or 7)
    if lowered.startswith("next ") and lowered[5:] in weekday:
        days = (weekday[lowered[5:]] - reference.weekday()) % 7
        return reference + timedelta(days=days or 7)
    for pattern in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    for pattern in ("%d %B", "%d %b"):
        try:
            parsed = datetime.strptime(text, pattern).date().replace(year=reference.year)
            return parsed if parsed >= reference else parsed.replace(year=reference.year + 1)
        except ValueError:
            pass
    return None


def deterministic_celebration_understanding(message: object) -> CustomerUnderstanding | None:
    """Extract explicit date/guest slots using the existing typed understanding model."""
    if not isinstance(message, str) or not message.strip():
        return None
    text = message.strip()
    guest_match = re.search(
        r"\b(?:(?:total\s+)(\d{1,3})(?!\s*(?:/|-))|(\d{1,3})\s*(?:guests?|people|persons?|pax|log|members?))\b|,\s*(\d{1,3})\s*$",
        text, re.I,
    )
    guest_count = int(next(group for group in guest_match.groups() if group)) if guest_match else None
    date_match = re.search(
        r"\b(today|tomorrow|\d{1,2}(?:st|nd|rd|th)?(?:/\d{1,2}(?:/\d{2,4})?|\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{4})?))\b",
        text, re.I,
    )
    planned_text = date_match.group(1) if date_match else None
    if planned_text and "/" in planned_text and planned_text.count("/") == 1:
        day, month = planned_text.split("/")
        reference = date.today()
        try:
            parsed = date(reference.year, int(month), int(day))
            parsed = parsed if parsed >= reference else parsed.replace(year=reference.year + 1)
            planned_text = parsed.isoformat()
        except ValueError:
            planned_text = None
    if guest_count is None and planned_text is None:
        return None
    return CustomerUnderstanding(
        intent="celebration", guest_count=guest_count, planned_date_text=planned_text,
        language=detect_language(text), confidence=1.0,
    )


_EXTRACTION_INSTRUCTIONS = """Extract only meaning explicitly present in the current customer message.
Use the supplied compact context only to interpret short replies; do not copy known values into output.
Return the structured schema. Do not answer, recommend, route, retrieve facts, quote prices, or confirm anything.
Put any service wording in service_mention; never invent an internal service code.
Leave uncertain fields null and use intent unknown when meaning is unclear.
Understand English, Hindi, Hinglish, ordinary typos, and multiple facts in one message."""


def build_customer_understanding_service(settings: Any) -> CustomerUnderstandingService:
    """Build an optional Responses structured-output extractor; fail closed."""
    key = getattr(settings, "openai_api_key", None)
    model = getattr(settings, "openai_chat_model", None)
    if key is None or not isinstance(model, str) or not model.strip():
        return CustomerUnderstandingService()
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key.get_secret_value())
    except Exception:
        return CustomerUnderstandingService()

    def extract(message: str, context: dict[str, Any]) -> _ExtractedMeaning:
        with latency_openai_call("customer_understanding", model.strip()):
            response = client.responses.parse(
                model=model.strip(),
                instructions=_EXTRACTION_INSTRUCTIONS,
                input=json.dumps({"current_message": message, "compact_context": context}, ensure_ascii=False),
                text_format=_ExtractedMeaning,
            )
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, _ExtractedMeaning):
            raise ValueError("missing_structured_understanding")
        return parsed

    return CustomerUnderstandingService(extract)
