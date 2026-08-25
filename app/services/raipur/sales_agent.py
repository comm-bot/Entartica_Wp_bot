"""One-call structured Chiki sales response plus validated turn understanding."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from app.prompts.raipur_system_prompt import RAIPUR_SYSTEM_PROMPT
from app.services.latency import latency_openai_call
from app.services.raipur.customer_understanding import (
    CustomerUnderstanding,
    UnderstandingIntent,
    UnderstandingLanguage,
    UnderstandingPreference,
    UnderstandingTopic,
    RestrictedIntent,
    validate_customer_understanding,
)
from app.services.raipur.sales_response_composer import SalesResponseBrief, _valid_composition


class _SalesAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply: str = Field(min_length=1, max_length=1200)
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
    asked_for: str | None = Field(default=None, max_length=80)
    handover_requested: bool = False


@dataclass(frozen=True)
class SalesAgentBrief:
    current_message: str
    compact_context: dict[str, Any]
    response_brief: SalesResponseBrief


@dataclass(frozen=True)
class SalesAgentResult:
    reply: str | None
    understanding: CustomerUnderstanding | None
    asked_for: str | None = None
    valid: bool = False
    reason: str = "sales_agent_unconfigured"


SalesAgentResponder = Callable[[SalesAgentBrief], _SalesAgentOutput | dict[str, Any]]


class SalesAgent:
    def __init__(self, responder: SalesAgentResponder | None = None) -> None:
        self._responder = responder

    @property
    def configured(self) -> bool:
        return self._responder is not None

    def respond(self, brief: SalesAgentBrief) -> SalesAgentResult:
        if self._responder is None:
            return SalesAgentResult(None, None)
        try:
            raw = self._responder(brief)
            parsed = raw if isinstance(raw, _SalesAgentOutput) else _SalesAgentOutput.model_validate(raw)
            if parsed.handover_requested or not _valid_composition(parsed.reply, brief.response_brief):
                return SalesAgentResult(None, None, reason="sales_agent_validation_failed")
            understanding = validate_customer_understanding(
                brief.current_message,
                parsed.model_dump(exclude={"reply", "asked_for", "handover_requested"}),
            )
            return SalesAgentResult(parsed.reply.strip(), understanding, parsed.asked_for, True, "composed")
        except Exception:
            return SalesAgentResult(None, None, reason="sales_agent_exception")


def build_sales_agent(settings: Any) -> SalesAgent:
    key = getattr(settings, "openai_api_key", None)
    model = getattr(settings, "openai_chat_model", None)
    if key is None or not isinstance(model, str) or not model.strip():
        return SalesAgent()
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key.get_secret_value())
    except Exception:
        return SalesAgent()

    instructions = RAIPUR_SYSTEM_PROMPT + """

Return the typed structured result. The reply is the customer-facing WhatsApp response.
Extract only facts explicitly present in the current message; null never means erase stored context.
Use only supplied approved facts and approved options. Never introduce another service or business fact.
Hard restrictions are authoritative. Do not request handover unless the supplied policy requires it.
"""

    def responder(brief: SalesAgentBrief) -> _SalesAgentOutput:
        payload = {
            "current_customer_message": brief.current_message,
            "compact_recent_context": brief.compact_context,
            "business_objective": brief.response_brief.response_goal.value,
            "service_code": brief.response_brief.service_code,
            "service_name": brief.response_brief.service_name,
            "approved_facts": brief.response_brief.approved_facts,
            "approved_options": brief.response_brief.approved_options,
            "known_occasion": brief.response_brief.known_occasion,
            "known_guest_count": brief.response_brief.known_guest_count,
            "known_date": brief.response_brief.known_date,
            "known_preference": brief.response_brief.known_preference,
            "recommended_service_codes": brief.response_brief.recommended_service_codes,
            "useful_next_action": brief.response_brief.next_action,
            "allowed_next_question": brief.response_brief.next_question,
            "hard_restrictions": brief.response_brief.restrictions,
        }
        with latency_openai_call("sales_agent", model.strip()):
            response = client.responses.parse(
                model=model.strip(), instructions=instructions,
                input=json.dumps(payload, ensure_ascii=False), text_format=_SalesAgentOutput,
            )
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, _SalesAgentOutput):
            raise ValueError("missing_structured_sales_agent_result")
        return parsed

    return SalesAgent(responder)
