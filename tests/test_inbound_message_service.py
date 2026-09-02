"""Tests for normalized inbound-message persistence."""

from datetime import UTC, datetime
import logging
from unittest.mock import MagicMock

from app.repositories.messages import DuplicateMessageError
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.inbound_messages import InboundMessageService, _log_repository_failure


def _message() -> NormalizedInboundMessage:
    return NormalizedInboundMessage(
        external_message_id="message-1",
        customer_whatsapp_number="+919000000000",
        business_whatsapp_number="+919000000001",
        message_type="text",
        content="Hello",
        received_at=datetime(2026, 7, 20, tzinfo=UTC),
    )


def test_process_reuses_customer_and_open_conversation() -> None:
    """A normalized message uses existing customer and conversation records."""

    service = InboundMessageService(MagicMock())
    service._customers = MagicMock()
    service._conversations = MagicMock()
    service._messages = MagicMock()
    service._customers.get_or_create.return_value = {"id": "customer-1"}
    service._conversations.get_or_create_open.return_value = {"id": "conversation-1"}

    result = service.process(_message())

    assert result.duplicate is False
    service._customers.get_or_create.assert_called_once()
    service._conversations.get_or_create_open.assert_called_once_with("customer-1")
    service._messages.store_inbound.assert_called_once()


def test_process_acknowledges_duplicate_message() -> None:
    """Duplicate provider IDs are treated as already processed."""

    service = InboundMessageService(MagicMock())
    service._customers = MagicMock()
    service._conversations = MagicMock()
    service._messages = MagicMock()
    service._customers.get_or_create.return_value = {"id": "customer-1"}
    service._conversations.get_or_create_open.return_value = {"id": "conversation-1"}
    service._messages.store_inbound.side_effect = DuplicateMessageError()

    assert service.process(_message()).duplicate is True


def test_repository_failure_diagnostic_excludes_personal_data(caplog) -> None:
    """Repository diagnostics include schema context without customer data."""

    error = RuntimeError("database failure for +919000000000")
    error.code = "42703"
    error.message = 'column "messages.received_at" does not exist for John Doe: Hello'

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        _log_repository_failure("message_store_inbound", error)

    diagnostic = caplog.messages[-1]
    assert "operation=message_store_inbound" in diagnostic
    assert "exception_class=RuntimeError" in diagnostic
    assert "database_code=42703" in diagnostic
    assert "database_target=messages.received_at" in diagnostic
    assert "+919000000000" not in diagnostic
    assert "John Doe" not in diagnostic
    assert "Hello" not in diagnostic
