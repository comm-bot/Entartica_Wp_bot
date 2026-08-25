"""Compact, privacy-safe observability for one Raipur conversation turn."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.latency import LatencyTrace
from app.services.raipur.response_models import ConversationContext, ConversationResult


@dataclass(frozen=True)
class TelemetryTiming:
    total: int
    understanding: int = 0
    retrieval: int = 0
    recommendation: int = 0
    response_generation: int = 0


@dataclass(frozen=True)
class ConversationTelemetryEvent:
    conversation_id: str
    message_id: str
    route: str | None
    graph_intent: str
    topic: str | None
    service_code: str | None
    understanding_invoked: bool
    understanding_intent: str | None
    understanding_service_code: str | None
    understanding_occasion: str | None
    understanding_guest_count: int | None
    understanding_date_present: bool
    understanding_preference: str | None
    understanding_restricted_intent: str | None
    sales_stage_before: str | None
    sales_stage_after: str | None
    pending_field_before: str | None
    pending_field_after: str | None
    guest_count_present: bool
    planned_date_present: bool
    selected_service: str | None
    sales_next_action: str | None
    recommendation_invoked: bool
    recommended_service_codes: tuple[str, ...]
    recommendation_insufficient_evidence: bool | None
    occasion_evidence_used: bool
    preference_evidence_used: bool
    capacity_status_used: tuple[str, ...]
    generic_fallback_used: bool
    response_type: str
    timing_ms: TelemetryTiming
    error_categories: tuple[str, ...] = ()

    def as_safe_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_conversation_telemetry(
    *,
    conversation_id: str,
    message_id: str,
    before: ConversationContext | None,
    result: ConversationResult,
    trace: LatencyTrace | None,
    local_total_ms: int,
) -> ConversationTelemetryEvent:
    metadata = result.safe_metadata if isinstance(result.safe_metadata, dict) else {}
    understanding = metadata.get("customer_understanding")
    understanding = understanding if isinstance(understanding, dict) else {}
    after = result.context
    route = metadata.get("selected_route") if isinstance(metadata.get("selected_route"), str) else None
    generic = route == "answer_general_openai" or bool(metadata.get("generic_fallback_used"))
    recommendation_invoked = bool(metadata.get("recommendation_invoked"))
    insufficient = metadata.get("recommendation_insufficient_evidence")
    capacity = metadata.get("capacity_compatibility")
    capacity_rows = capacity if isinstance(capacity, list) else []
    capacity_statuses = tuple(sorted({
        row["capacity_status"] for row in capacity_rows
        if isinstance(row, dict) and isinstance(row.get("capacity_status"), str)
    }))
    errors: list[str] = []
    if metadata.get("understanding_failed") is True:
        errors.append("UNDERSTANDING_FAILED")
    if metadata.get("retrieval_failed") is True:
        errors.append("RETRIEVAL_FAILED")
    if recommendation_invoked and insufficient is True:
        errors.append("RECOMMENDATION_INSUFFICIENT")
    if generic:
        errors.append("GENERIC_FALLBACK")
    total = round(trace.total_ms()) if trace is not None else local_total_ms
    timing = TelemetryTiming(
        total=total,
        understanding=trace.combined_value("customer_understanding") if trace else 0,
        retrieval=trace.combined_value("exact_section_lookup", "query_embedding", "Supabase_vector_search") if trace else 0,
        recommendation=trace.combined_value("celebration_recommendation") if trace else 0,
        response_generation=trace.combined_value("OpenAI_answer_generation") if trace else 0,
    )
    return ConversationTelemetryEvent(
        conversation_id=conversation_id,
        message_id=message_id,
        route=route,
        graph_intent=result.detected_intent,
        topic=metadata.get("topic") if isinstance(metadata.get("topic"), str) else None,
        service_code=metadata.get("service_code") if isinstance(metadata.get("service_code"), str) else None,
        understanding_invoked=bool(metadata.get("understanding_invoked")),
        understanding_intent=understanding.get("intent") if isinstance(understanding.get("intent"), str) else None,
        understanding_service_code=understanding.get("service_code") if isinstance(understanding.get("service_code"), str) else None,
        understanding_occasion=understanding.get("occasion") if isinstance(understanding.get("occasion"), str) else None,
        understanding_guest_count=understanding.get("guest_count") if isinstance(understanding.get("guest_count"), int) else None,
        understanding_date_present=bool(understanding.get("planned_date_text")),
        understanding_preference=understanding.get("preference") if isinstance(understanding.get("preference"), str) else None,
        understanding_restricted_intent=understanding.get("restricted_intent") if isinstance(understanding.get("restricted_intent"), str) else None,
        sales_stage_before=before.sales_stage.value if before is not None else None,
        sales_stage_after=after.sales_stage.value if after is not None else None,
        pending_field_before=before.pending_field if before is not None else None,
        pending_field_after=after.pending_field if after is not None else None,
        guest_count_present=bool(after and after.details.total_guests is not None),
        planned_date_present=bool(after and after.details.preferred_date is not None),
        selected_service=after.last_service_code if after is not None else None,
        sales_next_action=metadata.get("sales_next_action") if isinstance(metadata.get("sales_next_action"), str) else None,
        recommendation_invoked=recommendation_invoked,
        recommended_service_codes=tuple(item for item in metadata.get("recommended_service_codes", ()) if isinstance(item, str)),
        recommendation_insufficient_evidence=insufficient if isinstance(insufficient, bool) else None,
        occasion_evidence_used=bool(metadata.get("occasion_evidence_used")),
        preference_evidence_used=bool(metadata.get("preference_evidence_used")),
        capacity_status_used=capacity_statuses,
        generic_fallback_used=generic,
        response_type=result.action,
        timing_ms=timing,
        error_categories=tuple(errors),
    )
