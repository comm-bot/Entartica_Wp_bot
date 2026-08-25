"""Privacy-safe structured telemetry for Raipur turns."""
from datetime import date

from app.services.booking_enquiries import BookingDetails
from app.services.latency import LatencyTrace
from app.services.raipur.conversation_telemetry import build_conversation_telemetry
from app.services.raipur.response_models import ConversationContext, ConversationResult
from app.services.raipur.sales_state import SalesStage


def _context(*, guests=None, planned=None, pending=None, stage=SalesStage.DISCOVERY):
    return ConversationContext(
        BookingDetails(None, None, planned, None, None, None, guests),
        pending_field=pending,
        sales_stage=stage,
    )


def test_event_contains_structured_results_and_state_delta_without_message_text():
    before = _context(pending="total_guests", stage=SalesStage.QUALIFYING)
    after = _context(guests=12, planned=date(2026, 8, 13), stage=SalesStage.QUALIFIED)
    metadata = {
        "selected_route": "answer_venue_knowledge",
        "topic": "celebration_catalogue",
        "customer_understanding": {
            "intent": "celebration", "occasion": "birthday", "guest_count": 12,
            "planned_date_text": "13/08/2026", "preference": "lively_party",
            "service_code": None, "restricted_intent": None,
        },
        "understanding_invoked": True,
        "sales_next_action": "recommend_service",
        "recommendation_invoked": True,
        "recommended_service_codes": ["party_boat_celebration"],
        "recommendation_insufficient_evidence": False,
        "occasion_evidence_used": True,
        "preference_evidence_used": True,
        "capacity_compatibility": [{"service_code": "party_boat_celebration", "compatible": None, "capacity_status": "conflict"}],
    }
    result = ConversationResult(
        "answer_information", "customer-facing text", "graph_route", "customer_understanding_update",
        "raipur", "en", False, context=after, safe_metadata=metadata,
    )
    trace = LatencyTrace(request_id="safe")
    trace.stages_ms.update({"customer_understanding": 4.4, "celebration_recommendation": 2.2})
    event = build_conversation_telemetry(
        conversation_id="conversation", message_id="message", before=before,
        result=result, trace=trace, local_total_ms=9,
    )
    payload = event.as_safe_dict()
    assert payload["understanding_occasion"] == "birthday"
    assert payload["sales_stage_before"] == "qualifying" and payload["sales_stage_after"] == "qualified"
    assert payload["pending_field_before"] == "total_guests" and payload["pending_field_after"] is None
    assert payload["recommended_service_codes"] == ("party_boat_celebration",)
    assert payload["capacity_status_used"] == ("conflict",)
    assert payload["timing_ms"]["understanding"] == 4
    serialized = str(payload)
    assert "customer-facing text" not in serialized


def test_failure_categories_are_safe_and_generic_fallback_is_measured():
    result = ConversationResult(
        "answer_information", "not logged", "graph_route", "general_question", "raipur", "en", False,
        context=_context(), safe_metadata={
            "selected_route": "answer_general_openai", "understanding_invoked": True,
            "understanding_failed": True,
        },
    )
    event = build_conversation_telemetry(
        conversation_id="c", message_id="m", before=None, result=result, trace=None, local_total_ms=7,
    )
    assert event.generic_fallback_used
    assert event.error_categories == ("UNDERSTANDING_FAILED", "GENERIC_FALLBACK")
    assert event.timing_ms.total == 7
