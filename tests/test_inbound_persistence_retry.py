from types import SimpleNamespace

import httpx
import pytest

from app.services.inbound_persistence_retry import (
    process_inbound_with_retry,
    run_with_transient_retry,
)
from app.services.inbound_messages import InboundMessageResult


def test_transient_supabase_disconnect_is_retried_once_with_same_message():
    message = SimpleNamespace(external_message_id="message-1")

    class Service:
        calls = []

        def process(self, received):
            self.calls.append(received)
            if len(self.calls) == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return "persisted"

    service = Service()
    assert process_inbound_with_retry(service, message) == "persisted"
    assert service.calls == [message, message]


def test_transient_supabase_disconnect_is_retried_only_once():
    class Service:
        calls = 0

        def process(self, _message):
            self.calls += 1
            raise httpx.RemoteProtocolError("Server disconnected")

    service = Service()
    with pytest.raises(httpx.RemoteProtocolError):
        process_inbound_with_retry(service, object())
    assert service.calls == 2


def test_duplicate_after_transient_insert_is_marked_for_safe_orchestration_recovery():
    message = SimpleNamespace(external_message_id="message-1")

    class Service:
        calls = 0

        def process(self, _message):
            self.calls += 1
            if self.calls == 1:
                raise httpx.RemoteProtocolError("response lost after insert")
            return InboundMessageResult(
                duplicate=True,
                customer={"id": "customer-1"},
                conversation={"id": "conversation-1"},
            )

    result = process_inbound_with_retry(Service(), message)

    assert result.duplicate is True
    assert result.recovered_after_transient_duplicate is True


def test_postgrest_future_jwt_error_is_retried_once():
    class FutureJwtError(Exception):
        code = "PGRST303"
        message = "JWT issued at future"

    attempts = []

    def operation():
        attempts.append(True)
        if len(attempts) == 1:
            raise FutureJwtError()
        return "recovered"

    assert run_with_transient_retry(operation, operation_name="customer_lookup") == "recovered"
    assert len(attempts) == 2


def test_business_failure_is_not_retried():
    class Service:
        calls = 0

        def process(self, _message):
            self.calls += 1
            raise ValueError("invalid inbound")

    service = Service()
    with pytest.raises(ValueError, match="invalid inbound"):
        process_inbound_with_retry(service, object())
    assert service.calls == 1


def test_customer_details_token_operation_recovers_from_first_disconnect():
    attempts = []

    def issue_token():
        attempts.append(True)
        if len(attempts) == 1:
            raise httpx.RemoteProtocolError("Server disconnected")
        return "flow-token"

    assert run_with_transient_retry(
        issue_token,
        operation_name="customer_details_flow_token",
    ) == "flow-token"
    assert len(attempts) == 2
