-- Initial application schema. Apply through the Supabase SQL Editor or CLI.

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table public.locations (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) > 0),
  slug text not null unique check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  address text,
  city text,
  state text,
  country text not null default 'India',
  is_active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.services (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete restrict,
  name text not null check (char_length(trim(name)) > 0),
  slug text not null check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  description text,
  is_active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (location_id, slug)
);

create table public.customers (
  id uuid primary key default gen_random_uuid(),
  whatsapp_number text not null unique check (whatsapp_number ~ '^\+?[1-9][0-9]{7,14}$'),
  name text,
  preferred_language text check (preferred_language in ('en', 'hi', 'hinglish')),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references public.customers(id) on delete restrict,
  state text not null default 'new' check (state in (
    'new', 'awaiting_name', 'awaiting_location', 'awaiting_service',
    'awaiting_date', 'awaiting_time', 'awaiting_guest_count',
    'awaiting_event_details', 'enquiry_complete', 'human_handover', 'closed'
  )),
  mode text not null default 'bot' check (mode in ('bot', 'human')),
  assigned_team text,
  handover_reason text,
  closed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete restrict,
  customer_id uuid not null references public.customers(id) on delete restrict,
  direction text not null check (direction in ('inbound', 'outbound')),
  message_type text not null default 'text' check (message_type in ('text', 'image', 'document', 'audio', 'video', 'other')),
  content text,
  external_provider text,
  external_message_id text,
  delivery_status text,
  raw_payload jsonb,
  created_at timestamptz not null default now(),
  unique (external_provider, external_message_id)
);

create table public.booking_enquiries (
  id uuid primary key default gen_random_uuid(),
  reference text not null unique check (reference ~ '^ENQ-[0-9]{8}-[0-9]{4,}$'),
  customer_id uuid not null references public.customers(id) on delete restrict,
  conversation_id uuid references public.conversations(id) on delete set null,
  location_id uuid references public.locations(id) on delete restrict,
  service_id uuid references public.services(id) on delete restrict,
  preferred_date date,
  preferred_time time,
  guest_count integer check (guest_count is null or guest_count > 0),
  adult_count integer check (adult_count is null or adult_count >= 0),
  child_count integer check (child_count is null or child_count >= 0),
  special_requirements text,
  status text not null default 'new' check (status in ('new', 'in_progress', 'submitted', 'assigned', 'closed', 'cancelled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.leads (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references public.customers(id) on delete restrict,
  conversation_id uuid references public.conversations(id) on delete set null,
  location_id uuid references public.locations(id) on delete restrict,
  lead_type text not null check (lead_type in ('wedding', 'corporate_event', 'school_group', 'large_group', 'party', 'photoshoot', 'other_event')),
  preferred_event_date date,
  estimated_guest_count integer check (estimated_guest_count is null or estimated_guest_count > 0),
  requirements text,
  preferred_callback_time text,
  assigned_team text,
  status text not null default 'new' check (status in ('new', 'in_progress', 'assigned', 'closed', 'cancelled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.knowledge_documents (
  id uuid primary key default gen_random_uuid(),
  source_file text not null check (char_length(trim(source_file)) > 0),
  document_version text,
  approved_by text,
  effective_date date,
  review_date date,
  is_active boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source_file, document_version)
);

create table public.unanswered_questions (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid references public.customers(id) on delete set null,
  conversation_id uuid references public.conversations(id) on delete set null,
  question text not null check (char_length(trim(question)) > 0),
  status text not null default 'open' check (status in ('open', 'reviewing', 'resolved', 'dismissed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.system_settings (
  id uuid primary key default gen_random_uuid(),
  setting_key text not null unique check (setting_key ~ '^[a-z][a-z0-9_]*$'),
  setting_value jsonb not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_type text not null check (actor_type in ('system', 'customer', 'employee', 'api')),
  actor_id text,
  action text not null check (char_length(trim(action)) > 0),
  entity_type text not null check (char_length(trim(entity_type)) > 0),
  entity_id uuid,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index services_active_location_name_idx on public.services (location_id, name) where is_active;
create index conversations_customer_created_at_idx on public.conversations (customer_id, created_at desc);
create index messages_conversation_created_at_idx on public.messages (conversation_id, created_at desc);
create index messages_customer_created_at_idx on public.messages (customer_id, created_at desc);
create index booking_enquiries_status_created_at_idx on public.booking_enquiries (status, created_at desc);
create index leads_status_created_at_idx on public.leads (status, created_at desc);
create index knowledge_documents_active_idx on public.knowledge_documents (is_active) where is_active;
create index unanswered_questions_status_created_at_idx on public.unanswered_questions (status, created_at desc);
create index audit_logs_entity_idx on public.audit_logs (entity_type, entity_id, created_at desc);

create trigger locations_set_updated_at before update on public.locations for each row execute function public.set_updated_at();
create trigger services_set_updated_at before update on public.services for each row execute function public.set_updated_at();
create trigger customers_set_updated_at before update on public.customers for each row execute function public.set_updated_at();
create trigger conversations_set_updated_at before update on public.conversations for each row execute function public.set_updated_at();
create trigger booking_enquiries_set_updated_at before update on public.booking_enquiries for each row execute function public.set_updated_at();
create trigger leads_set_updated_at before update on public.leads for each row execute function public.set_updated_at();
create trigger knowledge_documents_set_updated_at before update on public.knowledge_documents for each row execute function public.set_updated_at();
create trigger unanswered_questions_set_updated_at before update on public.unanswered_questions for each row execute function public.set_updated_at();
create trigger system_settings_set_updated_at before update on public.system_settings for each row execute function public.set_updated_at();

alter table public.locations enable row level security;
alter table public.services enable row level security;
alter table public.customers enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.booking_enquiries enable row level security;
alter table public.leads enable row level security;
alter table public.knowledge_documents enable row level security;
alter table public.unanswered_questions enable row level security;
alter table public.system_settings enable row level security;
alter table public.audit_logs enable row level security;
