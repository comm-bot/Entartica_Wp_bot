-- Draft-only orchestrator responses. These records are never provider sends.
alter table public.messages
  add column if not exists related_inbound_message_id text,
  add column if not exists draft_status text not null default 'pending_review' check (draft_status in ('pending_review', 'approved', 'rejected', 'sent', 'failed')),
  add column if not exists draft_metadata jsonb not null default '{}'::jsonb,
  add column if not exists generated_by text,
  add column if not exists reviewed_at timestamptz,
  add column if not exists reviewer_note text,
  add column if not exists sent_at timestamptz;

create unique index if not exists messages_raipur_draft_idempotency_idx
  on public.messages (related_inbound_message_id, generated_by)
  where direction = 'outbound' and draft_status = 'pending_review' and related_inbound_message_id is not null;
