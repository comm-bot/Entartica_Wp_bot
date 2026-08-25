# Entartica WhatsApp Chatbot — Codex Handover

## 1. Executive Summary

Raipur is the active chatbot location in configuration. The repository contains a FastAPI/Exotel/Supabase/OpenAI/LangGraph chatbot with approved-document retrieval, deterministic safety routing, persisted conversation context, draft-first outbound delivery, and a currently uncommitted centralized WhatsApp formatter. Automated verification passed: **570 passed, 4 warnings** on 2026-08-04. This is not evidence of production deployment or current live-provider health.

## 2. Current Project Status

**Repository-confirmed:** branch `main`, HEAD `bb05f75 Stabilize ordered WhatsApp context and Supabase retrieval`. Working tree has uncommitted formatter changes: `app/services/whatsapp_response_formatter.py`, its test, and changes to orchestrator/graph tests. No deployment manifest, Render configuration, Terraform, Dockerfile, Compose file, queue, or CI workflow was found at the repository root.

## 3. Completed Work

- FastAPI health, inbound Exotel webhook, and delivery-status webhook.
- Inbound persistence, duplicate handling, background processing, Raipur orchestration, drafts, review lifecycle, durable outbound send claims, and callback state updates.
- Raipur knowledge ingestion/retrieval, section-aware service routing, deterministic location/catalogue/safety handling, and LangGraph as the default engine. Set `RAIPUR_LANGGRAPH_ENABLED=false` only for an explicit emergency compatibility rollback.
- Current formatter is integrated at `RaipurInboundOrchestrator.process()` after routing/grounding.

## 4. Working User Flows

Test-covered flows include greeting/gratitude; location; active service catalogue; service overview; exact service topics (duration, capacity, swimming, inclusions, safety); contextual service follow-ups; service switching; Hindi/Hinglish recognition; pricing/booking/payment/availability handover; approved drafts and send claims; and status callbacks. Live WhatsApp delivery and current provider credentials are **not verified in this handover**.

## 5. Business Rules and Safety Restrictions

- Entartica facts must come from active, approved, customer-facing Raipur knowledge or structured deterministic sources.
- Unknown Entartica-specific facts fail closed; harmless general questions may use `RaipurConversationalFallback`/OpenAI.
- Pricing, final quotation, payment, booking confirmation, cancellation/refund, medical clearance, and unverified live availability require controlled handover or approved live provider behavior.
- Sales configuration defaults are `+919429691418` (displayed as `+91 94296 91418`) and `sales@entartica.com`, verified in `.env.example` and `SalesContact`.
- `MVP_ENABLED_LOCATION_CODES=raipur` and default location is `raipur`; no other enabled location is evidenced.

## 6. Current Architecture

`Exotel → FastAPI /webhooks/exotel/inbound → normalize/validate → BackgroundTasks → InboundMessageService → RaipurInboundOrchestrator → RaipurLangGraphWorkflow by default (legacy only when explicitly disabled) → knowledge/structured route → outbound draft → optional RaipurDraftSender → Exotel`.

Supabase stores customers, conversations, messages, booking enquiries, service/location records, knowledge documents/chunks, drafts, and status-related data. OpenAI is used for embeddings/composition paths; it is not the authority for company facts.

## 7. Request-to-Reply Data Flow

`receive_inbound_message()` validates payload/signature and acknowledges 200. `process_inbound_messages_background()` obtains a process-local async lock keyed by inbound customer, persists inbound state, orchestrates, creates a draft, and attempts automatic reply only when enabled and eligible. Context is serialized into `conversations.service_context` by `_context_to_record()` and reloaded with TTL by `_context_from_record()`.

## 8. Repository Structure

- `app/api`: health and Exotel routes.
- `app/services`: conversation, LangGraph, drafts, sender, handover, response formatting.
- `app/rag`: query embedding, retrieval, Raipur provider, ingestion utilities.
- `app/repositories`: Supabase access.
- `documents/raipur`: approved local knowledge and ingestion controls.
- `supabase/migrations`: schema history through migration 014.
- `tests`: fake-only unit/integration coverage.
- `scripts`: ingestion, diagnostics, controlled operations.

## 9. Important Files and Responsibilities

See `IMPORTANT_FILES.csv`. Key entry points are `app/main.py`, `app/api/exotel_webhook.py`, `app/services/raipur_inbound_orchestrator.py`, `app/services/raipur_langgraph.py`, `app/services/raipur_conversation.py`, and `app/rag/raipur_knowledge_provider.py`.

## 10. Configuration and Environment Variables

Required by client construction: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`. OpenAI paths require `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSIONS`, `OPENAI_CHAT_MODEL`. Exotel configuration names are `EXOTEL_ACCOUNT_SID`, `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN`, `EXOTEL_BASE_URL`, `EXOTEL_WHATSAPP_FROM`, `EXOTEL_STATUS_CALLBACK_URL`, and `EXOTEL_OUTBOUND_ENABLED`. Feature flags include `RAIPUR_INBOUND_ORCHESTRATOR_ENABLED`, `RAIPUR_DRAFT_CREATION_ENABLED`, `RAIPUR_APPROVED_DRAFT_SEND_ENABLED`, `RAIPUR_AUTOMATIC_REPLY_ENABLED`, and `RAIPUR_LANGGRAPH_ENABLED`. Never record values in handover/chat.

## 11. Database and Supabase Structure

Migrations `001`–`014` cover initial schema, inbound constraints, message statuses, knowledge chunks, booking availability, outbound drafts/claims, Raipur seed/location/services/availability, context storage, and location correction. `get_supabase_client()` uses server-side secret key. `log_startup_readiness()` makes only minimal SELECTs on customers/conversations/messages/knowledge_documents and logs safe category/code. RLS, backups, and current applied migration state are **not verified from this repository**.

## 12. Knowledge-Base Structure

`documents/raipur` contains 35 files. Unified ingestion uses manifest/frontmatter approval, active/catalogue/customer-facing safeguards. `RaipurKnowledgeProvider` filters active approved customer-facing Raipur rows, rejects internal/example sections, isolates service codes, ranks headings, and supports exact direct lookup before embeddings for duration, inclusions, swimming, capacity, how-it-works, safety and eligibility.

## 13. Routing and Intent Behaviour

`RaipurLangGraphWorkflow._deterministic_plan()` handles location, catalogue, greeting, technical unknown facts, facilities, restricted intents, named services, and contextual topic follow-ups. `RaipurDialoguePlanner` supports legacy flow. Facility terms route separately ahead of booking availability. Known topic names: `overview`, `how_it_works`, `capacity`, `duration`, `swimming`, `swimming_requirement`, `safety`, `eligibility`, `inclusions`, and `operating_hours`.

## 14. Conversation Context Behaviour

`ConversationContext` carries selected service, active topic, clarification and booking state. The orchestrator stores/reloads it in the conversation record with TTL. The per-customer lock in `exotel_webhook.py` is **single-process only**. Multiple replicas have no shared lock/queue; same-customer ordering is therefore not distributed-safe. Background work is in-process and can be interrupted by a restart; no persistent queue is present.

## 15. WhatsApp Formatting Behaviour

`format_whatsapp_response()` is called after result metadata is assembled in the orchestrator. It converts 2–5 reliable statements into simple `*heading*` plus bullets, leaves single/unsafe-to-split prose intact, keeps greetings/gratitude short, and preserves approved handovers. `validate_whatsapp_response()` checks empty output, tables, internal metadata phrases, bullet count, malformed bold markers, and overly long lines. It does not retrieve or create facts. Hindi/Hinglish are preserved textually; language-specific structural generation remains limited.

## 16. Exotel Integration

`app/integrations/exotel.py` owns the nested WhatsApp payload and Basic Auth request. Inbound webhook validates signature when `EXOTEL_SIGNATURE_VALIDATION_ENABLED=true`; `.env.example` defaults it to false. Outbound sending is protected by flags, allowlist, approved draft state, durable claims, and reconciliation-required behavior. No live request was made during this handover.

## 17. Duplicate and Idempotency Protection

Inbound duplicate protection is repository-backed via external provider/message ID. Outbound drafts have conditional claims (`202607200012_outbound_draft_send_claims.sql`), matching-token completion, reconciliation-required state, and callback SID matching. A provider ambiguity blocks resend; automatic retry is intentionally absent. Distinct inbound messages with similar body are not suppressed.

## 18. Tests and Verification

**PASSED 2026-08-04:** `python -m pytest -q` → **570 passed, 4 warnings**. Warnings: LangGraph serializer pending deprecation; Starlette TestClient deprecation; FastAPI `on_event` deprecation. Focused tests exist for webhook, payloads, outbound sender, callbacks, repositories, knowledge provider/retrieval, LangGraph, orchestrator, formatter, and controlled workflows. Live Supabase/Exotel/OpenAI checks: **NOT VERIFIED** here.

## 19. Known Issues and Limitations

- Supabase PGRST303 observed previously means JWT claims validation/parsing failure; repair credentials/project configuration before live testing. Current live auth not checked.
- Startup readiness logs access failure but does not block app startup.
- Process-local ordering is insufficient for multi-replica deployment/restarts.
- BackgroundTasks is not durable; events can be lost on process termination.
- No explicit deployment/monitoring/backups configuration exists in repository.
- Formatter has unit tests but no live device-rendering acceptance test.

## 20. Deployment Status

**NOT VERIFIED / repository appears local-development focused.** No Render, AWS/ECS, SQS, Terraform, Dockerfile, Compose, permanent-domain, or CI/CD configuration was found. Git history includes `connected Exotel to our ngrok server`; that is historical evidence only, not current tunnel health.

## 21. Rajsamand and Future Locations

No `rajsamand` file was found by repository inventory. The reported Rajsamand package is external to this repository, pending review, and must not be enabled/ingested without separate approved transfer and manifest review. Rajsamand, Prayagraj, and Coimbatore are planned only.

## 22. Pending Work by Priority

1. Resolve/verify live Supabase service-secret JWT configuration and run safe readiness diagnostic.
2. Commit/review current formatter work only after human review of customer output.
3. Perform controlled staging WhatsApp acceptance tests with outbound flags/allowlist explicitly approved.
4. Decide durable queue/shared ordering strategy before multiple replicas.
5. Add deployment, secrets, monitoring, backups, and operational runbook before production.

## 23. Safe Next Steps

Read this file, run tests, inspect `git status`, verify the startup readiness log with an approved non-production project, and use a controlled allowlisted staging recipient before enabling outbound flags. Do not re-ingest knowledge or change `.env` as part of diagnosis without approval.

## 24. Actions the New Codex Must Avoid

Do not expose secrets/customer data; call live providers; enable send flags; run migrations; ingest; resend reconciliation-required drafts; bypass draft/send claims; remove approval filters; or refactor working routing in bulk without a bounded, tested request.

## 25. Exact Continuation Commands

```powershell
cd C:\Users\mandi\OneDrive\Documents\entartica_whatsapp_chat_bot
& "C:\Users\mandi\AppData\Local\Programs\Python\Python312\python.exe" -m pytest -q
python scripts/ingest_raipur_knowledge.py --dry-run
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Do not run live ingestion, confirmed cleanup/preparation, or confirmed send without explicit approval.

## 26. Git Status and Checkpoint

At inspection: branch `main`; commit `bb05f75`; dirty tree: two modified formatter/orchestrator test files and two untracked formatter files. The most recent committed work is ordered WhatsApp context and Supabase retrieval stabilization.

## 27. Final Readiness Assessment

Application logic is heavily test-covered but **not production-ready** by repository evidence. Deployment/durability/live credential health/operational monitoring remain unverified or pending.
