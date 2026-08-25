# Start Prompt for New Codex

Work in `C:\Users\mandi\OneDrive\Documents\entartica_whatsapp_chat_bot`. First read `AGENTS.md`, then `CODEX_HANDOVER.md`, then inspect `git status` before editing anything.

This is an Entartica Sea World WhatsApp chatbot. Raipur is the only enabled location. The stack is Python 3.12, FastAPI, Exotel, Supabase, OpenAI 2.46.0, LangGraph 0.6.6, and pytest. It has approved Raipur RAG, deterministic safety routing, persisted context, outbound draft/send claims, callbacks, and a currently uncommitted centralized WhatsApp formatter.

Business rules: approved location-specific knowledge only for Entartica facts; unknown Entartica facts fail closed; harmless non-Entartica general questions may use the configured OpenAI fallback; pricing, live availability, payment, booking confirmation, refunds/cancellation, medical clearance, and final quotations are not automated. Sales contact comes from `ENTARTICA_SALES_PHONE` and `ENTARTICA_SALES_EMAIL` (repository defaults display `+91 94296 91418`, `sales@entartica.com`). Do not enable other locations.

Key files: `app/api/exotel_webhook.py`, `app/services/raipur_inbound_orchestrator.py`, `app/services/raipur_langgraph.py`, `app/services/raipur_conversation.py`, `app/rag/raipur_knowledge_provider.py`, `app/services/whatsapp_response_formatter.py`, `app/services/raipur_draft_sender.py`, `app/repositories/outbound_drafts.py`, and `supabase/migrations/`.

Latest verified test command: `python -m pytest -q` on 2026-08-04 → **530 passed, 4 warnings**. This does not verify live Supabase/Exotel/OpenAI. The working tree was dirty because the formatting layer was not committed.

Do not rewrite working logic, perform migrations/ingestion, alter `.env`, call live providers, enable outbound flags, or send WhatsApp without explicit user permission. Do not bypass durable send claims or resend reconciliation-required drafts.

Known limitations: Supabase PGRST303 previously indicates JWT claims validation/parsing error; live credentials are not verified. Same-customer ordering is process-local only; BackgroundTasks is in-process and non-durable; no queue/deployment/monitoring/backups configuration was found; multiple replicas are unsafe for strict ordering.

First recommended task: inspect the uncommitted formatter changes and make a small reviewed commit only if the user approves; otherwise diagnose Supabase startup readiness safely in a staging project.

Verify with:

```powershell
cd C:\Users\mandi\OneDrive\Documents\entartica_whatsapp_chat_bot
git -c safe.directory=C:/Users/mandi/OneDrive/Documents/entartica_whatsapp_chat_bot status --short
& "C:\Users\mandi\AppData\Local\Programs\Python\Python312\python.exe" -m pytest -q
```
