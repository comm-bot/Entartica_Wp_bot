"""In-memory draft repository for tests; it never accesses external services."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
import threading
from typing import Any

from app.schemas.outbound_drafts import DraftCreateRequest


_STATUSES = {"pending_review", "approved", "rejected", "sent", "failed"}


def _reviewer_note(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return " ".join(value.split())[:500] or None


@dataclass
class FakeDraftCounters:
    create_attempts: int = 0
    drafts_created: int = 0
    duplicate_skips: int = 0
    approvals: int = 0
    rejections: int = 0
    sent_count: int = 0
    failed_count: int = 0
    resets: int = 0


class FakeOutboundDraftRepository:
    """Small behavioural fake matching the repository's public draft interface."""

    def __init__(self) -> None:
        self._drafts: list[dict[str, Any]] = []
        self._sequence = 0
        self._lock = threading.Lock()
        self.counters = FakeDraftCounters()
        self.fail_next_create = False
        self.raise_next_create = False
        self.simulate_duplicate_race = False
        # Explicitly external-operation counters; in-memory changes are not database writes.
        self.exotel_called = False
        self.whatsapp_sent = False
        self.openai_called = False
        self.network_calls = 0
        self.database_writes = 0
        self.reservations_created = 0
        self.capacity_changes = 0
        self.payment_actions = 0
        self.final_bookings_confirmed = 0

    @property
    def create_attempts(self) -> int:
        return self.counters.create_attempts

    @property
    def drafts_created(self) -> int:
        return self.counters.drafts_created

    @property
    def duplicate_skips(self) -> int:
        return self.counters.duplicate_skips

    @property
    def approvals(self) -> int:
        return self.counters.approvals

    @property
    def rejections(self) -> int:
        return self.counters.rejections

    @property
    def sent_count(self) -> int:
        return self.counters.sent_count

    @property
    def failed_count(self) -> int:
        return self.counters.failed_count

    @property
    def resets(self) -> int:
        return self.counters.resets

    def create_pending_draft(self, request: DraftCreateRequest) -> tuple[dict[str, Any], bool]:
        self.counters.create_attempts += 1
        existing = self.find_draft_for_inbound_message(request.related_inbound_message_id)
        if existing is not None:
            self.counters.duplicate_skips += 1
            return existing, False
        if self.raise_next_create:
            self.raise_next_create = False
            raise RuntimeError("simulated repository failure")
        if self.fail_next_create:
            self.fail_next_create = False
            return {}, False
        if self.simulate_duplicate_race:
            self.simulate_duplicate_race = False
            self._drafts.append(self._record(request))
            self.counters.drafts_created += 1
            self.counters.duplicate_skips += 1
            return self.find_draft_for_inbound_message(request.related_inbound_message_id) or {}, False

        record = self._record(request)
        self._drafts.append(record)
        self.counters.drafts_created += 1
        return deepcopy(record), True

    def find_draft_for_inbound_message(self, inbound_id: str) -> dict[str, Any] | None:
        for draft in self._drafts:
            if (
                draft["related_inbound_message_id"] == inbound_id
                and draft["generated_by"] == "raipur_draft_orchestrator"
                and draft["draft_status"] == "pending_review"
            ):
                return deepcopy(draft)
        return None

    def get_draft_by_id(self, draft_id: str) -> dict[str, Any] | None:
        for draft in self._drafts:
            if draft["id"] == draft_id and draft["direction"] == "outbound":
                return deepcopy(draft)
        return None

    def list_drafts(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100 or status is not None and status not in _STATUSES:
            return []
        drafts = [
            draft
            for draft in self._drafts
            if draft["direction"] == "outbound" and draft["generated_by"] == "raipur_draft_orchestrator"
            and (status is None or draft["draft_status"] == status)
        ]
        return deepcopy(sorted(drafts, key=lambda draft: draft["created_sequence"], reverse=True)[:limit])

    def approve_draft(self, draft_id: str, reviewer_note: str | None = None) -> bool:
        return self._transition(draft_id, {"pending_review"}, "approved", reviewer_note)

    def reject_draft(self, draft_id: str, reviewer_note: str | None = None) -> bool:
        return self._transition(draft_id, {"pending_review", "approved"}, "rejected", reviewer_note)

    def mark_sent(self, draft_id: str) -> bool:
        return self._transition(draft_id, {"approved"}, "sent")

    def mark_failed(self, draft_id: str) -> bool:
        return self._transition(draft_id, {"approved"}, "failed")

    def count_drafts_for_inbound_message(self, inbound_id: str) -> int:
        return sum(
            draft["related_inbound_message_id"] == inbound_id
            and draft["generated_by"] == "raipur_draft_orchestrator"
            for draft in self._drafts
        )

    def claim_send(self, draft_id: str, claim_token: str) -> str:
        with self._lock:
            draft = next((row for row in self._drafts if row["id"] == draft_id), None)
            if draft is None or draft.get("draft_status") != "approved": return "ineligible"
            if draft.get("send_attempt_state") == "reconciliation_required": return "reconciliation_required"
            if draft.get("sent_at") or draft.get("external_message_id") or draft.get("draft_status") == "sent": return "already_sent"
            if draft.get("send_attempt_state") == "claimed": return "already_claimed"
            draft["send_attempt_state"] = "claimed"; draft["send_claim_token"] = claim_token
            return "claim_acquired"

    def complete_send_claim(self, draft_id: str, claim_token: str, provider_sid: str) -> bool:
        with self._lock:
            draft = next((row for row in self._drafts if row["id"] == draft_id), None)
            if not draft or draft.get("send_claim_token") != claim_token or draft.get("send_attempt_state") != "claimed": return False
            draft.update(external_provider="exotel", external_message_id=provider_sid, delivery_status="accepted", draft_status="sent", sent_at="fake-now", send_attempt_state="completed")
            return True

    def mark_claim_reconciliation_required(self, draft_id: str, claim_token: str) -> bool:
        with self._lock:
            draft = next((row for row in self._drafts if row["id"] == draft_id), None)
            if not draft or draft.get("send_claim_token") != claim_token: return False
            draft["send_attempt_state"] = "reconciliation_required"; draft["reconciliation_required_at"] = "fake-now"; return True

    def mark_claim_provider_failed(self, draft_id: str, claim_token: str) -> bool:
        with self._lock:
            draft = next((row for row in self._drafts if row["id"] == draft_id), None)
            if not draft or draft.get("send_claim_token") != claim_token or draft.get("send_attempt_state") != "claimed":
                return False
            draft["send_attempt_state"] = "provider_failed"
            return True

    def reset(self) -> None:
        self._drafts.clear()
        self._sequence = 0
        resets = self.counters.resets + 1
        self.counters = FakeDraftCounters(resets=resets)

    def _record(self, request: DraftCreateRequest) -> dict[str, Any]:
        self._sequence += 1
        return {
            "id": f"fake-draft-{self._sequence}",
            "customer_id": request.customer_id,
            "conversation_id": request.conversation_id,
            "related_inbound_message_id": request.related_inbound_message_id,
            "direction": "outbound",
            "message_type": "text",
            "content": request.content,
            "delivery_status": None,
            "draft_status": "pending_review",
            "send_attempt_state": "none",
            "generated_by": "raipur_draft_orchestrator",
            "created_sequence": self._sequence,
            "draft_metadata": {
                "language": request.language,
                "action": request.action,
                "template_key": request.template_key,
                "human_handover_required": request.human_handover_required,
                "response_valid": request.response_valid,
            },
        }

    def _transition(
        self, draft_id: str, allowed_from: set[str], target: str, reviewer_note: str | None = None
    ) -> bool:
        for draft in self._drafts:
            if draft["id"] != draft_id or draft["draft_status"] not in allowed_from:
                continue
            if target == "approved" and not draft["draft_metadata"]["response_valid"]:
                return False
            draft["draft_status"] = target
            if target in {"approved", "rejected"}:
                draft["reviewer_note"] = _reviewer_note(reviewer_note)
                if target == "approved":
                    self.counters.approvals += 1
                else:
                    self.counters.rejections += 1
            elif target == "sent":
                self.counters.sent_count += 1
            elif target == "failed":
                self.counters.failed_count += 1
            return True
        return False
