"""Grounded, optional LLM composition for customer-facing sales replies."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Callable

from app.rag.customer_ready_knowledge import contains_governance_language
from app.prompts.raipur_system_prompt import RAIPUR_SYSTEM_PROMPT
from app.services.raipur.gold_example_selector import GoldExampleSelector, compact_gold_examples
from app.services.latency import latency_openai_call


class ResponseGoal(str, Enum):
    SERVICE_OVERVIEW = "service_overview"
    SERVICE_MORE_DETAILS = "service_more_details"
    FACTUAL_ANSWER = "factual_answer"
    CELEBRATION_DISCOVERY = "celebration_discovery"
    ASK_GUEST_COUNT = "ask_guest_count"
    ASK_DATE = "ask_date"
    ASK_PREFERENCE = "ask_preference"
    SERVICE_RECOMMENDATION = "service_recommendation"
    CLARIFY_SERVICE = "clarify_service"
    ACTIVITY_DISCOVERY = "activity_discovery"
    FAMILY_DISCOVERY = "family_discovery"
    VENUE_OVERVIEW = "venue_overview"


@dataclass(frozen=True)
class CustomerFacts:
    """Normalized customer facts; no retrieval or governance metadata."""
    experience_summary: str | None = None
    benefits: tuple[str, ...] = ()
    duration_type: str | None = None
    duration_value: str | None = None
    operating_hours: str | None = None
    access_type: str | None = None
    approved_inclusions: tuple[str, ...] = ()
    suitability: tuple[str, ...] = ()
    relevant_highlights: tuple[str, ...] = ()


@dataclass(frozen=True)
class SalesResponseBrief:
    response_goal: ResponseGoal
    customer_language: str
    service_code: str | None = None
    service_name: str | None = None
    approved_facts: tuple[str, ...] = ()
    customer_facts: CustomerFacts | None = None
    approved_options: tuple[str, ...] = ()
    known_occasion: str | None = None
    known_guest_count: int | None = None
    known_date: str | None = None
    known_preference: str | None = None
    recommended_service_codes: tuple[str, ...] = ()
    next_action: str | None = None
    next_question: str | None = None
    restrictions: tuple[str, ...] = (
        "Do not invent prices, availability, capacity, duration, inclusions, or booking confirmation.",
        "Use only supplied facts, options, recommendation, and next question.",
    )


@dataclass(frozen=True)
class SalesComposition:
    text: str | None
    valid: bool
    reason: str


class SalesResponseComposer:
    """Lets a model phrase an approved brief without making business decisions."""

    def __init__(self, responder: Callable[[SalesResponseBrief], str | None] | None = None) -> None:
        self._responder = responder

    def compose(self, brief: SalesResponseBrief) -> SalesComposition:
        if self._responder is None:
            return SalesComposition(None, False, "composer_unconfigured")
        try:
            text = self._responder(brief)
        except Exception:
            return SalesComposition(None, False, "composer_exception")
        if not _valid_composition(text, brief):
            return SalesComposition(None, False, "composer_validation_failed")
        return SalesComposition(text.strip(), True, "composed")


def build_sales_response_composer(settings: Any) -> SalesResponseComposer:
    key = getattr(settings, "openai_api_key", None)
    default_model = getattr(settings, "openai_chat_model", None)
    fine_tuned_model = getattr(settings, "chiki_sales_fine_tuned_model", None)
    use_fine_tuned = bool(getattr(settings, "chiki_sales_fine_tuned_enabled", False))
    use_gold_fewshot = bool(getattr(settings, "chiki_sales_gold_fewshot_enabled", False))
    model = fine_tuned_model if use_fine_tuned and isinstance(fine_tuned_model, str) and fine_tuned_model.strip() else default_model
    if key is None or not isinstance(model, str) or not model.strip():
        return SalesResponseComposer()
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key.get_secret_value())
    except Exception:
        return SalesResponseComposer()

    def responder(brief: SalesResponseBrief) -> str | None:
        instructions = RAIPUR_SYSTEM_PROMPT
        payload = {
            "response_goal": brief.response_goal.value,
            "customer_language": brief.customer_language,
            "service_code": brief.service_code,
            "service_name": brief.service_name,
            "approved_facts": brief.approved_facts,
            "customer_facts": brief.customer_facts,
            "approved_options": brief.approved_options,
            "known_occasion": brief.known_occasion,
            "known_guest_count": brief.known_guest_count,
            "known_date": brief.known_date,
            "known_preference": brief.known_preference,
            "recommended_service_codes": brief.recommended_service_codes,
            "next_action": brief.next_action,
            "next_question": brief.next_question,
            "restrictions": brief.restrictions,
        }
        request_input = str(payload)
        if use_gold_fewshot:
            try:
                demonstrations = compact_gold_examples(GoldExampleSelector().select(brief))
            except Exception:
                demonstrations = ""
            if demonstrations:
                request_input = (
                    "Examples demonstrate response style and structure only. Never use a factual value from an example "
                    "unless it also appears in the CURRENT CUSTOMER BRIEF. The current brief is the only factual authority.\n\n"
                    f"{demonstrations}\n\nCURRENT CUSTOMER BRIEF:\n{payload}\n\nCompose the reply."
                )
        with latency_openai_call("sales_response_composer", model.strip()):
            response = client.responses.create(model=model.strip(), instructions=instructions, input=request_input)
        output = getattr(response, "output_text", None)
        return output if isinstance(output, str) else None

    return SalesResponseComposer(responder)


_UNSAFE = re.compile(
    r"(?:\b(?:price|pricing|cost|rate|inr|rs\.?)\b|₹|\b(?:available|slot)\s+(?:now|today|tomorrow)\b|"
    r"\b(?:booking|payment)\s+(?:is\s+)?confirmed\b|\b(?:source|metadata|retrieval|governance|verification note)\b)",
    re.I,
)
_UNSUPPORTED_OFFERING = re.compile(r"\b(?:yacht|luxury\s+cruise|dinner\s+cruise)\b", re.I)


def _valid_composition(value: object, brief: SalesResponseBrief) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 1200:
        return False
    if _UNSAFE.search(value) or _UNSUPPORTED_OFFERING.search(value) or contains_governance_language(value):
        return False
    # A supplied next question is a policy decision. Require its key wording so
    # the model cannot replace it with a different qualification question.
    if brief.next_question:
        keywords = [word for word in re.findall(r"[a-z0-9]+", brief.next_question.casefold()) if len(word) >= 4]
        if keywords and not any(word in value.casefold() for word in keywords[-4:]):
            return False
    return True
