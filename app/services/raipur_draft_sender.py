"""Explicit-only approved-draft sender; approval itself never calls this service."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from app.integrations.exotel import (
    ExotelAmbiguousOutcomeError,
    ExotelClient,
    ExotelDefiniteRejectionError,
    ExotelOutboundError,
)
from app.services.latency import latency_stage

@dataclass(frozen=True)
class ApprovedDraftSendResult:
 attempted:bool;accepted:bool;sid_recorded:bool;duplicate_prevented:bool;reason:str

class RaipurDraftSender:
    def __init__(self, repository: Any, settings: Any, exotel: ExotelClient):
        self._repo, self._settings, self._exotel = repository, settings, exotel

    async def send(self, draft_id: str, to: str, *, confirmed: bool) -> ApprovedDraftSendResult:
        if not confirmed:
            return ApprovedDraftSendResult(False, False, False, False, "confirmation_required")
        if not self._settings.exotel_outbound_enabled or not self._settings.raipur_approved_draft_send_enabled:
            return ApprovedDraftSendResult(False, False, False, False, "send_feature_disabled")
        if to not in self._settings.raipur_outbound_test_recipients:
            return ApprovedDraftSendResult(False, False, False, False, "recipient_not_allowlisted")

        draft = self._repo.get_draft_by_id(draft_id)
        metadata = draft.get("draft_metadata") if isinstance(draft, dict) and isinstance(draft.get("draft_metadata"), dict) else {}
        if not isinstance(draft, dict) or draft.get("draft_status") == "sent" or draft.get("sent_at") or draft.get("external_message_id"):
            return ApprovedDraftSendResult(False, False, False, True, "duplicate_send_prevented")
        if draft.get("send_attempt_state") in {"claimed", "provider_failed", "reconciliation_required"}:
            return ApprovedDraftSendResult(False, False, False, True, "duplicate_send_prevented")
        if draft.get("draft_status") != "approved" or not metadata.get("response_valid") or not isinstance(draft.get("content"), str) or not draft["content"].strip():
            return ApprovedDraftSendResult(False, False, False, False, "local_validation_failure")

        claim_token = secrets.token_urlsafe(24)
        claim = self._repo.claim_send(draft_id, claim_token)
        if claim in {"already_claimed", "already_sent", "provider_failed", "reconciliation_required"}:
            return ApprovedDraftSendResult(False, False, False, True, "duplicate_send_prevented")
        if claim != "claim_acquired":
            return ApprovedDraftSendResult(False, False, False, False, "local_validation_failure")

        try:
            with latency_stage("Exotel_outbound_api"):
                accepted = await self._exotel.send_text_message(
                    to, draft["content"], self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}"
                )
        except ExotelDefiniteRejectionError:
            self._repo.mark_claim_provider_failed(draft_id, claim_token)
            return ApprovedDraftSendResult(True, False, False, False, "provider_rejected")
        except (ExotelAmbiguousOutcomeError, ExotelOutboundError):
            self._repo.mark_claim_reconciliation_required(draft_id, claim_token)
            return ApprovedDraftSendResult(True, False, False, False, "reconciliation_required")
        except Exception:
            # An unknown post-claim error is treated conservatively: Exotel may have accepted.
            self._repo.mark_claim_reconciliation_required(draft_id, claim_token)
            return ApprovedDraftSendResult(True, False, False, False, "reconciliation_required")

        if self._repo.complete_send_claim(draft_id, claim_token, accepted.provider_message_id):
            return ApprovedDraftSendResult(True, True, True, False, "completed")

        self._repo.mark_claim_reconciliation_required(draft_id, claim_token)
        return ApprovedDraftSendResult(True, False, False, False, "reconciliation_required")
