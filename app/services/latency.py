"""Safe per-turn latency instrumentation and dedicated JSONL persistence."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Iterator
from uuid import uuid4


logger = logging.getLogger("uvicorn.error")
latency_logger = logging.getLogger("entartica.latency")
_trace: ContextVar["LatencyTrace | None"] = ContextVar("latency_trace", default=None)
_sink_lock = Lock()
_STAGE_EVENTS = {
    "customer_understanding": "customer_understanding",
    "exact_section_lookup": "knowledge_retrieval",
    "Supabase_vector_search": "knowledge_retrieval",
    "query_embedding": "embedding",
    "sales_response_composer": "sales_composer",
    "sales_agent": "sales_agent",
    "conversational_fallback": "conversational_fallback",
    "answer_validation": "validation",
}


def configure_latency_logging(path: str | Path = "logs/raipur-latency.log") -> Path:
    """Configure one promptly flushed, application-owned safe JSONL sink."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _sink_lock:
        existing = next((handler for handler in latency_logger.handlers if getattr(handler, "baseFilename", None) == str(target)), None)
        if existing is None:
            for handler in tuple(latency_logger.handlers):
                handler.close()
                latency_logger.removeHandler(handler)
            handler = logging.FileHandler(target, mode="a", encoding="utf-8", delay=False)
            handler.setFormatter(logging.Formatter("%(message)s"))
            latency_logger.addHandler(handler)
        latency_logger.setLevel(logging.INFO)
        latency_logger.propagate = False
    return target


@dataclass
class LatencyTrace:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: float = field(default_factory=perf_counter)
    stages_ms: dict[str, float] = field(default_factory=dict)
    marks: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=lambda: {"supabase_reads": 0, "supabase_writes": 0, "logical_openai_calls": 0, "embedding_calls": 0})
    attributes: dict[str, object] = field(default_factory=dict)

    @property
    def trace_id(self) -> str:
        return self.request_id

    def event(self, event: str, **safe_fields: object) -> None:
        payload = {"event": event, "trace_id": self.trace_id, "elapsed_ms": round(self.total_ms(), 3)}
        payload.update({key: value for key, value in safe_fields.items() if value is not None})
        latency_logger.info(json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True))

    def mark(self, name: str, *, event: str | None = None, **safe_fields: object) -> None:
        self.marks[name] = perf_counter()
        if event:
            self.event(event, **safe_fields)

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = perf_counter()
        event_name = _STAGE_EVENTS.get(name)
        if event_name:
            self.event(f"{event_name}_start")
        try:
            yield
        finally:
            duration = (perf_counter() - start) * 1000
            self.stages_ms[name] = self.stages_ms.get(name, 0.0) + duration
            if name in {
                "session_state_load", "deterministic_pending_field_resolution", "qualification",
                "LLM_understanding", "date_parse", "guest_parse", "state_update",
                "package_selection", "exact_KB_package_lookup", "YAML_load", "package_render",
                "add_on_render", "media_build", "interactive_action_build", "draft_creation",
                "automatic_reply_eligibility", "draft_approval", "outbound_claim",
                "Exotel_request_prepare", "Exotel_HTTP_request", "package_state_commit",
                "total_orchestration",
            }:
                logger.info(
                    "coimbatore_stage_latency trace_id=%s stage=%s duration_ms=%.3f",
                    self.trace_id, name, duration,
                )
            if event_name:
                self.event(f"{event_name}_complete", duration_ms=round(duration, 3))

    def total_ms(self) -> float:
        return (perf_counter() - self.started_at) * 1000

    def value(self, name: str) -> int:
        return round(self.stages_ms.get(name, 0.0))

    def combined_value(self, *names: str) -> int:
        return round(sum(self.stages_ms.get(name, 0.0) for name in names))

    def summary(self, *, intent: object = None, response_mode: object = None, response_basis: object = None,
                route: object = None, location_code: object = "raipur", service_code: object = None,
                topic: object = None, answer_source: object = None, cache_hit: object = False,
                conversation_id: object = None) -> None:
        """Persist one safe summary with non-overlapping top-level accounting."""
        def safe(value: object, fallback: str = "none") -> str:
            return value if isinstance(value, str) and value else fallback
        def stage(*names: str) -> int:
            return round(sum(self.stages_ms.get(name, 0.0) for name in names))
        exotel_complete = self.marks.get("exotel_request_complete")
        total = round((exotel_complete - self.started_at) * 1000) if exotel_complete else round(self.total_ms())
        reply_ready = self.marks.get("reply_ready")
        exotel_start = self.marks.get("exotel_request_start")
        post_generation = round(max(0.0, (exotel_start - reply_ready) * 1000)) if reply_ready and exotel_start else 0
        top_level = (
            stage("background_task_start_delay") + stage("customer_lock_wait") + stage("customer_lookup")
            + stage("conversation_load") + stage("inbound_message_persistence") + stage("orchestrator_initialization") + stage("total_orchestration")
            + post_generation + stage("Exotel_outbound_api")
        )
        accounted = min(total, top_level)
        payload = {
            "event": "chatbot_latency_summary", "trace_id": self.trace_id,
            "route": safe(route), "intent": safe(intent, "unknown"), "location_code": safe(location_code, "raipur"),
            "service_code": safe(service_code), "topic": safe(topic), "answer_source": safe(answer_source),
            "total_ms": total, "background_start_delay_ms": stage("background_task_start_delay"),
            "customer_lock_wait_ms": stage("customer_lock_wait"), "customer_lookup_ms": stage("customer_lookup"),
            "conversation_lookup_ms": stage("conversation_load"), "inbound_persistence_ms": stage("inbound_message_persistence"),
            "orchestrator_initialization_ms": stage("orchestrator_initialization"),
            "context_load_ms": stage("context_resolution"), "routing_ms": stage("total_orchestration"),
            "customer_understanding_ms": stage("customer_understanding"),
            "knowledge_retrieval_ms": stage("exact_section_lookup", "Supabase_vector_search"),
            "embedding_ms": stage("query_embedding"), "sales_composer_ms": stage("sales_response_composer"),
            "sales_agent_ms": stage("sales_agent"),
            "conversational_fallback_ms": stage("conversational_fallback"), "validation_ms": stage("answer_validation"),
            "context_save_ms": stage("context_save"),
            "reply_ready_ms": round((reply_ready - self.started_at) * 1000) if reply_ready else 0,
            "draft_creation_ms": stage("draft_creation"), "draft_approval_ms": stage("draft_approval"),
            "send_claim_ms": stage("outbound_claim"), "reply_ready_to_exotel_start_ms": post_generation,
            "exotel_http_ms": stage("Exotel_outbound_api"), "send_completion_persistence_ms": stage("send_completion_persistence"),
            "supabase_reads": self.counters.get("supabase_reads", 0), "supabase_writes": self.counters.get("supabase_writes", 0),
            "supabase_round_trips": self.counters.get("supabase_reads", 0) + self.counters.get("supabase_writes", 0),
            "logical_openai_calls": self.counters.get("logical_openai_calls", 0), "embedding_calls": self.counters.get("embedding_calls", 0),
            "knowledge_cache_hit": bool(cache_hit or self.attributes.get("knowledge_cache_hit", False)),
            "vector_cache_hit": bool(self.attributes.get("vector_cache_hit", False)),
            "location_cache_hit": bool(self.attributes.get("location_cache_hit", False)),
            "accounted_ms": accounted, "unaccounted_ms": max(0, total - accounted),
        }
        latency_logger.info(json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
        logger.info("chatbot_latency_summary trace_id=%s route=%s total_ms=%s accounted_ms=%s unaccounted_ms=%s", self.trace_id, payload["route"], total, accounted, payload["unaccounted_ms"])


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


def latency_counter(name: str, amount: int = 1) -> None:
    trace = current_latency_trace()
    if trace is not None:
        trace.increment(name, amount)


def latency_attribute(name: str, value: object) -> None:
    trace = current_latency_trace()
    if trace is not None:
        trace.set_attribute(name, value)


@contextmanager
def latency_openai_call(call_type: str, model: str, *, embedding: bool = False) -> Iterator[None]:
    """Observe one logical OpenAI call without prompts, outputs, or credentials."""
    trace = current_latency_trace()
    if trace is None:
        yield
        return
    trace.increment("embedding_calls" if embedding else "logical_openai_calls")
    start = perf_counter()
    trace.event("openai_call_start", call_type=call_type, model=model)
    try:
        yield
    except Exception:
        trace.event("openai_call_complete", call_type=call_type, model=model, duration_ms=round((perf_counter() - start) * 1000, 3), success=False, retry_count="unavailable")
        raise
    else:
        trace.event("openai_call_complete", call_type=call_type, model=model, duration_ms=round((perf_counter() - start) * 1000, 3), success=True, retry_count="unavailable")
