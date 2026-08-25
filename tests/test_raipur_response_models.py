from dataclasses import asdict, fields

from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.services.booking_enquiries import BookingDetails
from app.services.raipur.response_models import ConversationContext, ConversationResult, KnowledgeDraft
from app.services.raipur_conversation import (
    ConversationContext as LegacyConversationContext,
    ConversationResult as LegacyConversationResult,
    KnowledgeDraft as LegacyKnowledgeDraft,
)


def _details() -> BookingDetails:
    return BookingDetails("Customer", "Jet Ski Ride", None, None, 2, 0, 2)


def test_legacy_model_imports_are_identity_compatible_reexports():
    assert LegacyKnowledgeDraft is KnowledgeDraft
    assert LegacyConversationContext is ConversationContext
    assert LegacyConversationResult is ConversationResult


def test_knowledge_draft_constructor_defaults_field_order_and_repr_are_unchanged():
    draft = KnowledgeDraft("Approved answer")

    assert [field.name for field in fields(KnowledgeDraft)] == [
        "text", "source_filename", "confidence", "low_confidence",
        "section_heading", "retrieval_result_count", "source_document_id",
        "retrieved_section_headings",
    ]
    assert draft == LegacyKnowledgeDraft("Approved answer")
    assert asdict(draft) == {
        "text": "Approved answer", "source_filename": None, "confidence": None,
        "low_confidence": True, "section_heading": None,
        "retrieval_result_count": None, "source_document_id": None,
        "retrieved_section_headings": (),
    }
    assert repr(draft).startswith("KnowledgeDraft(")


def test_context_and_result_constructor_defaults_and_serialization_contract():
    context = ConversationContext(_details(), last_service_code="jet_ski_ride")
    result = ConversationResult(
        "answer_information", "Approved answer", "approved_service_detail",
        "service_detail", "raipur", "en", False, context=context,
    )

    assert [field.name for field in fields(ConversationContext)] == [
        "details", "pending_field", "availability_requested", "last_service_name",
        "last_service_code", "last_intent", "last_bot_action",
        "service_selection_prompted", "service_details_requested", "active_domain",
        "active_topic", "active_entity_type", "active_entity_name",
        "last_user_intent", "last_assistant_answer_summary",
        "pending_clarification", "pending_clarification_type",
        "pending_clarification_options", "preferred_language",
        "last_assistant_question", "pending_question_type", "pending_action",
        "pending_entity_type", "pending_entity_name", "pending_created_at",
        "pending_service_code", "pending_slots", "last_answer_source",
        "last_answer_sections", "sales_stage", "selected_location",
        "active_journey", "active_form", "form_status", "form_values",
    ]
    assert context == LegacyConversationContext(_details(), last_service_code="jet_ski_ride")
    assert result == LegacyConversationResult(
        "answer_information", "Approved answer", "approved_service_detail",
        "service_detail", "raipur", "en", False, context=context,
    )
    assert asdict(result)["context"]["last_service_code"] == "jet_ski_ride"
    assert result.response_valid is True and result.response_validation_reason == "safe"


def test_knowledge_provider_returns_the_shared_knowledge_draft_type():
    provider = RaipurKnowledgeProvider(
        object(),
        type("Settings", (), {"raipur_knowledge_min_confidence": 0.65})(),
        embed_query_fn=lambda _question, _settings: [1.0],
        retrieve_candidates_fn=lambda _client, _embedding, _limit: [],
    )

    assert isinstance(provider.answer("approved question"), KnowledgeDraft)
