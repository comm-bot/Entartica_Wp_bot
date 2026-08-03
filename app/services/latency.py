"""Safe per-message latency instrumentation with no customer data."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import logging
from time import perf_counter
from typing import Iterator
from uuid import uuid4


logger = logging.getLogger("uvicorn.error")
_trace: ContextVar["LatencyTrace | None"] = ContextVar("latency_trace", default=None)


@dataclass
class LatencyTrace:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: float = field(default_factory=perf_counter)
    stages_ms: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = perf_counter()
        try:
            yield
        finally:
            self.stages_ms[name] = self.stages_ms.get(name, 0.0) + (perf_counter() - start) * 1000

    def total_ms(self) -> float:
        return (perf_counter() - self.started_at) * 1000

    def value(self, name: str) -> int:
        return round(self.stages_ms.get(name, 0.0))

    def summary(self, *, intent: object = None, response_mode: object = None, response_basis: object = None) -> None:
        logger.info(
            "latency_summary request_id=%s intent=%s response_mode=%s response_basis=%s "
            "webhook_received_ms=%s payload_validation_ms=%s duplicate_check_ms=%s customer_lookup_ms=%s "
            "conversation_load_ms=%s planner_ms=%s deterministic_routing_ms=%s embedding_ms=%s retrieval_ms=%s "
            "reranking_ms=%s generation_ms=%s validation_ms=%s retry_generation_ms=%s persistence_ms=%s "
            "automatic_reply_eligibility_ms=%s exotel_ms=%s app_total_ms=%s",
            self.request_id,
            intent if isinstance(intent, str) else "unknown",
            response_mode if isinstance(response_mode, str) else "unknown",
            response_basis if isinstance(response_basis, str) else "unknown",
            self.value("webhook_received"),
            self.value("payload_validation"),
            self.value("duplicate_check"),
            self.value("customer_lookup"),
            self.value("conversation_load"),
            self.value("dialogue_planner"),
            self.value("deterministic_routing"),
            self.value("query_embedding"),
            self.value("Supabase_vector_search"),
            self.value("knowledge_reranking"),
            self.value("OpenAI_answer_generation"),
            self.value("answer_validation"),
            self.value("retry_generation"),
            round(self.stages_ms.get("draft_or_message_persistence", 0.0) + self.stages_ms.get("customer_lookup", 0.0) + self.stages_ms.get("conversation_load", 0.0)),
            self.value("automatic_reply_eligibility"),
            self.value("Exotel_outbound_api"),
            round(self.total_ms()),
        )


@contextmanager
def use_latency_trace(trace: LatencyTrace) -> Iterator[LatencyTrace]:
    token: Token[LatencyTrace | None] = _trace.set(trace)
    try:
        yield trace
    finally:
        _trace.reset(token)


@contextmanager
def latency_stage(name: str) -> Iterator[None]:
    trace = _trace.get()
    if trace is None:
        yield
        return
    with trace.stage(name):
        yield


def current_latency_trace() -> LatencyTrace | None:
    return _trace.get()
