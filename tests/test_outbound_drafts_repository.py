from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.repositories.outbound_drafts import OutboundDraftRepository


@dataclass
class Response:
    data: Any


class FakeQuery:
    def __init__(self, client: "FakeSupabase") -> None:
        self.client = client
        self.filters: list[tuple[str, Any]] = []
        self.single = False
        self.operation = "select"
        self.update_values: dict[str, Any] = {}
        self.order_desc = False
        self.row_limit: int | None = None

    def select(self, _fields: str) -> "FakeQuery":
        return self

    def eq(self, field: str, value: Any) -> "FakeQuery":
        self.filters.append((field, value))
        return self

    def is_(self, field: str, value: str) -> "FakeQuery":
        self.filters.append((field, None if value == "null" else value))
        return self

    def maybe_single(self) -> "FakeQuery":
        self.single = True
        return self

    def order(self, _field: str, *, desc: bool = False) -> "FakeQuery":
        self.order_desc = desc
        return self

    def limit(self, value: int) -> "FakeQuery":
        self.row_limit = value
        return self

    def insert(self, values: dict[str, Any]) -> "FakeQuery":
        self.operation = "insert"
        self.update_values = values
        return self

    def update(self, values: dict[str, Any]) -> "FakeQuery":
        self.operation = "update"
        self.update_values = values
        return self

    def execute(self) -> Response:
        rows = [row for row in self.client.rows if all(row.get(k) == v for k, v in self.filters)]
        if self.operation == "insert":
            row = deepcopy(self.update_values)
            row.setdefault("id", f"draft-{len(self.client.rows) + 1}")
            self.client.rows.append(row)
            return Response([deepcopy(row)])
        if self.operation == "update":
            for row in rows:
                row.update(deepcopy(self.update_values))
            return Response(deepcopy(rows))
        if self.order_desc:
            rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        if self.single:
            return Response(deepcopy(rows[0]) if rows else None)
        return Response(deepcopy(rows))


class FakeSupabase:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = deepcopy(rows)
        self.table_calls = 0

    def table(self, name: str) -> FakeQuery:
        assert name == "messages"
        self.table_calls += 1
        return FakeQuery(self)


def draft(
    draft_id: str,
    status: str = "pending_review",
    *,
    response_valid: bool = True,
    created_at: str = "2026-07-22T00:00:00Z",
) -> dict[str, Any]:
    return {
        "id": draft_id,
        "direction": "outbound",
        "generated_by": "raipur_draft_orchestrator",
        "draft_status": status,
        "related_inbound_message_id": "inbound-1",
        "created_at": created_at,
        "draft_metadata": {"response_valid": response_valid},
    }


def test_get_list_and_count_are_safe_and_newest_first() -> None:
    client = FakeSupabase(
        [
            draft("old", created_at="2026-07-21T00:00:00Z"),
            draft("new", "approved", created_at="2026-07-22T00:00:00Z"),
            {"id": "not-a-draft", "direction": "inbound", "related_inbound_message_id": "inbound-1"},
        ]
    )
    repository = OutboundDraftRepository(client)

    assert repository.get_draft_by_id("new") == client.rows[1]
    assert repository.get_draft_by_id("missing") is None
    assert [row["id"] for row in repository.list_drafts(limit=2)] == ["new", "old"]
    assert [row["id"] for row in repository.list_drafts(status="approved")] == ["new"]
    assert repository.list_drafts(status="unknown") == []
    assert repository.list_drafts(limit=0) == []
    assert repository.list_drafts(limit=101) == []
    assert repository.count_drafts_for_inbound_message("inbound-1") == 2


def test_lifecycle_transitions_and_reviewer_note_normalisation() -> None:
    client = FakeSupabase([draft("pending"), draft("approved", "approved")])
    repository = OutboundDraftRepository(client)

    assert repository.approve_draft("pending", "  reviewed\x00\n by\t team  ") is True
    approved = client.rows[0]
    assert approved["draft_status"] == "approved"
    assert approved["reviewer_note"] == "reviewed by team"
    assert "reviewed_at" in approved

    assert repository.reject_draft("pending", "x" * 600) is True
    rejected = client.rows[0]
    assert rejected["draft_status"] == "rejected"
    assert len(rejected["reviewer_note"]) == 500
    assert repository.approve_draft("pending") is False

    assert repository.reject_draft("approved") is True
    assert client.rows[1]["draft_status"] == "rejected"


def test_send_and_failure_transitions_reject_invalid_paths() -> None:
    client = FakeSupabase(
        [
            draft("pending"),
            draft("approved", "approved"),
            draft("failed", "failed"),
            draft("sent", "sent"),
        ]
    )
    repository = OutboundDraftRepository(client)

    assert repository.mark_sent("pending") is False
    assert repository.mark_sent("approved") is True
    assert client.rows[1]["draft_status"] == "sent"
    assert "sent_at" in client.rows[1]
    assert repository.mark_sent("failed") is False
    assert repository.reject_draft("sent") is False
    assert repository.approve_draft("sent") is False

    client.rows[1]["draft_status"] = "approved"
    assert repository.mark_failed("approved") is True
    assert client.rows[1]["draft_status"] == "failed"


def test_approval_requires_a_response_valid_draft() -> None:
    client = FakeSupabase([draft("invalid", response_valid=False)])
    repository = OutboundDraftRepository(client)

    assert repository.approve_draft("invalid", "not eligible") is False
    assert client.rows[0]["draft_status"] == "pending_review"


def test_claim_completion_rejection_and_reconciliation_require_the_matching_token() -> None:
    client = FakeSupabase([draft("approved", "approved")])
    client.rows[0].update(send_attempt_state="none", sent_at=None, external_message_id=None)
    repository = OutboundDraftRepository(client)

    assert repository.claim_send("approved", "token-one") == "claim_acquired"
    assert client.rows[0]["send_attempt_state"] == "claimed"
    assert client.rows[0]["send_claim_token"] == "token-one"
    assert client.rows[0]["send_claimed_at"]
    assert repository.claim_send("approved", "token-two") == "already_claimed"
    assert repository.complete_send_claim("approved", "wrong", "sid-safe") is False
    assert repository.mark_claim_provider_failed("approved", "wrong") is False
    assert repository.mark_claim_reconciliation_required("approved", "token-one") is True
    assert client.rows[0]["send_attempt_state"] == "reconciliation_required"
    assert client.rows[0]["reconciliation_required_at"]
    assert repository.claim_send("approved", "token-three") == "reconciliation_required"


def test_matching_claim_completion_records_only_accepted_delivery_fields() -> None:
    client = FakeSupabase([draft("approved", "approved")])
    client.rows[0].update(send_attempt_state="none", sent_at=None, external_message_id=None)
    repository = OutboundDraftRepository(client)

    assert repository.claim_send("approved", "token") == "claim_acquired"
    assert repository.complete_send_claim("approved", "token", "sid-safe") is True
    record = client.rows[0]
    assert record["external_message_id"] == "sid-safe"
    assert record["delivery_status"] == "accepted"
    assert record["draft_status"] == "sent"
    assert record["send_attempt_state"] == "completed"
    assert record["sent_at"]
