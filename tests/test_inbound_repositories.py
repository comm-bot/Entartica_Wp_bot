"""Mocked tests for inbound customer, conversation, and message repositories."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from postgrest.base_request_builder import APIResponse, SingleAPIResponse

from app.repositories.conversations import ConversationRepository
from app.repositories.customers import CustomerRepository
from app.repositories.messages import DuplicateMessageError, MessageRepository
from app.schemas.exotel_webhook import NormalizedInboundMessage


def _message() -> NormalizedInboundMessage:
    return NormalizedInboundMessage(
        external_message_id="message-1",
        customer_whatsapp_number="+919000000000",
        business_whatsapp_number="+919000000001",
        message_type="text",
        content="Hello",
        received_at=datetime(2026, 7, 20, tzinfo=UTC),
    )


def test_customer_repository_reuses_existing_customer() -> None:
    """A matching WhatsApp number avoids a second customer insert."""

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.maybe_single.return_value = query
    query.execute.return_value = SingleAPIResponse(data={"id": "customer-1"})
    client = MagicMock()
    client.table.return_value = query

    customer = CustomerRepository(client).get_or_create("+919000000000", None)

    assert customer["id"] == "customer-1"
    query.insert.assert_not_called()


def test_customer_repository_creates_new_customer() -> None:
    """A new WhatsApp number creates the minimum required customer record."""

    select_query = MagicMock()
    select_query.select.return_value = select_query
    select_query.eq.return_value = select_query
    select_query.maybe_single.return_value = select_query
    select_query.execute.return_value = None
    insert_query = MagicMock()
    insert_query.insert.return_value = insert_query
    insert_query.execute.return_value = APIResponse(data=[{"id": "customer-1"}])
    client = MagicMock()
    client.table.side_effect = [select_query, insert_query]

    customer = CustomerRepository(client).get_or_create("+919000000000", "Profile")

    assert customer["id"] == "customer-1"
    insert_query.insert.assert_called_once_with(
        {"whatsapp_number": "+919000000000", "name": "Profile"}
    )


def test_conversation_repository_creates_new_open_conversation() -> None:
    """No open record creates a new bot-mode conversation."""

    select_query = MagicMock()
    select_query.select.return_value = select_query
    select_query.eq.return_value = select_query
    select_query.neq.return_value = select_query
    select_query.is_.return_value = select_query
    select_query.maybe_single.return_value = select_query
    select_query.execute.return_value = None
    insert_query = MagicMock()
    insert_query.insert.return_value = insert_query
    insert_query.execute.return_value = APIResponse(data=[{"id": "conversation-1"}])
    client = MagicMock()
    client.table.side_effect = [select_query, insert_query]

    conversation = ConversationRepository(client).get_or_create_open("customer-1")

    assert conversation["id"] == "conversation-1"
    insert_query.insert.assert_called_once_with(
        {"customer_id": "customer-1", "state": "new", "mode": "bot"}
    )


def test_message_repository_stores_normalized_inbound_message() -> None:
    """Only normalized provider fields are inserted into the messages table."""

    query = MagicMock()
    query.insert.return_value = query
    query.execute.return_value = APIResponse(data=[{"id": "stored-message"}])
    client = MagicMock()
    client.table.return_value = query

    stored = MessageRepository(client).store_inbound(
        _message(), customer_id="customer-1", conversation_id="conversation-1"
    )

    assert stored["id"] == "stored-message"
    record = query.insert.call_args.args[0]
    assert record["direction"] == "inbound"
    assert "raw_payload" not in record


def test_message_repository_reports_duplicate_provider_message() -> None:
    """A PostgreSQL unique violation becomes an idempotency signal."""

    error = RuntimeError("duplicate")
    error.code = "23505"
    query = MagicMock()
    query.insert.return_value = query
    query.execute.side_effect = error
    client = MagicMock()
    client.table.return_value = query

    with pytest.raises(DuplicateMessageError):
        MessageRepository(client).store_inbound(
            _message(), customer_id="customer-1", conversation_id="conversation-1"
        )
