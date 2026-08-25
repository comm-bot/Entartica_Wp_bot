-- Secure, short-lived Coimbatore customer-details form sessions.
alter table public.customers
  add column if not exists email text,
  add column if not exists details_completed_at timestamptz;

create index if not exists customers_email_idx
  on public.customers (lower(email)) where email is not null;

create table if not exists public.customer_detail_forms (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references public.customers(id) on delete cascade,
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  token_digest text not null unique check (token_digest ~ '^[a-f0-9]{64}$'),
  source text not null default 'whatsapp' check (source in ('whatsapp')),
  status text not null default 'pending' check (status in ('pending', 'completed', 'expired')),
  expires_at timestamptz not null,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((status = 'completed') = (completed_at is not null))
);

create index if not exists customer_detail_forms_identity_idx
  on public.customer_detail_forms (customer_id, conversation_id, created_at desc);

alter table public.customer_detail_forms enable row level security;

create trigger customer_detail_forms_set_updated_at
before update on public.customer_detail_forms
for each row execute function public.set_updated_at();
