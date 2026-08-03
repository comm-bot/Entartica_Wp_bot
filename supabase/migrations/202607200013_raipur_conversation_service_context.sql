-- Durable, non-customer-content context for safe Raipur service follow-ups.

alter table public.conversations
  add column if not exists service_context jsonb not null default '{}'::jsonb;

create index if not exists conversations_service_context_updated_at_idx
  on public.conversations ((service_context ->> 'context_updated_at'));
