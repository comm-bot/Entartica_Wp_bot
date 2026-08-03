-- Durable, cross-worker claim state for explicitly approved draft sends.
alter table public.messages
  add column send_claim_token text,
  add column send_claimed_at timestamptz,
  add column send_attempt_state text not null default 'none'
    check (send_attempt_state in ('none','claimed','provider_accepted','completed','provider_failed','reconciliation_required')),
  add column reconciliation_required_at timestamptz;

create unique index messages_active_send_claim_idx
  on public.messages (id)
  where send_attempt_state in ('claimed','provider_accepted','reconciliation_required');
