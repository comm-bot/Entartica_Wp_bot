# Raipur Chatbot Latency Report

## Baseline

Prior live observations were 5–7 seconds for exact topics and 10–14 seconds
for service overviews. They are observations, not measured production evidence.
The accompanying benchmark is explicitly local and no-network.

Local baseline/final benchmark (`100` iterations per request, measured after
the cache/instrumentation change): deterministic median/p95 `0.008/0.014 ms`,
exact-topic `0.011/0.013 ms`, service overview `0.013/0.016 ms`, catalogue
`0.013/0.021 ms`, and restricted handover `0.006/0.006 ms`. There is no valid
pre-change local comparison, so this report does not claim a live improvement.

## Timing by Processing Stage

`chatbot_latency_summary` now emits the requested safe millisecond fields:
webhook acknowledgement, lock wait, lookup/context/routing, exact-section,
embedding/vector/OpenAI, safety/formatting/persistence/draft/outbound and total.

## Root Causes

Exact approved sections were already checked before embedding/vector retrieval,
but were read from Supabase for every eligible request. External Supabase and
OpenAI stages remain the likely dominant cost for non-deterministic routes.

## Optimizations Applied

- Canonical safe structured timing event.
- Five-minute in-process cache for active, approved, customer-facing Raipur
  exact service sections only. Pricing, availability, booking and customer data
  are not cached.
- Exact section lookup continues to precede embeddings, vector search and OpenAI.

## Files Changed

- `app/services/latency.py`
- `app/api/exotel_webhook.py`
- `app/services/raipur_inbound_orchestrator.py`
- `app/rag/raipur_knowledge_provider.py`
- `scripts/benchmark_raipur_latency.py`
- `tests/test_raipur_knowledge_provider.py`

## Before-and-After Results

The previous 5–7 second exact-topic and 10–14 second overview observations
were not collected using the new timing event, so an honest numerical before /
after comparison is unavailable. The final local benchmark records only local
routing and formatting. Live comparison requires the controlled staging steps
below.

## Route-Level Results

The local benchmark covers deterministic reply, general venue knowledge,
service overview, exact topic section, restricted handover, and the
OpenAI/general external-answer route. It deliberately does not invoke external
providers, so provider latency is excluded by design.

## External Provider Time

Not measured in this change. The local benchmark does not call Supabase,
OpenAI, Exotel or WhatsApp; it cannot establish live latency improvement.

## Tests

Focused latency/knowledge/webhook routing tests and the complete suite pass.
The cache test proves an approved exact-topic cache hit produces no embedding.

## Remaining Bottlenecks

Service-overview and general-knowledge paths may still require Supabase vector
search and OpenAI composition. Their real contribution will be visible in the
new structured timing event after a controlled, approved staging test.

## Final Assessment

The critical fast paths are locally timed and preserve their existing safety,
location-isolation, ordering and durable-send behaviour. A controlled live
measurement remains required before making customer-visible latency claims.

## Production Recommendations

Run the manual staging sequence after deployment/restart and record sent/reply
timestamps: `Hi`, `ADDRESS`, `Tell me about Bumper Boat.`, `kitna log aa sakte
hain isme?`, `How long does it last?`, `What is the price?`, `Thanks`.
