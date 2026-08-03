from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.integrations.exotel import (
    ExotelAcceptedMessage,
    ExotelConnectionError,
    ExotelTimeoutError,
    ExotelValidationError,
)
from app.services.raipur_draft_sender import RaipurDraftSender


class Repo:
    """Thread-safe in-memory claim fake; it does not access Supabase."""

    def __init__(self, initial: dict):
        self.row = deepcopy(initial)
        self._lock = threading.Lock()
        self.complete_returns = True

    def get_draft_by_id(self, _draft_id: str):
        with self._lock:
            return deepcopy(self.row)

    def claim_send(self, _draft_id: str, token: str) -> str:
        with self._lock:
            state = self.row.get("send_attempt_state", "none")
            if self.row.get("draft_status") == "sent" or self.row.get("sent_at") or self.row.get("external_message_id"):
                return "already_sent"
            if state == "reconciliation_required":
                return "reconciliation_required"
            if state == "provider_failed":
                return "provider_failed"
            if state != "none":
                return "already_claimed"
            self.row.update(send_attempt_state="claimed", send_claim_token=token, send_claimed_at="fake-now")
            return "claim_acquired"

    def complete_send_claim(self, _draft_id: str, token: str, sid: str) -> bool:
        with self._lock:
            if not self.complete_returns or self.row.get("send_claim_token") != token or self.row.get("send_attempt_state") != "claimed":
                return False
            self.row.update(
                external_provider="exotel",
                external_message_id=sid,
                delivery_status="accepted",
                draft_status="sent",
                sent_at="fake-now",
                send_attempt_state="completed",
            )
            return True

    def mark_claim_reconciliation_required(self, _draft_id: str, token: str) -> bool:
        with self._lock:
            if self.row.get("send_claim_token") != token or self.row.get("send_attempt_state") != "claimed":
                return False
            self.row.update(send_attempt_state="reconciliation_required", reconciliation_required_at="fake-now")
            return True

    def mark_claim_provider_failed(self, _draft_id: str, token: str) -> bool:
        with self._lock:
            if self.row.get("send_claim_token") != token or self.row.get("send_attempt_state") != "claimed":
                return False
            self.row["send_attempt_state"] = "provider_failed"
            return True


class Exotel:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result or ExotelAcceptedMessage(provider_message_id="sid-safe")
        self.error = error
        self.calls: list[tuple] = []

    async def send_text_message(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


def settings(**updates):
    values = dict(
        exotel_outbound_enabled=True,
        raipur_approved_draft_send_enabled=True,
        raipur_outbound_test_recipients=("+910000000000",),
        exotel_status_callback_url="https://example.test/status",
    )
    values.update(updates)
    return SimpleNamespace(**values)


def row(**updates):
    values = dict(
        draft_status="approved",
        sent_at=None,
        external_message_id=None,
        content="approved text",
        draft_metadata={"response_valid": True},
        send_attempt_state="none",
    )
    values.update(updates)
    return values


def _send(repository: Repo, exotel: Exotel):
    return asyncio.run(RaipurDraftSender(repository, settings(), exotel).send("draft-1", "+910000000000", confirmed=True))


def test_sender_gates_and_local_validation_never_call_provider():
    for configured in (settings(exotel_outbound_enabled=False), settings(raipur_approved_draft_send_enabled=False), settings(raipur_outbound_test_recipients=())):
        exotel = Exotel()
        result = asyncio.run(RaipurDraftSender(Repo(row()), configured, exotel).send("draft-1", "+910000000000", confirmed=True))
        assert not result.attempted and not exotel.calls
    assert not asyncio.run(RaipurDraftSender(Repo(row()), settings(), Exotel()).send("draft-1", "+910000000000", confirmed=False)).attempted
    for bad in (row(draft_status="pending_review"), row(content=" "), row(draft_metadata={"response_valid": False})):
        exotel = Exotel()
        result = _send(Repo(bad), exotel)
        assert result.reason == "local_validation_failure" and not result.attempted and not exotel.calls


def test_accepted_response_completes_matching_claim_without_regenerating_text():
    repository, exotel = Repo(row()), Exotel()
    result = _send(repository, exotel)

    assert result.reason == "completed"
    assert result.attempted and result.accepted and result.sid_recorded
    assert exotel.calls[0][1] == "approved text"
    assert repository.row["send_attempt_state"] == "completed"
    assert repository.row["draft_status"] == "sent"
    assert repository.row["delivery_status"] == "accepted"
    assert repository.row["sent_at"] == "fake-now"


@pytest.mark.parametrize("error", [ExotelValidationError(), __import__("app.integrations.exotel", fromlist=["ExotelAuthenticationError"]).ExotelAuthenticationError()])
def test_definite_rejections_are_provider_failed_and_never_retried(error):
    repository, exotel = Repo(row()), Exotel(error=error)
    result = _send(repository, exotel)

    assert result.reason == "provider_rejected" and result.attempted
    assert repository.row["send_attempt_state"] == "provider_failed"
    assert repository.row["external_message_id"] is None and repository.row["sent_at"] is None
    second = _send(repository, exotel)
    assert second.reason == "duplicate_send_prevented" and not second.attempted and len(exotel.calls) == 1


@pytest.mark.parametrize("error", [ExotelTimeoutError(), ExotelConnectionError()])
def test_ambiguous_transport_outcomes_require_durable_reconciliation(error):
    repository, exotel = Repo(row()), Exotel(error=error)
    result = _send(repository, exotel)

    assert result.reason == "reconciliation_required"
    assert result.attempted and not result.accepted and not result.sid_recorded and not result.duplicate_prevented
    assert repository.row["send_attempt_state"] == "reconciliation_required"
    assert repository.row["reconciliation_required_at"] == "fake-now"
    assert repository.row["send_claim_token"]
    second = _send(repository, exotel)
    assert second.reason == "duplicate_send_prevented" and second.duplicate_prevented and not second.attempted
    assert len(exotel.calls) == 1


def test_success_without_sid_or_completion_persistence_requires_reconciliation():
    class NoSid:
        async def send_text_message(self, *_args):
            raise __import__("app.integrations.exotel", fromlist=["ExotelProviderResponseError"]).ExotelProviderResponseError()

    repository = Repo(row())
    assert _send(repository, NoSid()).reason == "reconciliation_required"
    assert repository.row["send_attempt_state"] == "reconciliation_required"

    repository, exotel = Repo(row()), Exotel()
    repository.complete_returns = False
    assert _send(repository, exotel).reason == "reconciliation_required"
    assert repository.row["send_attempt_state"] == "reconciliation_required"


def test_concurrent_attempts_make_exactly_one_provider_request():
    repository, exotel = Repo(row()), Exotel()
    sender_one = RaipurDraftSender(repository, settings(), exotel)
    sender_two = RaipurDraftSender(repository, settings(), exotel)

    async def run_both():
        return await asyncio.gather(
            sender_one.send("draft-1", "+910000000000", confirmed=True),
            sender_two.send("draft-1", "+910000000000", confirmed=True),
        )

    results = asyncio.run(run_both())
    assert len(exotel.calls) == 1
    assert sorted(result.reason for result in results) == ["completed", "duplicate_send_prevented"]
