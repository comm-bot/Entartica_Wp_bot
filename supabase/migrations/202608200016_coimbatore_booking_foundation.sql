-- Durable Coimbatore booking/payment foundation.
-- Forward-only: creates new server-only tables and does not alter existing data.

create table public.bookings (
  id uuid primary key default gen_random_uuid(),
  booking_ref text not null unique check (char_length(trim(booking_ref)) > 0),
  conversation_id uuid references public.conversations(id) on delete set null,
  customer_id uuid references public.customers(id) on delete set null,
  location_code text not null check (char_length(trim(location_code)) > 0),
  product_code text not null check (char_length(trim(product_code)) > 0),
  package_id text not null check (char_length(trim(package_id)) > 0),
  event_date date,
  preferred_time time without time zone,
  guest_count integer check (guest_count is null or guest_count > 0),
  occasion text,
  customer_name text,
  customer_mobile text,
  customer_email text,
  zoho_submission_id text,
  amount_paise bigint not null check (amount_paise > 0),
  currency text not null default 'INR' check (char_length(trim(currency)) = 3),
  status text not null default 'form_pending' check (status in (
    'form_pending', 'form_submitted', 'form_invalid',
    'payment_link_created', 'payment_link_failed', 'payment_pending',
    'payment_received', 'confirmation_generating', 'confirmation_failed',
    'confirmed', 'cancelled', 'handoff'
  )),
  confirmation_pdf_url text,
  confirmation_pdf_storage_key text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  form_submitted_at timestamptz,
  payment_received_at timestamptz,
  confirmed_at timestamptz
);

create unique index bookings_zoho_submission_id_uidx
  on public.bookings (zoho_submission_id) where zoho_submission_id is not null;
create index bookings_conversation_id_idx on public.bookings (conversation_id);
create index bookings_customer_id_idx on public.bookings (customer_id);
create index bookings_status_idx on public.bookings (status);
create index bookings_event_date_idx on public.bookings (event_date);
create index bookings_customer_mobile_idx on public.bookings (customer_mobile);
create index bookings_customer_email_idx on public.bookings (customer_email);

create trigger bookings_set_updated_at
before update on public.bookings
for each row execute function public.set_updated_at();

alter table public.bookings enable row level security;

create table public.payments (
  id uuid primary key default gen_random_uuid(),
  booking_id uuid not null references public.bookings(id) on delete restrict,
  provider text not null check (char_length(trim(provider)) > 0),
  reference_id text not null unique check (char_length(trim(reference_id)) > 0),
  provider_payment_link_id text,
  provider_payment_id text,
  payment_url text,
  amount_paise bigint not null check (amount_paise > 0),
  currency text not null default 'INR' check (char_length(trim(currency)) = 3),
  status text not null default 'created' check (status in (
    'created', 'issued', 'pending', 'paid', 'failed',
    'expired', 'cancelled', 'verification_failed'
  )),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  paid_at timestamptz,
  expired_at timestamptz
);

create unique index payments_provider_payment_link_id_uidx
  on public.payments (provider_payment_link_id) where provider_payment_link_id is not null;
create unique index payments_provider_payment_id_uidx
  on public.payments (provider_payment_id) where provider_payment_id is not null;
create index payments_booking_id_idx on public.payments (booking_id);
create index payments_status_idx on public.payments (status);

create trigger payments_set_updated_at
before update on public.payments
for each row execute function public.set_updated_at();

alter table public.payments enable row level security;

create table public.webhook_events (
  id uuid primary key default gen_random_uuid(),
  provider text not null check (char_length(trim(provider)) > 0),
  provider_event_id text not null check (char_length(trim(provider_event_id)) > 0),
  event_type text not null check (char_length(trim(event_type)) > 0),
  booking_id uuid references public.bookings(id) on delete set null,
  payment_id uuid references public.payments(id) on delete set null,
  status text not null default 'received' check (status in (
    'received', 'processing', 'processed', 'ignored', 'failed'
  )),
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  error_code text,
  created_at timestamptz not null default now(),
  unique (provider, provider_event_id)
);

create index webhook_events_booking_id_idx on public.webhook_events (booking_id);
create index webhook_events_payment_id_idx on public.webhook_events (payment_id);
create index webhook_events_status_idx on public.webhook_events (status);

alter table public.webhook_events enable row level security;
