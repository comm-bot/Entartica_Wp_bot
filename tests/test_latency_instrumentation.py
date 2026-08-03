"""Offline regression coverage for safe latency measurement and client reuse."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
from pydantic import SecretStr

from app.integrations.exotel import ExotelClient
from app.rag import retrieval
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService
from app.services.latency import LatencyTrace, latency_stage, use_latency_trace


def test_latency_summary_contains_only_safe_aggregate_fields(caplog) -> None:
    trace = LatencyTrace(request_id="safe-request-id")
    with use_latency_trace(trace), latency_stage("dialogue_planner"), latency_stage("answer_validation"):
        pass
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        trace.summary(intent="location", response_mode="grounded_answer", response_basis="deterministic")
    message = caplog.messages[-1]
    assert "latency_summary" in message and "planner_ms=" in message and "app_total_ms=" in message
    for private in ("+919000000000", "secret", "Authorization"):
        assert private not in message


def test_embedding_http_client_is_reused_without_network(monkeypatch) -> None:
    calls = []

    class Client:
        def post(self, *_args, **_kwargs):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"data": [{"embedding": [0.1, 0.2]}]},
            )

    client = Client()
    retrieval._embedding_http_client.cache_clear()
    monkeypatch.setattr(retrieval.httpx, "Client", lambda **_kwargs: calls.append("created") or client)
    settings = SimpleNamespace(openai_api_key=SecretStr("test-key"), openai_embedding_model="test-model", openai_embedding_dimensions=2)
    assert retrieval.embed_texts(["one"], settings) == [[0.1, 0.2]]
    assert retrieval.embed_texts(["two"], settings) == [[0.1, 0.2]]
    assert calls == ["created"]
    retrieval._embedding_http_client.cache_clear()


def test_exotel_http_client_is_reused_without_a_provider_request() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"response": {"whatsapp": {"messages": [{"code": 202, "status": "success", "data": {"sid": f"sid-{len(requests)}"}}]}}})

    async def run() -> None:
        client = ExotelClient(account_sid="account", api_key="key", api_token="token", whatsapp_from="+919900000000", transport=httpx.MockTransport(handler))
        await client.send_text_message("+919000000000", "test")
        first = client._http_client
        await client.send_text_message("+919000000000", "test")
        assert client._http_client is first
        await client.aclose()

    asyncio.run(run())
    assert len(requests) == 2


def test_deterministic_fast_paths_bypass_knowledge_retrieval() -> None:
    class Knowledge:
        calls = 0
        def answer(self, _question):
            self.calls += 1
            return KnowledgeDraft(None)

    class Drafts:
        def create_outbound_draft(self, **_kwargs): return {}, False

    class Enquiries:
        def create_idempotent(self, record): return record, True

    knowledge = Knowledge()
    service = RaipurConversationService(
        knowledge=knowledge,
        bookings=BookingEnquiryService(Enquiries()),
        drafts=Drafts(),
        persist_drafts=False,
        location={"id": "raipur", "metadata": {"location_name": "Entartica Sea World Raipur", "address_line": "Sector 24", "landmark": "Near MAYFAIR Resort", "maps_url": "https://maps.example/raipur"}},
    )
    customer, conversation = {"id": "customer"}, {"id": "conversation", "location_id": "raipur"}
    for index, text in enumerate(("Hi", "Team ka number do", "Raipur location bhejo", "What is the Jet Ski price?")):
        message = NormalizedInboundMessage(
            external_message_id=f"message-{index}",
            customer_whatsapp_number="+919000000000",
            business_whatsapp_number="+919000000001",
            message_type="text",
            content=text,
            received_at=datetime.now(UTC),
        )
        service.process(message, customer=customer, conversation=conversation, source_message_id=message.external_message_id)
    assert knowledge.calls == 0
