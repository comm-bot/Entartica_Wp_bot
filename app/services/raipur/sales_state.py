"""Pure, typed sales-stage and next-action decisions for Raipur conversations."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.raipur.response_models import ConversationContext


class SalesStage(str, Enum):
    LEAD = "lead"
    DISCOVERY = "discovery"
    OPTIONS_SHOWN = "options_shown"
    SERVICE_SELECTED = "service_selected"
    QUALIFYING = "qualifying"
    QUALIFIED = "qualified"
    PACKAGE_PRESENTED = "package_presented"
    INTERESTED = "interested"
    DETAILS_COLLECTED = "details_collected"
    PAYMENT_PENDING = "payment_pending"
    BOOKED = "booked"
    HANDOVER = "handover"


class SalesNextAction(str, Enum):
    SHOW_OPTIONS = "show_options"
    ANSWER_SERVICE = "answer_service"
    ASK_GUEST_COUNT = "ask_guest_count"
    ASK_DATE = "ask_date"
    ASK_PREFERENCE = "ask_preference"
    RECOMMEND_SERVICE = "recommend_service"
    CONTINUE_DISCOVERY = "continue_discovery"
    HANDOVER = "handover"
    NONE = "none"


@dataclass(frozen=True)
class SalesDecision:
    action: SalesNextAction
    reason: str
    next_stage: SalesStage
    requested_field: str | None = None


_HIGHER_PRIORITY_INTENTS = {
    "pricing", "booking", "availability", "payment", "cancellation_refund",
    "human_support", "contact_information", "location", "greeting",
}


def evaluate_sales_next_action(
    context: "ConversationContext",
    *,
    current_intent: str | None = None,
) -> SalesDecision:
    """Return the next sales suggestion without mutating state or doing I/O."""

    if current_intent in _HIGHER_PRIORITY_INTENTS:
        return SalesDecision(
            SalesNextAction.NONE, "higher_priority_route_owns_turn", context.sales_stage
        )

    if not context.last_service_code:
        if context.active_topic == "celebration_catalogue":
            if context.details.total_guests is None:
                return SalesDecision(
                    SalesNextAction.ASK_GUEST_COUNT,
                    "celebration_needs_guest_count",
                    SalesStage.QUALIFYING,
                    "total_guests",
                )
            if context.details.preferred_date is None:
                return SalesDecision(
                    SalesNextAction.ASK_DATE,
                    "celebration_guest_count_known_date_missing",
                    SalesStage.QUALIFYING,
                    "preferred_date",
                )
            if (context.pending_slots or {}).get("celebration_preference"):
                return SalesDecision(
                    SalesNextAction.RECOMMEND_SERVICE,
                    "celebration_minimum_qualification_complete",
                    SalesStage.QUALIFIED,
                )
            return SalesDecision(
                SalesNextAction.ASK_PREFERENCE,
                "celebration_needs_supported_preference",
                SalesStage.QUALIFYING,
                "celebration_preference",
            )
        if context.active_topic in {"activity_catalogue", "package_catalogue"}:
            return SalesDecision(
                SalesNextAction.NONE, "options_already_shown", SalesStage.OPTIONS_SHOWN
            )
        return SalesDecision(
            SalesNextAction.NONE, "no_commercial_context", SalesStage.DISCOVERY
        )

    if context.details.total_guests is None:
        return SalesDecision(
            SalesNextAction.ASK_GUEST_COUNT,
            "selected_service_needs_guest_count",
            SalesStage.QUALIFYING,
            "total_guests",
        )

    if context.details.preferred_date is None:
        return SalesDecision(
            SalesNextAction.ASK_DATE,
            "guest_count_known_date_missing",
            SalesStage.QUALIFYING,
            "preferred_date",
        )

    return SalesDecision(
        SalesNextAction.HANDOVER,
        "minimum_qualification_complete",
        SalesStage.QUALIFIED,
    )
