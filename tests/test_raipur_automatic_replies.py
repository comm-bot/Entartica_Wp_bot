import asyncio
from types import SimpleNamespace

from app.services.raipur_automatic_replies import attempt_automatic_reply, eligible_for_automatic_reply
from app.services.raipur_draft_sender import ApprovedDraftSendResult


def settings(**updates):
    values = dict(exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True,
                  raipur_automatic_reply_enabled=True, raipur_automatic_reply_intents=("information", "location", "services"))
    values.update(updates)
    return SimpleNamespace(**values)


def orchestration(**updates):
    values = dict(action="answer_information", reason_code="approved_knowledge", detected_intent="knowledge",
                  response_valid=True, human_handover_required=False, draft_text="grounded", safe_metadata={"source_filename":"approved.docx", "customer_response_sanitized": True, "response_basis":"active_rag"})
    values.update(updates)
    return SimpleNamespace(**values)


def draft(**updates):
    values = dict(id="draft", draft_status="pending_review", sent_at=None, external_message_id=None)
    values.update(updates)
    return values


class Repo:
    def __init__(self, row): self.row, self.approvals = row, 0
    def approve_draft(self, draft_id):
        if self.row["draft_status"] != "pending_review": return False
        self.approvals += 1; self.row["draft_status"] = "approved"; return True


class Sender:
    def __init__(self, result): self.result, self.calls = result, []
    async def send(self, draft_id, recipient, *, confirmed): self.calls.append((draft_id, recipient, confirmed)); return self.result


def test_disabled_or_invalid_results_remain_pending_review():
    cases = [
        (settings(raipur_automatic_reply_enabled=False), orchestration()),
        (settings(exotel_outbound_enabled=False), orchestration()),
        (settings(), orchestration(response_valid=False)),
        (settings(), orchestration(draft_text="price details")),
        (settings(), orchestration(safe_metadata={"response_basis": "untrusted", "customer_response_sanitized": True})),
    ]
    for configured, result in cases:
        row, repo, sender = draft(), Repo(draft()), Sender(ApprovedDraftSendResult(True, True, True, False, "accepted"))
        outcome = asyncio.run(attempt_automatic_reply(settings=configured, orchestration=result, draft=row, recipient="+910000000000", repository=repo, sender_factory=lambda: sender))
        assert not outcome.eligible and not sender.calls and repo.approvals == 0


def test_information_location_and_services_send_once_with_existing_sender():
    for intent in ("knowledge", "location", "services"):
        row, repo = draft(), Repo(draft())
        sender = Sender(ApprovedDraftSendResult(True, True, True, False, "accepted"))
        outcome = asyncio.run(attempt_automatic_reply(settings=settings(), orchestration=orchestration(detected_intent=intent), draft=row, recipient="+910000000000", repository=repo, sender_factory=lambda: sender))
        assert outcome.attempted and sender.calls == [("draft", "+910000000000", True)] and repo.approvals == 1


def test_raw_safe_intents_map_to_categories_and_greeting_sends_with_mocked_acceptance():
    categories = {
        "greeting": ("greeting", "information"),
        "service_definition": ("generic_service_definition", "information"),
        "service_list": ("structured_service_list", "services"),
        "service_confirmation": ("structured_service_confirmation", "services"),
        "location": ("structured_location", "location"),
    }
    for intent, (reason, category) in categories.items():
        result = orchestration(detected_intent=intent, reason_code=reason, safe_metadata={"customer_response_sanitized": True, "structured_grounding": True})
        assert eligible_for_automatic_reply(settings(), result, draft()) == (True, "eligible")
        row, repo = draft(), Repo(draft())
        sender = Sender(ApprovedDraftSendResult(True, True, True, False, "completed"))
        outcome = asyncio.run(attempt_automatic_reply(settings=settings(), orchestration=result, draft=row, recipient="+910000000000", repository=repo, sender_factory=lambda: sender))
        assert outcome.attempted and outcome.response_sent and sender.calls


def test_unknown_intent_uses_the_safe_final_answer_mode_not_a_silence_gate():
    result = orchestration(
        detected_intent="unknown",
        safe_metadata={"response_basis": "clarification", "customer_response_sanitized": True},
    )
    assert eligible_for_automatic_reply(settings(), result, draft()) == (True, "eligible")
    row, repo = draft(), Repo(draft())
    sender = Sender(ApprovedDraftSendResult(True, True, True, False, "accepted"))
    outcome = asyncio.run(attempt_automatic_reply(settings=settings(), orchestration=result, draft=row, recipient="+910000000000", repository=repo, sender_factory=lambda: sender))
    assert outcome.response_sent and outcome.reason == "clarification_sent"


def test_restricted_intent_uses_controlled_handover_instead_of_silence():
    result = orchestration(
        detected_intent="pricing",
        human_handover_required=True,
        draft_text="Our team will help with the quotation.",
        safe_metadata={"response_basis": "restricted_handover", "customer_response_sanitized": True},
    )
    assert eligible_for_automatic_reply(settings(), result, draft()) == (True, "eligible")
    row, repo = draft(), Repo(draft())
    sender = Sender(ApprovedDraftSendResult(True, True, True, False, "accepted"))
    outcome = asyncio.run(attempt_automatic_reply(settings=settings(), orchestration=result, draft=row, recipient="+910000000000", repository=repo, sender_factory=lambda: sender))
    assert outcome.response_sent and outcome.reason == "human_handover_sent"


def test_unsanitized_draft_remains_ineligible():
    assert eligible_for_automatic_reply(settings(), orchestration(detected_intent="greeting", reason_code="greeting", safe_metadata={"structured_grounding": True}), draft())[0] is False


def test_only_explicitly_approved_pontoon_package_bypasses_commercial_word_scan():
    text = "Offer price. Pay token. Full Refund terms."
    approved = orchestration(
        detected_intent="service_overview", draft_text=text,
        safe_metadata={
            "response_basis": "active_rag", "customer_response_sanitized": True,
            "answer_source": "pontoon_package_boundary", "service_code": "pontoon_celebration",
            "approved_package": True, "source_filename": "approved-pontoon-config",
        },
    )
    assert eligible_for_automatic_reply(settings(), approved, draft()) == (True, "eligible")

    for changed in (
        {"approved_package": False},
        {"service_code": "party_boat_celebration"},
        {"answer_source": "generated_answer"},
    ):
        metadata = {**approved.safe_metadata, **changed}
        assert eligible_for_automatic_reply(settings(), orchestration(draft_text=text, safe_metadata=metadata), draft()) == (False, "ineligible_content")


def test_superseded_coimbatore_standard_package_no_longer_gets_commercial_exception():
    text = "Rack price ₹5,999. Token payment ₹1,000. Full refund terms."
    metadata = {
        "response_basis": "deterministic", "customer_response_sanitized": True,
        "structured_grounding": True, "approved_standard_package": True,
        "package_id": "coimbatore_pontoon_standard", "selected_location": "coimbatore",
        "service_code": "pontoon_celebration",
    }
    approved = orchestration(draft_text=text, safe_metadata=metadata)
    assert eligible_for_automatic_reply(settings(), approved, draft()) == (False, "ineligible_content")
    for changed in (
        {"approved_standard_package": False}, {"package_id": "other"},
        {"selected_location": "raipur"}, {"service_code": "other"},
    ):
        rejected = orchestration(draft_text=text, safe_metadata={**metadata, **changed})
        assert eligible_for_automatic_reply(settings(), rejected, draft()) == (False, "ineligible_content")


def test_only_trusted_coimbatore_deterministic_reply_bypasses_legacy_commercial_scan():
    metadata = {
        "active_location": "coimbatore", "active_service": "pontoon_celebration",
        "coimbatore_pontoon_mvp": True, "answer_source": "structured_grounding",
        "response_basis": "deterministic", "structured_grounding": True,
        "customer_response_sanitized": True,
    }
    result = orchestration(detected_intent="greeting", draft_text="Ask about price or booking.", safe_metadata=metadata)
    assert eligible_for_automatic_reply(settings(), result, draft()) == (True, "eligible")
    for changed in ({"active_location": "raipur"}, {"structured_grounding": False}, {"answer_source": "generated"}):
        rejected = orchestration(detected_intent="greeting", draft_text="Ask about price or booking.", safe_metadata={**metadata, **changed})
        assert eligible_for_automatic_reply(settings(), rejected, draft()) == (False, "ineligible_content")


def test_only_approved_test_mode_razorpay_response_bypasses_payment_word_scan():
    metadata = {
        "approved_coimbatore_payment_response":True,
        "package_id":"coimbatore_pontoon_standard", "payment_provider":"razorpay",
        "razorpay_mode":"test", "service_code":"pontoon_celebration",
        "response_basis":"deterministic", "structured_grounding":True,
        "customer_response_sanitized":True,
    }
    result = orchestration(detected_intent="booking", draft_text="Secure test payment link is ready.",
                           safe_metadata=metadata)
    assert eligible_for_automatic_reply(settings(), result, draft()) == (True, "eligible")
    for changed in ({"razorpay_mode":"live"}, {"payment_provider":"other"},
                    {"package_id":"other"}, {"structured_grounding":False}):
        rejected = orchestration(detected_intent="booking", draft_text="Secure payment link is ready.",
                                 safe_metadata={**metadata, **changed})
        assert eligible_for_automatic_reply(settings(), rejected, draft()) == (False, "ineligible_content")


def test_response_basis_validation_allows_safe_greeting_but_fails_closed_otherwise():
    greeting = orchestration(detected_intent="greeting", reason_code="greeting", safe_metadata={"response_basis":"deterministic", "customer_response_sanitized":True})
    assert eligible_for_automatic_reply(settings(), greeting, draft()) == (True, "eligible")
    missing_sanitization = orchestration(detected_intent="greeting", reason_code="greeting", safe_metadata={"response_basis":"deterministic"})
    assert eligible_for_automatic_reply(settings(), missing_sanitization, draft()) == (False, "ungrounded_response")
    rag_missing_source = orchestration(safe_metadata={"response_basis":"active_rag", "customer_response_sanitized":True})
    assert eligible_for_automatic_reply(settings(), rag_missing_source, draft()) == (False, "ungrounded_response")
    rag_with_source = orchestration(safe_metadata={"response_basis":"active_rag", "source_filename":"approved.md", "customer_response_sanitized":True})
    assert eligible_for_automatic_reply(settings(), rag_with_source, draft()) == (True, "eligible")
    unknown = orchestration(detected_intent="greeting", reason_code="greeting", safe_metadata={"response_basis":"untrusted", "customer_response_sanitized":True})
    assert eligible_for_automatic_reply(settings(), unknown, draft()) == (False, "response_mode_unavailable")


def test_duplicate_and_provider_failure_do_not_retry_or_send_twice():
    row, repo = draft(), Repo(draft())
    failure = Sender(ApprovedDraftSendResult(True, False, False, False, "provider_failure"))
    first = asyncio.run(attempt_automatic_reply(settings=settings(), orchestration=orchestration(), draft=row, recipient="+910000000000", repository=repo, sender_factory=lambda: failure))
    second = asyncio.run(attempt_automatic_reply(settings=settings(), orchestration=orchestration(), draft=row, recipient="+910000000000", repository=repo, sender_factory=lambda: failure))
    assert first.reason == "provider_failure" and not second.eligible and len(failure.calls) == 1


def test_final_response_modes_map_to_meaningful_sent_reasons():
    cases = [
        (orchestration(), "grounded_answer", "grounded_answer_sent"),
        (orchestration(safe_metadata={"response_basis": "clarification", "customer_response_sanitized": True}), "clarification_question", "clarification_sent"),
        (orchestration(safe_metadata={"response_basis": "deterministic", "approved_safe_fallback": True, "customer_response_sanitized": True}), "approved_safe_fallback", "safe_fallback_sent"),
        (orchestration(human_handover_required=True, safe_metadata={"response_basis": "restricted_handover", "customer_response_sanitized": True}), "human_handover", "human_handover_sent"),
    ]
    for result, mode, sent_reason in cases:
        row, repo = draft(), Repo(draft())
        sender = Sender(ApprovedDraftSendResult(True, True, True, False, "accepted"))
        outcome = asyncio.run(attempt_automatic_reply(settings=settings(), orchestration=result, draft=row, recipient="+910000000000", repository=repo, sender_factory=lambda: sender))
        assert outcome.response_mode == mode
        assert outcome.response_sent and outcome.reason == sent_reason


def test_participation_eligibility_maps_to_information_and_sends_grounded_answer():
    result = orchestration(
        detected_intent="participation_eligibility",
        safe_metadata={
            "response_basis": "active_rag",
            "source_filename": "jet_ski_ride.md",
            "customer_response_sanitized": True,
            "approved_active_exact_service": True,
            "retrieval_service_code": "jet_ski_ride",
        },
    )
    assert eligible_for_automatic_reply(settings(), result, draft()) == (True, "eligible")
    row, repo = draft(), Repo(draft())
    sender = Sender(ApprovedDraftSendResult(True, True, True, False, "accepted"))
    outcome = asyncio.run(attempt_automatic_reply(settings=settings(), orchestration=result, draft=row, recipient="+910000000000", repository=repo, sender_factory=lambda: sender))
    assert outcome.response_sent and outcome.response_mode == "grounded_answer"
