"""Tests for observed Exotel DLR normalization and idempotent transitions."""

from datetime import UTC, datetime

import pytest

from app.integrations.exotel import normalize_delivery_callbacks
from app.schemas.exotel_status import NormalizedDeliveryStatus
from app.services.delivery_status import DeliveryStatusService


class _Messages:
    def __init__(self, status: str = "accepted") -> None:
        self.record = {"id": "message-1", "delivery_status": status, "accepted_at": None}
        self.updated: list[dict] = []

    def find_outbound_by_provider_sid(self, value: str):
        return self.record

    def find_outbound_by_id(self, value: str):
        return self.record

    def update_delivery_status(self, message_id: str, fields: dict) -> None:
        self.updated.append(fields)
        self.record.update(fields)


def _service(status: str = "accepted") -> tuple[DeliveryStatusService, _Messages]:
    service = DeliveryStatusService(object())
    messages = _Messages(status)
    service._messages = messages
    return service, messages


@pytest.mark.parametrize(
    ("code", "status"),
    [("30001", "sent"), ("30002", "delivered"), ("30003", "read"), ("30004", "failed")],
)
def test_normalizes_observed_dlr_codes(code: str, status: str) -> None:
    """Observed callback envelope maps Exotel codes to normalized statuses."""

    callbacks = normalize_delivery_callbacks(
        {"whatsapp": {"messages": [{"callback_type": "dlr", "message_sid": "sid", "exo_status_code": code, "timestamp": "2026-07-20T10:00:00Z"}]}}
    )

    assert callbacks[0].status == status


def test_delivery_callback_requires_provider_sid() -> None:
    """Custom data alone cannot select an outbound message."""

    service, messages = _service()
    callback = NormalizedDeliveryStatus(internal_message_id="message-1", status="sent")

    assert service.process(callback) is False
    assert messages.record["delivery_status"] == "accepted"


def test_duplicate_and_out_of_order_callbacks_do_not_regress() -> None:
    """Delivered/read lifecycle states are terminal for later lower callbacks."""

    service, messages = _service("delivered")

    assert service.process(NormalizedDeliveryStatus(provider_message_id="sid", status="sent")) is False
    assert service.process(NormalizedDeliveryStatus(provider_message_id="sid", status="delivered")) is False
    assert messages.updated == []


def test_read_callback_updates_delivered_message() -> None:
    """Read advances delivery without changing recipient or message data."""

    service, messages = _service("delivered")
    callback = NormalizedDeliveryStatus(
        provider_message_id="sid", status="read", occurred_at=datetime(2026, 7, 20, tzinfo=UTC)
    )

    assert service.process(callback) is True
    assert messages.record["delivery_status"] == "read"
    assert "read_at" in messages.updated[0]


def test_failed_callback_is_recorded_before_delivery() -> None:
    """Failed DLRs retain only safe provider failure metadata."""

    service, messages = _service("sent")

    assert service.process(
        NormalizedDeliveryStatus(provider_message_id="sid", status="failed", failure_code="30004")
    ) is True
    assert messages.record["delivery_status"] == "failed"
    assert messages.record["failure_code"] == "30004"


def test_unknown_status_and_unsupported_callback_are_acknowledged_without_update() -> None:
    """Unsupported Exotel data cannot crash or mutate a message."""

    assert normalize_delivery_callbacks({"whatsapp": {"messages": [{"callback_type": "other"}]}}) == []
    service, messages = _service()
    assert service.process(NormalizedDeliveryStatus(provider_message_id="sid")) is False
    assert messages.updated == []
