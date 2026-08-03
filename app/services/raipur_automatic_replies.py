"""Narrow, disabled-by-default automatic replies using the approved draft sender."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from app.services.raipur_draft_sender import ApprovedDraftSendResult
from app.services.latency import latency_stage

logger = logging.getLogger("uvicorn.error")

_INTENT_CATEGORIES = {
    "greeting": "information", "self_introduction": "information",
    "general": "information", "general_conversation": "information",
    "service_definition": "information",
    "celebration_service_list": "services", "service_list": "services", "service_catalogue": "services",
    "services": "services", "service_confirmation": "services",
    "service_offered": "services", "celebration_service_confirmation": "services",
    "celebration_service_detail": "information", "service_detail": "information",
    "participation_eligibility": "information",
    "health_safety_eligibility": "information",
    "follow_up_detail": "information", "general_information": "information",
    "location": "location", "knowledge": "information",
    "safe_conversational_fallback": "information", "clarification": "information",
    "service_recommendation": "information", "general_conversation": "information",
    "generic_service_definition": "information", "service_correction": "information",
    "conversation_repair": "information",
    "human_contact_request": "information",
}
_SAFE_NON_RAG_BASES = {"deterministic", "self_introduction", "conversation_repair", "general_stable_knowledge", "conversational_fallback", "clarification"}
_SENT_REASONS = {
    "grounded_answer": "grounded_answer_sent",
    "approved_safe_fallback": "safe_fallback_sent",
    "clarification_question": "clarification_sent",
    "human_handover": "human_handover_sent",
    "direct_contact_details": "human_handover_sent",
}


@dataclass(frozen=True)
class AutomaticReplyResult:
    eligible: bool
    attempted: bool = False
    reason: str = "automatic_reply_disabled"
    response_sent: bool = False
    response_mode: str | None = None


def final_response_mode(orchestration: Any) -> str | None:
    """Classify the final safe response, independent of the raw intent name."""

    metadata = getattr(orchestration, "safe_metadata", None)
    if not isinstance(metadata, dict) or not getattr(orchestration, "response_valid", False):
        return None
    if metadata.get("response_mode") == "direct_contact_details":
        return "direct_contact_details"
    if getattr(orchestration, "human_handover_required", False):
        return "human_handover"
    basis = metadata.get("response_basis")
    if basis == "active_rag" or metadata.get("structured_grounding") is True:
        return "grounded_answer"
    if metadata.get("approved_safe_fallback") is True:
        return "approved_safe_fallback"
    if basis in _SAFE_NON_RAG_BASES:
        return "clarification_question"
    return None


def _safe_intent(orchestration: Any) -> str | None:
    """Map the safe final response category, not an untrusted raw intent alone."""

    metadata = getattr(orchestration, "safe_metadata", None)
    raw_intent = getattr(orchestration, "detected_intent", None)
    category = _INTENT_CATEGORIES.get(raw_intent) if isinstance(raw_intent, str) else None
    if category is None and isinstance(metadata, dict):
        value = metadata.get("automatic_reply_category")
        category = value if value in {"information", "location", "services"} else None
    if category is not None:
        return category
    return "information" if final_response_mode(orchestration) is not None else None


def eligible_for_automatic_reply(settings: Any, orchestration: Any, draft: dict[str, Any] | None) -> tuple[bool, str]:
    if not getattr(settings, "raipur_automatic_reply_enabled", False): return False, "automatic_reply_disabled"
    if not getattr(settings, "exotel_outbound_enabled", False) or not getattr(settings, "raipur_approved_draft_send_enabled", False): return False, "send_feature_disabled"
    raw_intent = getattr(orchestration, "detected_intent", None)
    intent = _safe_intent(orchestration)
    if intent is not None:
        logger.info("automatic_reply_category_mapped raw_intent=%s category=%s", raw_intent if isinstance(raw_intent, str) else "unknown", intent)
    allowed = getattr(settings, "raipur_automatic_reply_intents", ())
    metadata = getattr(orchestration, "safe_metadata", None)
    text = getattr(orchestration, "draft_text", None)
    response_mode = final_response_mode(orchestration)
    prohibited = ("price", "payment", "booking confirmation", "reservation", "refund", "cancel", "complaint")
    if response_mode is None: return False, "response_mode_unavailable"
    if intent not in allowed: return False, "category_not_enabled"
    if not isinstance(text, str) or not text.strip(): return False, "ineligible_content"
    if raw_intent != "self_introduction" and response_mode not in {"human_handover", "direct_contact_details"} and any(word in text.casefold() for word in prohibited): return False, "ineligible_content"
    if not isinstance(metadata, dict) or metadata.get("customer_response_sanitized") is not True: return False, "ungrounded_response"
    basis = metadata.get("response_basis")
    has_source = isinstance(metadata.get("source_filename"), str) and bool(metadata["source_filename"].strip())
    if metadata.get("structured_grounding") is True:
        pass
    elif basis == "active_rag":
        if not has_source: return False, "ungrounded_response"
        if raw_intent in {"participation_eligibility", "health_safety_eligibility"} and not (
            metadata.get("approved_active_exact_service") is True
            and isinstance(metadata.get("retrieval_service_code"), str)
            and metadata["retrieval_service_code"].strip()
        ):
            return False, "ungrounded_response"
    elif raw_intent in {"participation_eligibility", "health_safety_eligibility"} and response_mode == "approved_safe_fallback":
        if metadata.get("approved_safe_fallback") is not True or metadata.get("eligibility_subject_addressed") is not True:
            return False, "ungrounded_response"
    elif response_mode not in {"human_handover", "direct_contact_details"} and basis not in _SAFE_NON_RAG_BASES:
        return False, "ungrounded_response"
    if not isinstance(draft, dict) or draft.get("draft_status") != "pending_review" or draft.get("sent_at") or draft.get("external_message_id"): return False, "draft_not_eligible"
    return True, "eligible"


async def attempt_automatic_reply(*, settings: Any, orchestration: Any, draft: dict[str, Any] | None,
                                  recipient: str, repository: Any, sender_factory: Callable[[], Any]) -> AutomaticReplyResult:
    with latency_stage("automatic_reply_eligibility"):
        eligible, reason = eligible_for_automatic_reply(settings, orchestration, draft)
    if not eligible: return AutomaticReplyResult(False, reason=reason)
    response_mode = final_response_mode(orchestration)
    draft_id = draft.get("id")
    try: sender = sender_factory()
    except Exception: return AutomaticReplyResult(False, reason="sender_configuration_unavailable")
    if not isinstance(draft_id, str) or not repository.approve_draft(draft_id):
        return AutomaticReplyResult(False, reason="approval_failed")
    result: ApprovedDraftSendResult = await sender.send(draft_id, recipient, confirmed=True)
    response_sent = bool(getattr(result, "accepted", False) and getattr(result, "sid_recorded", False))
    reason = _SENT_REASONS[response_mode] if response_sent and response_mode in _SENT_REASONS else result.reason
    return AutomaticReplyResult(True, result.attempted, reason, response_sent=response_sent, response_mode=response_mode)
