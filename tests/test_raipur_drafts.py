from __future__ import annotations

import pytest

from app.schemas.outbound_drafts import DraftCreateRequest
from app.services.raipur_drafts import RaipurDraftService
from tests.support.fake_outbound_drafts import FakeOutboundDraftRepository


def request(*, inbound_id: str = "inbound-1", content: str = "Approved Raipur draft", valid: bool = True) -> DraftCreateRequest:
    return DraftCreateRequest(
        customer_id="customer-test",
        conversation_id="conversation-test",
        related_inbound_message_id=inbound_id,
        content=content,
        language="hinglish",
        action="booking_enquiry",
        template_key="booking_follow_up",
        human_handover_required=True,
        response_valid=valid,
    )


def create(service: RaipurDraftService, draft_request: DraftCreateRequest, **overrides: bool):
    flags = {
        "inbound_persisted": True,
        "duplicate": False,
        "response_sent": False,
        "draft_saved": False,
    }
    flags.update(overrides)
    return service.create(draft_request, **flags)


def test_feature_flags_prevent_draft_creation() -> None:
    repository = FakeOutboundDraftRepository()
    disabled = RaipurDraftService(repository, enabled=False)
    assert create(disabled, request()).reason == "feature_disabled"
    assert repository.create_attempts == 0

    # The inbound orchestrator feature gate is composed by the caller with the draft gate.
    inbound_orchestrator_enabled = False
    service = RaipurDraftService(repository, enabled=True and inbound_orchestrator_enabled)
    assert create(service, request()).reason == "feature_disabled"
    assert repository.create_attempts == 0


@pytest.mark.parametrize(
    ("draft_request", "flags"),
    [
        (request(), {"inbound_persisted": False}),
        (request(), {"duplicate": True}),
        (request(), {"response_sent": True}),
        (request(), {"draft_saved": True}),
        (request(content="   "), {}),
        (request(valid=False), {}),
    ],
)
def test_ineligible_drafts_are_not_created(draft_request: DraftCreateRequest, flags: dict[str, bool]) -> None:
    repository = FakeOutboundDraftRepository()
    result = create(RaipurDraftService(repository, enabled=True), draft_request, **flags)
    assert result.created is False
    assert result.reason == "draft_not_eligible"
    assert repository.create_attempts == 0


def test_eligible_draft_is_safe_and_idempotent() -> None:
    repository = FakeOutboundDraftRepository()
    service = RaipurDraftService(repository, enabled=True)

    first = create(service, request())
    second = create(service, request())
    drafts = repository.list_drafts()

    assert first.created is True and first.status == "pending_review" and first.reason == "created"
    assert second.created is False and second.status is None and second.reason == "already_pending"
    assert len(drafts) == 1
    assert repository.create_attempts == 2
    assert repository.drafts_created == 1
    assert repository.duplicate_skips == 1
    draft = drafts[0]
    assert draft["draft_status"] == "pending_review"
    assert draft["generated_by"] == "raipur_draft_orchestrator"
    assert draft["draft_metadata"] == {
        "language": "hinglish",
        "action": "booking_enquiry",
        "template_key": "booking_follow_up",
        "human_handover_required": True,
        "response_valid": True,
    }


def test_duplicate_race_and_repository_failure_are_safe() -> None:
    race_repository = FakeOutboundDraftRepository()
    race_repository.simulate_duplicate_race = True
    race_result = create(RaipurDraftService(race_repository, enabled=True), request())
    assert race_result.created is False
    assert race_result.reason == "already_pending"
    assert race_repository.count_drafts_for_inbound_message("inbound-1") == 1

    failed_repository = FakeOutboundDraftRepository()
    failed_repository.raise_next_create = True
    failed_result = create(RaipurDraftService(failed_repository, enabled=True), request())
    assert failed_result.created is False
    assert failed_result.status is None
    assert failed_result.reason == "repository_unavailable"
    assert "RuntimeError" not in failed_result.reason


def test_metadata_excludes_unapproved_or_sensitive_context() -> None:
    repository = FakeOutboundDraftRepository()
    create(RaipurDraftService(repository, enabled=True), request())
    metadata = repository.list_drafts()[0]["draft_metadata"]
    forbidden = {
        "raw_exotel_payload",
        "phone_number",
        "api_key",
        "supabase_credentials",
        "retrieval_chunks",
        "embeddings",
        "provider_error_body",
        "stack_trace",
        "availability_record",
    }
    assert forbidden.isdisjoint(metadata)
    assert set(metadata) == {
        "language",
        "action",
        "template_key",
        "human_handover_required",
        "response_valid",
    }


def test_fake_lifecycle_rules_and_note_safety() -> None:
    repository = FakeOutboundDraftRepository()
    _, created = repository.create_pending_draft(request())
    assert created is True
    draft_id = repository.list_drafts()[0]["id"]

    assert repository.approve_draft(draft_id, "  checked\x00\n by\t reviewer  ") is True
    assert repository.get_draft_by_id(draft_id)["reviewer_note"] == "checked by reviewer"
    assert repository.reject_draft(draft_id, "x" * 600) is True
    rejected = repository.get_draft_by_id(draft_id)
    assert len(rejected["reviewer_note"]) == 500
    assert repository.approve_draft(draft_id) is False

    _, created = repository.create_pending_draft(request(inbound_id="inbound-2"))
    sent_id = repository.list_drafts(status="pending_review")[0]["id"]
    assert repository.mark_sent(sent_id) is False
    assert repository.approve_draft(sent_id) is True
    assert repository.mark_sent(sent_id) is True
    assert repository.reject_draft(sent_id) is False

    _, created = repository.create_pending_draft(request(inbound_id="inbound-3"))
    failed_id = repository.list_drafts(status="pending_review")[0]["id"]
    assert repository.approve_draft(failed_id) is True
    assert repository.mark_failed(failed_id) is True

    _, created = repository.create_pending_draft(request(inbound_id="inbound-4", valid=False))
    invalid_id = repository.list_drafts(status="pending_review")[0]["id"]
    assert repository.approve_draft(invalid_id) is False
    assert repository.approvals == 3
    assert repository.rejections == 1
    assert repository.sent_count == 1
    assert repository.failed_count == 1


def test_fake_listing_count_reset_and_global_safety() -> None:
    repository = FakeOutboundDraftRepository()
    repository.create_pending_draft(request(inbound_id="inbound-1"))
    repository.create_pending_draft(request(inbound_id="inbound-2"))
    assert len(repository.list_drafts(limit=1)) == 1
    assert repository.list_drafts(status="unknown") == []
    assert repository.list_drafts(limit=0) == []
    assert repository.count_drafts_for_inbound_message("inbound-1") == 1
    assert repository.get_draft_by_id("missing") is None
    assert repository.find_draft_for_inbound_message("missing") is None

    assert repository.exotel_called is False
    assert repository.whatsapp_sent is False
    assert repository.openai_called is False
    assert repository.network_calls == 0
    assert repository.database_writes == 0
    assert repository.reservations_created == 0
    assert repository.capacity_changes == 0
    assert repository.payment_actions == 0
    assert repository.final_bookings_confirmed == 0

    repository.reset()
    assert repository.list_drafts() == []
    assert repository.resets == 1
    assert repository.drafts_created == 0
