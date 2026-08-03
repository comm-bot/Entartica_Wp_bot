"""Draft-only data access; no method in this module sends a message."""

from __future__ import annotations

import re
import logging
from datetime import UTC, datetime
from typing import Any

from app.schemas.outbound_drafts import DraftCreateRequest


_DRAFT_STATUSES = {"pending_review", "approved", "rejected", "sent", "failed"}
logger = logging.getLogger("uvicorn.error")


def _response_row(response: object) -> dict[str, Any] | None:
    """Return one safe response row without assuming a PostgREST shape."""
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _normalise_reviewer_note(value: str | None) -> str | None:
    if value is None:
        return None
    without_controls = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    normalised = " ".join(without_controls.split())
    return normalised[:500] or None


class OutboundDraftRepository:
    def __init__(self, client: Any):
        self._client = client

    def find_draft_for_inbound_message(self, inbound_id: str) -> dict[str, Any] | None:
        try:
            response = (
                self._client.table("messages")
                .select("*")
                .eq("related_inbound_message_id", inbound_id)
                .eq("generated_by", "raipur_draft_orchestrator")
                .eq("draft_status", "pending_review")
                .maybe_single()
                .execute()
            )
            return _response_row(response)
        except Exception:
            return None

    def create_pending_draft(self, request: DraftCreateRequest) -> tuple[dict[str, Any], bool]:
        existing = self.find_draft_for_inbound_message(request.related_inbound_message_id)
        if existing:
            return existing, False
        record = {
            "customer_id": request.customer_id,
            "conversation_id": request.conversation_id,
            "related_inbound_message_id": request.related_inbound_message_id,
            "direction": "outbound",
            "message_type": "text",
            "content": request.content,
            # Draft lifecycle is represented by `draft_status`; this is not an outbound delivery.
            "delivery_status": None,
            "draft_status": "pending_review",
            "generated_by": "raipur_draft_orchestrator",
            "draft_metadata": {
                "language": request.language,
                "action": request.action,
                "template_key": request.template_key,
                "human_handover_required": request.human_handover_required,
                "response_valid": request.response_valid,
            },
        }
        try:
            response = self._client.table("messages").insert(record).execute()
            return _response_row(response) or {}, True
        except Exception as error:
            logger.error("outbound_draft_create_failed_safe exception_class=%s database_code=%s", type(error).__name__, getattr(error, "code", None))
            return self.find_draft_for_inbound_message(request.related_inbound_message_id) or {}, False

    def get_draft_by_id(self, draft_id: str) -> dict[str, Any] | None:
        try:
            response = (
                self._client.table("messages")
                .select("*")
                .eq("id", draft_id)
                .eq("direction", "outbound")
                .maybe_single()
                .execute()
            )
            return _response_row(response)
        except Exception:
            return None

    def list_drafts(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100 or status is not None and status not in _DRAFT_STATUSES:
            return []
        try:
            query = (
                self._client.table("messages")
                .select("*")
                .eq("direction", "outbound")
                .eq("generated_by", "raipur_draft_orchestrator")
            )
            if status is not None:
                query = query.eq("draft_status", status)
            response = query.order("created_at", desc=True).limit(limit).execute()
            data = getattr(response, "data", None)
            return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
        except Exception:
            return []

    def approve_draft(self, draft_id: str, reviewer_note: str | None = None) -> bool:
        return self._transition(draft_id, {"pending_review"}, "approved", reviewer_note)

    def reject_draft(self, draft_id: str, reviewer_note: str | None = None) -> bool:
        return self._transition(draft_id, {"pending_review", "approved"}, "rejected", reviewer_note)

    def mark_sent(self, draft_id: str) -> bool:
        return self._transition(draft_id, {"approved"}, "sent")

    def mark_failed(self, draft_id: str) -> bool:
        return self._transition(draft_id, {"approved"}, "failed")

    def count_drafts_for_inbound_message(self, inbound_id: str) -> int:
        try:
            response = (
                self._client.table("messages")
                .select("id")
                .eq("related_inbound_message_id", inbound_id)
                .eq("generated_by", "raipur_draft_orchestrator")
                .execute()
            )
            data = getattr(response, "data", None)
            return len(data) if isinstance(data, list) else 0
        except Exception:
            return 0

    def claim_send(self, draft_id: str, claim_token: str) -> str:
        """Atomically acquire the only active provider-send claim for this draft."""
        try:
            now = datetime.now(UTC).isoformat()
            response = (self._client.table("messages").update({"send_claim_token": claim_token, "send_claimed_at": now, "send_attempt_state": "claimed"})
                .eq("id", draft_id).eq("draft_status", "approved").is_("sent_at", "null")
                .is_("external_message_id", "null").eq("send_attempt_state", "none").execute())
            if _response_row(response) is not None:
                return "claim_acquired"
            draft = self.get_draft_by_id(draft_id) or {}
            if draft.get("send_attempt_state") == "reconciliation_required":
                return "reconciliation_required"
            if draft.get("draft_status") == "sent" or draft.get("sent_at") or draft.get("external_message_id"):
                return "already_sent"
            if draft.get("send_attempt_state") == "provider_failed":
                return "provider_failed"
            return "already_claimed"
        except Exception:
            return "ineligible"

    def complete_send_claim(self, draft_id: str, claim_token: str, provider_sid: str) -> bool:
        try:
            response = (self._client.table("messages").update({"external_provider":"exotel","external_message_id":provider_sid,"delivery_status":"accepted","draft_status":"sent","sent_at":datetime.now(UTC).isoformat(),"send_attempt_state":"completed"})
                .eq("id",draft_id).eq("send_claim_token",claim_token).eq("send_attempt_state","claimed").execute())
            return _response_row(response) is not None
        except Exception:return False

    def mark_claim_reconciliation_required(self, draft_id: str, claim_token: str) -> bool:
        try:
            response=self._client.table("messages").update({"send_attempt_state":"reconciliation_required","reconciliation_required_at":datetime.now(UTC).isoformat()}).eq("id",draft_id).eq("send_claim_token",claim_token).eq("send_attempt_state","claimed").execute()
            return _response_row(response) is not None
        except Exception:return False

    def mark_claim_provider_failed(self, draft_id: str, claim_token: str) -> bool:
        """Record a definite provider rejection without inventing a delivery SID."""
        try:
            response = (self._client.table("messages").update({"send_attempt_state": "provider_failed"})
                .eq("id", draft_id).eq("send_claim_token", claim_token).eq("send_attempt_state", "claimed").execute())
            return _response_row(response) is not None
        except Exception:
            return False

    def _transition(
        self,
        draft_id: str,
        allowed_from: set[str],
        target_status: str,
        reviewer_note: str | None = None,
    ) -> bool:
        draft = self.get_draft_by_id(draft_id)
        if draft is None or draft.get("draft_status") not in allowed_from:
            return False
        if target_status == "approved" and not bool((draft.get("draft_metadata") or {}).get("response_valid")):
            return False

        update: dict[str, Any] = {"draft_status": target_status}
        now = datetime.now(UTC).isoformat()
        if target_status in {"approved", "rejected"}:
            update["reviewed_at"] = now
            if reviewer_note is not None:
                update["reviewer_note"] = _normalise_reviewer_note(reviewer_note)
        elif target_status == "sent":
            update["sent_at"] = now

        try:
            response = (
                self._client.table("messages")
                .update(update)
                .eq("id", draft_id)
                .eq("draft_status", draft["draft_status"])
                .execute()
            )
            return _response_row(response) is not None
        except Exception:
            return False
