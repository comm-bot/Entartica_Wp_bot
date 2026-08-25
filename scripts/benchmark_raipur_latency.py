"""Local, no-network latency baseline for safe Raipur response routes.

This intentionally measures only deterministic local routing/formatting.  It
does not construct Supabase, OpenAI, Exotel, or webhook clients.
"""
from __future__ import annotations

import statistics
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.whatsapp_response_formatter import format_whatsapp_response


CASES = (
    ("deterministic_reply", "Hi"), ("deterministic_reply", "Thanks"),
    ("deterministic_reply", "ADDRESS"), ("service_catalogue", "What activities are available?"),
    ("service_overview", "Tell me about Water Bike."), ("exact_topic_section", "How does it work?"),
    ("exact_topic_section", "Is swimming compulsory?"), ("service_overview", "Tell me about Bumper Boat."),
    ("exact_topic_section", "Kitna log aa sakte hain isme?"), ("restricted_handover", "What is the price?"),
    ("general_venue_knowledge", "Tell me about Entartica Raipur."),
    ("openai_general_external_answer", "Explain a general unexpected question."),
)


def _local_route(text: str) -> str:
    value = text.casefold()
    if any(term in value for term in ("price", "booking", "payment")): return "restricted_handover"
    if "entartica raipur" in value: return "general_venue_knowledge"
    if "unexpected" in value: return "openai_general_external_answer"
    if any(term in value for term in ("capacity", "kitna", "swimming", "how does")): return "exact_topic_section"
    if any(term in value for term in ("activities", "rides")): return "service_catalogue"
    if any(term in value for term in ("water bike", "bumper boat")): return "service_overview"
    return "deterministic_reply"


def benchmark(iterations: int = 100) -> dict[str, dict[str, float]]:
    samples: dict[str, list[float]] = {}
    for expected, text in CASES:
        for _ in range(iterations):
            start = perf_counter()
            route = _local_route(text)
            format_whatsapp_response(text="Safe local response.", intent="information", response_mode="grounded_answer", service_code=None, service_display_name=None, topic=None, language="en", requires_handover=False)
            assert route == expected
            samples.setdefault(route, []).append((perf_counter() - start) * 1000)
    return {route: {"min": min(values), "avg": statistics.fmean(values), "median": statistics.median(values), "p95": sorted(values)[max(0, round(len(values) * .95) - 1)], "max": max(values)} for route, values in samples.items()}


if __name__ == "__main__":
    print("mode=local_no_network_benchmark")
    print("external_clients_constructed=false")
    for route, metrics in benchmark().items():
        print("route=%s min_ms=%.3f avg_ms=%.3f median_ms=%.3f p95_ms=%.3f max_ms=%.3f" % (route, metrics["min"], metrics["avg"], metrics["median"], metrics["p95"], metrics["max"]))
