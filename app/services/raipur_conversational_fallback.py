"""Grounded, validated conversational fallback for safe Raipur questions."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from app.prompts.raipur_system_prompt import RAIPUR_SYSTEM_PROMPT


@dataclass(frozen=True)
class ConversationalFallbackResult:
    text: str | None
    valid: bool
    retries: int = 0
    reason: str = "clarification"


_UNSAFE = re.compile(
    r"(?:\b(?:rs\.?|inr|₹|price|pricing|cost|rate)\b|₹|\b(?:available|slot)\s+(?:now|today|tomorrow)\b|\b(?:booking|payment)\s+(?:is\s+)?confirmed\b|\b(?:refund|cancel(?:lation)?)\b|\b(?:safe|safety)\s+guarantee\b|\bcompletely\s+safe\b|\b(?:\d+\s*(?:guests?|people|hours?|hrs?))\b|\b(?:includes?|inclusions?|package)\b|\b(?:source|metadata|confidence|retrieval|document)\b)",
    re.IGNORECASE,
)


class RaipurConversationalFallback:
    """Uses an injected response model and rejects unsupported customer output."""

    def __init__(self, responder: Callable[[str, dict[str, Any], bool], str | None] | None = None) -> None:
        self._responder = responder

    def respond(
        self,
        *,
        question: str,
        language: str,
        selected_service: str | None,
        approved_excerpts: tuple[str, ...] = (),
        active_services: tuple[str, ...] = (),
        previous_response_summary: str | None = None,
        generic_definition: bool = False,
    ) -> ConversationalFallbackResult:
        context = {
            "customer_message": question,
            "location": "Raipur",
            "selected_service": selected_service,
            "approved_knowledge_excerpts": approved_excerpts[:3],
            "active_services": active_services,
            "previous_response_summary": previous_response_summary,
            "language": language,
            "restricted_fields": "price,payment,booking confirmation,live availability,capacity,duration,inclusions,medical,safety guarantees",
            "response_mode": "generic_service_definition" if generic_definition else "safe_conversational_fallback",
        }
        for retry in (False, True):
            text = self._call(context, retry)
            if _safe_customer_text(text, generic_definition=generic_definition):
                return ConversationalFallbackResult(text.strip(), True, int(retry), "grounded" if approved_excerpts else "clarification")
        return ConversationalFallbackResult(None, False, 1, "validation_failed")

    def _call(self, context: dict[str, Any], retry: bool) -> str | None:
        if self._responder is None:
            return _deterministic_clarification(context)
        try:
            return self._responder(RAIPUR_SYSTEM_PROMPT, context, retry)
        except Exception:
            return None


def build_raipur_conversational_fallback(settings: Any) -> RaipurConversationalFallback:
    """Construct the optional OpenAI responder only when explicitly configured."""
    key = getattr(settings, "openai_api_key", None)
    model = getattr(settings, "openai_chat_model", None)
    if key is None or not isinstance(model, str) or not model.strip():
        return RaipurConversationalFallback()
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key.get_secret_value())
    except Exception:
        return RaipurConversationalFallback()

    def responder(prompt: str, context: dict[str, Any], retry: bool) -> str | None:
        correction = "Your previous draft was unsafe. Return only a safe clarification." if retry else ""
        prepared_input = (
            "<approved_raipur_context>\n"
            f"{context}\n"
            "</approved_raipur_context>\n"
            "Return a customer-facing answer only."
        )
        response = client.responses.create(model=model.strip(), instructions=f"{prompt}\n{correction}", input=prepared_input)
        output = getattr(response, "output_text", None)
        return output if isinstance(output, str) else None

    return RaipurConversationalFallback(responder)


def _safe_customer_text(value: object, *, generic_definition: bool = False) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500 or _UNSAFE.search(value):
        return False
    return not generic_definition or not re.search(r"\b(?:entartica|raipur)\b", value, re.IGNORECASE)


def _deterministic_clarification(context: dict[str, Any]) -> str:
    if context.get("response_mode") == "generic_service_definition":
        service = context.get("selected_service")
        if service == "Bumper Boat":
            return "A bumper boat is generally a small recreational boat designed for gentle maneuvering and light contact on water."
        return f"{service} is generally a recreational water activity; its exact operation can vary by equipment model." if isinstance(service, str) else "This is generally a recreational water activity; its exact operation can vary by equipment model."
    services = tuple(item for item in context.get("active_services", ()) if isinstance(item, str) and item.strip())
    language = context.get("language")
    if language == "hinglish":
        return "Aap thrill, relaxation, family activity ya celebration mein se kya prefer karenge?"
    if language == "hi":
        return "आप रोमांच, आराम, परिवार गतिविधि या सेलिब्रेशन में से क्या पसंद करेंगे?"
    if services:
        return "I can help you choose an approved Raipur experience. Do you prefer thrill, relaxation, a family activity, or a celebration?"
    return "Please tell me what kind of Raipur experience you would prefer."
