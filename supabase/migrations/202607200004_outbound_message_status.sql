-- Outbound Exotel WhatsApp delivery lifecycle fields.

alter table public.messages
  add column accepted_at timestamptz,
  add column sent_at timestamptz,
  add column delivered_at timestamptz,
  add column read_at timestamptz,
  add column failed_at timestamptz,
  add column failure_code text,
  add column failure_description text;

alter table public.messages
  add constraint messages_delivery_status_check
  check (
    delivery_status is null
    or delivery_status in ('pending', 'accepted', 'sent', 'delivered', 'read', 'failed')
  );

create index messages_outbound_delivery_status_idx
  on public.messages (delivery_status, created_at desc)
  where direction = 'outbound';
