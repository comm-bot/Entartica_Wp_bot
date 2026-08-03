-- Raipur service availability only. Review and apply manually in Supabase SQL Editor.
-- No reservation, capacity decrement, payment, price, booking confirmation, or customer data is created.

create table public.service_availability (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete restrict,
  service_id uuid not null references public.services(id) on delete restrict,
  availability_date date not null,
  start_time time not null,
  end_time time not null,
  total_capacity integer not null check (total_capacity >= 0),
  available_capacity integer not null check (available_capacity >= 0 and available_capacity <= total_capacity),
  operational_status text not null default 'verification_required' check (operational_status in (
    'available', 'limited', 'full', 'closed', 'weather_hold', 'maintenance', 'verification_required'
  )),
  last_verified_at timestamptz not null,
  internal_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (service_id, availability_date, start_time, end_time),
  check (end_time > start_time)
);

create index service_availability_service_date_idx
  on public.service_availability (location_id, service_id, availability_date, start_time);
create index service_availability_verified_idx
  on public.service_availability (last_verified_at desc);

create or replace function public.enforce_service_availability_location()
returns trigger language plpgsql as $$
begin
  if not exists (
    select 1 from public.services
    where id = new.service_id and location_id = new.location_id
  ) then
    raise exception 'availability service must belong to its location';
  end if;
  return new;
end;
$$;

create trigger service_availability_location_match
before insert or update on public.service_availability
for each row execute function public.enforce_service_availability_location();

create trigger service_availability_set_updated_at
before update on public.service_availability
for each row execute function public.set_updated_at();

alter table public.service_availability enable row level security;

alter table public.booking_enquiries
  drop constraint booking_enquiries_availability_status_check;
alter table public.booking_enquiries
  add constraint booking_enquiries_availability_status_check
  check (availability_status in ('verification_required', 'available', 'limited', 'not_available', 'stale', 'provider_error'));
