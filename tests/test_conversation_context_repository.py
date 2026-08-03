"""Unit tests for customer-isolated durable service-context persistence."""

from types import SimpleNamespace

from app.repositories.conversations import ConversationRepository


class _Query:
    def __init__(self, client, action):
        self.client, self.action, self.filters, self.payload = client, action, [], None

    def select(self, _): return self
    def update(self, payload): self.payload = payload; return self
    def eq(self, field, value): self.filters.append((field, value)); return self
    def maybe_single(self): return self
    def execute(self):
        self.client.calls.append((self.action, self.filters, self.payload))
        return SimpleNamespace(data=self.client.data)


class _Client:
    def __init__(self, data): self.data, self.calls = data, []
    def table(self, name): assert name == "conversations"; return _Query(self, "table")


def test_context_read_and_write_are_scoped_to_exact_customer_and_conversation():
    context = {"service_code": "jet_ski", "service_name": "Jet Ski", "updated_at": "2026-07-27T00:00:00+00:00"}
    client = _Client({"customer_id": "customer-a", "service_context": context})
    repository = ConversationRepository(client)

    assert repository.get_service_context("conversation-a", "customer-a") == context
    assert repository.save_service_context("conversation-a", "customer-a", context)
    for _, filters, _ in client.calls:
        assert ("id", "conversation-a") in filters
        assert ("customer_id", "customer-a") in filters


def test_context_row_for_another_customer_is_never_returned():
    client = _Client({"customer_id": "customer-b", "service_context": {"last_matched_service_name": "Jet Ski"}})

    assert ConversationRepository(client).get_service_context("conversation-a", "customer-a") is None
