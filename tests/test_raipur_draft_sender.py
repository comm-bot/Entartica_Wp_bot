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
    def __init__(self, result=None, error: Exception | None = None, image_error: Exception | None = None):
        self.result = result or ExotelAcceptedMessage(provider_message_id="sid-safe")
        self.error = error
        self.image_error = image_error
        self.calls: list[tuple] = []
        self.call_types: list[str] = []

    async def send_text_message(self, *args):
        self.call_types.append("text")
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result

    async def send_interactive_message(self, *args):
        self.call_types.append("interactive")
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result

    async def send_image_message(self, *args):
        self.call_types.append("image")
        self.calls.append(args)
        if self.image_error is not None:
            raise self.image_error
        if self.error is not None:
            raise self.error
        return self.result

    async def send_video_message(self, *args):
        self.call_types.append("video")
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result

    async def send_document_message(self, *args):
        self.call_types.append("document")
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result

    async def send_template_message(self, *args):
        self.call_types.append("template")
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


def test_production_sender_accepts_any_normalized_customer_recipient():
    repository, exotel = Repo(row()), Exotel()
    configured = settings(app_env="production", raipur_outbound_test_recipients=())
    result = asyncio.run(
        RaipurDraftSender(repository, configured, exotel).send(
            "draft-1", "+919876543210", confirmed=True,
        )
    )
    assert result.attempted and result.accepted and result.sid_recorded
    assert exotel.calls[0][0] == "+919876543210"


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


def test_approved_interactive_draft_uses_the_same_claimed_send_path():
    interactive = {
        "kind": "list", "body": "Approved options", "fallback_text": "Approved options",
        "button_label": "Choose Celebration", "options": [
            {"id": "celebration_floating_gazebo", "title": "Floating Gazebo", "description": None}
        ], "flow_id": None, "flow_token": None, "flow_cta": None, "flow_type": None,
    }
    repository, exotel = Repo(row(draft_metadata={"response_valid": True, "interactive_message": interactive})), Exotel()
    result = _send(repository, exotel)
    assert result.reason == "completed" and len(exotel.calls) == 1
    assert exotel.calls[0][1].kind == "list"
    assert exotel.calls[0][1].options[0].id == "celebration_floating_gazebo"


def test_customer_details_flow_keeps_published_id_token_and_screen_through_durable_sender():
    interactive = {
        "kind": "flow",
        "body": "Hi 👋 Welcome to Entartica Coimbatore!",
        "fallback_text": "Please tap Complete Details to continue.",
        "button_label": "Complete Details",
        "options": [],
        "flow_id": "27532617159750529",
        "flow_token": "secure-random-token-from-inbound-conversation",
        "flow_cta": "Complete Details",
        "flow_screen_id": "CUSTOMER_DETAILS",
        "flow_type": "customer_details",
    }
    repository = Repo(row(draft_metadata={
        "response_valid": True,
        "interactive_message": interactive,
    }))
    exotel = Exotel()

    result = _send(repository, exotel)

    assert result.reason == "completed"
    assert exotel.call_types == ["interactive"]
    sent_to, sent_flow = exotel.calls[0][0], exotel.calls[0][1]
    assert sent_to == "+910000000000"
    assert sent_flow.flow_id == "27532617159750529"
    assert sent_flow.flow_token == "secure-random-token-from-inbound-conversation"
    assert sent_flow.flow_screen_id == "CUSTOMER_DETAILS"
    assert sent_flow.flow_type == "customer_details"


def test_approved_document_draft_uses_claimed_send_path():
    document = {"type":"document", "url":"https://signed.example/confirmation.pdf",
                "caption":"Booking confirmed", "filename":"Entartica-CBE-1.pdf"}
    repository = Repo(row(draft_metadata={"response_valid":True, "document_message":document}))
    exotel = Exotel()
    result = _send(repository, exotel)
    assert result.reason == "completed" and exotel.call_types == ["document"]
    assert exotel.calls[0][1:4] == (document["url"], document["caption"], document["filename"])


def test_approved_image_draft_sends_image_then_qualification_text_under_one_claim():
    media = {"type": "image", "url": "https://example.test/pontoon.jpg", "caption": "Approved package"}
    repository = Repo(row(content="What date and how many persons?", draft_metadata={"response_valid": True, "media_message": media}))
    exotel = Exotel()
    result = _send(repository, exotel)

    assert result.reason == "completed"
    assert exotel.call_types == ["image", "text"]
    assert exotel.calls[0][1:3] == (media["url"], media["caption"])
    assert exotel.calls[1][1] == "What date and how many persons?"
    assert repository.row["send_attempt_state"] == "completed"


def test_approved_pontoon_bundle_sends_image_then_flow_under_one_claim():
    media = {"type": "image", "url": "https://example.test/pontoon.jpg", "caption": "Approved package"}
    interactive = {
        "kind": "flow", "body": "Pontoon Celebration Details", "fallback_text": "Share date and persons",
        "button_label": "Share Celebration Details", "options": [], "flow_id": "configured-flow-id",
        "flow_token": "entartica_pontoon_celebration", "flow_cta": "Share Celebration Details",
        "flow_type": "pontoon_celebration",
    }
    repository = Repo(row(content="What date and how many persons?", draft_metadata={
        "response_valid": True, "media_message": media, "interactive_message": interactive,
    }))
    exotel = Exotel()
    assert _send(repository, exotel).reason == "completed"
    assert exotel.call_types == ["image", "interactive"]
    assert exotel.calls[1][1].flow_type == "pontoon_celebration"


def test_coimbatore_package_sequence_sends_full_image_caption_before_four_action_list():
    media = {"type":"image", "url":"https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/pontoon_boat_celebration_Coimbtore.jpg",
             "caption":"Pontoon Boat Celebration Package ✨\nEvent Date: 21 Aug 2026\nGuests: 5\n₹5,999\n₹4,999\n₹1,000"}
    interactive = {"kind":"list", "body":media["caption"], "fallback_text":media["caption"],
                   "button_label":"Package Actions", "options":[
                       {"id":"book", "title":"Book Now"}, {"id":"question", "title":"Ask a Question"},
                       {"id":"customize", "title":"Customize"}, {"id":"photos", "title":"See More Photos"},
                   ], "header_image_url":media["url"]}
    repository = Repo(row(content=media["caption"], draft_metadata={"response_valid":True,
        "package_id":"coimbatore_pontoon_standard", "package_presentation_pending":True,
        "media_message":media, "interactive_message":interactive}))
    exotel = Exotel()
    result = _send(repository, exotel)
    assert result.reason == "completed"
    assert exotel.call_types == ["interactive"]
    assert "Pontoon Boat Celebration Package" in exotel.calls[0][1].body
    assert exotel.calls[0][1].header_image_url == media["url"]
    assert len(exotel.calls[0][1].options) == 4


def test_approved_pontoon_template_uses_exactly_one_provider_request():
    template = {
        "name": "approved_pontoon_template", "language": "en",
        "header_image_url": "https://example.test/pontoon.jpg", "flow_id": "approved-flow",
        "flow_cta": "Share Event Details", "service_code": "pontoon_celebration",
        "package_source_file": "active/services/pontoon_celebration.md", "approved_package": True,
    }
    repository = Repo(row(content="Approved KB package", draft_metadata={
        "response_valid": True, "template_message": template,
    }))
    exotel = Exotel()
    assert _send(repository, exotel).reason == "completed"
    assert exotel.call_types == ["template"]
    assert exotel.calls[0][1].name == "approved_pontoon_template"


def test_media_sequence_sends_one_interactive_cta_only_after_all_media():
    media_sequence = [
        {"type":"image", "url":"https://example.test/one.jpg", "caption":"Photo one"},
        {"type":"image", "url":"https://example.test/two.jpg", "caption":"Photo two"},
        {"type":"video", "url":"https://example.test/video-one.mp4", "caption":"Video one"},
        {"type":"video", "url":"https://example.test/video-two.mp4", "caption":"Video two"},
    ]
    interactive = {
        "kind":"buttons", "body":"Ready to make it yours?", "fallback_text":"Ready to make it yours?",
        "button_label":"Choose an option", "options":[
            {"id":"coimbatore_pontoon_book_standard", "title":"Book Now"},
            {"id":"coimbatore_pontoon_customize", "title":"Customize"},
            {"id":"coimbatore_pontoon_talk_sales", "title":"Talk to Sales Person"},
        ],
    }
    repository = Repo(row(draft_metadata={
        "response_valid":True, "package_id":"coimbatore_pontoon_standard",
        "media_sequence":media_sequence, "interactive_message":interactive,
    }))
    exotel = Exotel()

    result = _send(repository, exotel)

    assert result.reason == "completed"
    assert exotel.call_types == ["image", "image", "video", "video", "interactive"]
    assert exotel.call_types.count("interactive") == 1
    assert [option.title for option in exotel.calls[-1][1].options] == ["Book Now", "Customize", "Talk to Sales Person"]
    assert _send(repository, exotel).reason == "duplicate_send_prevented"
    assert exotel.call_types == ["image", "image", "video", "video", "interactive"]


@pytest.mark.parametrize(
    "error,expected_state,expected_reason",
    [
        (ExotelValidationError(), "provider_failed", "provider_rejected"),
        (ExotelTimeoutError(), "reconciliation_required", "reconciliation_required"),
    ],
)
def test_template_provider_failures_preserve_existing_claim_safety(error, expected_state, expected_reason):
    template = {
        "name": "approved_pontoon_template", "language": "en",
        "header_image_url": "https://example.test/pontoon.jpg", "flow_id": "approved-flow",
        "flow_cta": "Share Event Details", "service_code": "pontoon_celebration",
        "package_source_file": "active/services/pontoon_celebration.md", "approved_package": True,
    }
    repository = Repo(row(content="Approved KB package", draft_metadata={
        "response_valid": True, "template_message": template,
    }))
    exotel = Exotel(error=error)
    assert _send(repository, exotel).reason == expected_reason
    assert repository.row["send_attempt_state"] == expected_state
    assert _send(repository, exotel).reason == "duplicate_send_prevented"
    assert exotel.call_types == ["template"]


def test_definite_image_rejection_falls_back_to_caption_then_qualification_text():
    media = {"type": "image", "url": "https://example.test/pontoon.jpg", "caption": "Approved package"}
    repository = Repo(row(content="What date?", draft_metadata={"response_valid": True, "media_message": media}))
    exotel = Exotel(image_error=ExotelValidationError())
    result = _send(repository, exotel)

    assert result.reason == "completed"
    assert exotel.call_types == ["image", "text", "text"]
    assert [call[1] for call in exotel.calls[1:]] == ["Approved package", "What date?"]


def test_failure_after_image_acceptance_requires_reconciliation_and_prevents_resend():
    class PartialExotel(Exotel):
        async def send_text_message(self, *args):
            self.call_types.append("text")
            self.calls.append(args)
            raise ExotelValidationError()

    media = {"type": "image", "url": "https://example.test/pontoon.jpg", "caption": "Approved package"}
    repository = Repo(row(content="What date?", draft_metadata={"response_valid": True, "media_message": media}))
    exotel = PartialExotel()
    assert _send(repository, exotel).reason == "reconciliation_required"
    assert _send(repository, exotel).reason == "duplicate_send_prevented"
    assert exotel.call_types == ["image", "text"]


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
