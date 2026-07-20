-- Constraints for idempotent inbound webhook processing.

alter table public.messages
  add column received_at timestamptz not null default now();

create index messages_received_at_idx
  on public.messages (received_at desc);

create unique index conversations_one_open_per_customer_idx
  on public.conversations (customer_id)
  where state <> 'closed' and closed_at is null;
