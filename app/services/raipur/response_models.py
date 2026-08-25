"""Lightweight response and context models shared by Raipur engines.

These models intentionally have no routing, provider, or persistence imports.
Their dataclass field order is part of the compatibility contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.services.booking_enquiries import BookingDetails
from app.services.raipur.sales_state import SalesStage


Action = Literal[
    "answer_information", "ask_booking_field", "check_availability",
    "booking_enquiry_saved", "pricing_sales_handover",
    "unsupported_location_handover", "low_confidence_handover",
    "general_human_handover",
]


@dataclass(frozen=True)
class KnowledgeDraft:
    text: str | None
    source_filename: str | None = None
    confidence: float | None = None
    low_confidence: bool = True
    section_heading: str | None = None
    retrieval_result_count: int | None = None
    source_document_id: str | None = None
    retrieved_section_headings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationContext:
    details: BookingDetails
    pending_field: str | None = None
    availability_requested: bool = False
    last_service_name: str | None = None
    last_service_code: str | None = None
    last_intent: str | None = None
    last_bot_action: str | None = None
    service_selection_prompted: bool = False
    service_details_requested: bool = False
    active_domain: str = "entartica"
    active_topic: str | None = None
    active_entity_type: str | None = None
    active_entity_name: str | None = None
    last_user_intent: str | None = None
    last_assistant_answer_summary: str | None = None
    pending_clarification: bool = False
    pending_clarification_type: str | None = None
    pending_clarification_options: tuple[str, ...] = ()
    preferred_language: str | None = None
    last_assistant_question: str | None = None
    pending_question_type: str | None = None
    pending_action: str | None = None
    pending_entity_type: str | None = None
    pending_entity_name: str | None = None
    pending_created_at: str | None = None
    pending_service_code: str | None = None
    pending_slots: dict[str, str | None] | None = None
    last_answer_source: str | None = None
    last_answer_sections: tuple[str, ...] = ()
    sales_stage: SalesStage = SalesStage.DISCOVERY
    selected_location: str | None = None
    active_journey: str | None = None
    active_form: str | None = None
    form_status: str = "not_started"
    form_values: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConversationResult:
    action: Action
    draft_text: str
    reason_code: str
    detected_intent: str
    detected_location: str
    response_language: str
    human_handover_required: bool
    booking_enquiry_created: bool = False
    booking_enquiry_updated: bool = False
    availability_status: str | None = None
    next_required_field: str | None = None
    draft_only: bool = True
    draft_saved: bool = False
    context: ConversationContext | None = None
    safe_metadata: dict[str, Any] | None = None
    template_key: str | None = None
    response_valid: bool = True
    response_validation_reason: str = "safe"
