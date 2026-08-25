# Completed

- FastAPI APIs, Exotel normalization/callbacks, Supabase repositories/migrations, Raipur retrieval/routing, drafts/send claims, and test coverage.
- 530 local tests passed on 2026-08-04.

# Partially Completed

- WhatsApp response formatter is implemented/tested but uncommitted.
- Startup readiness check exists; live credential health is not verified.
- Automatic replies exist but must remain controlled by flags and recipient allowlist.
- LangGraph is the default Raipur engine; explicit `RAIPUR_LANGGRAPH_ENABLED=false` retains the emergency compatibility engine. Live WhatsApp acceptance and a Git rollback tag remain required before legacy deletion.

# Pending

- Production deployment, monitoring, backups, durable queue/shared ordering, and live acceptance testing.

# Blocked

- Live Supabase auth/reliability requires valid approved server credentials; prior PGRST303 indicates JWT claims validation/parsing failure.

# Requires Business Approval

- Enabling outbound flags, live sends, migration application, ingestion, other locations, Rajsamand approval, and production deployment.

# Requires Live Verification

- Current Exotel callback/tunnel, Supabase readiness, OpenAI provider health, approved send lifecycle, delivery callbacks, and phone rendering.

# Recommended Next Milestone

- Resolve staging Supabase JWT/readiness, then perform one explicitly approved staging WhatsApp end-to-end test using the durable draft lifecycle.
