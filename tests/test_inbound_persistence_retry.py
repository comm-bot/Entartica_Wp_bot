from types import SimpleNamespace

import httpx
import pytest

from app.services.inbound_persistence_retry import process_inbound_with_retry


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
