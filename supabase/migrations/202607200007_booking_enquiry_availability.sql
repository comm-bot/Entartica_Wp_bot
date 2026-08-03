-- Local-draft booking enquiries and approved-live-source availability support.
-- This migration deliberately has no confirmed-booking, payment, or reservation state.

alter table public.booking_enquiries
  add column requested_service_id uuid references public.services(id) on delete restrict,
  add column requested_service_text text,
  add column total_guests integer check (total_guests is null or total_guests > 0),
  add column availability_status text not null default 'verification_required'
    check (availability_status in ('verification_required', 'available', 'not_available', 'stale')),
  add column enquiry_status text not null default 'collecting_details'
    check (enquiry_status in (
      'collecting_details', 'pending_availability_check', 'availability_found',
      'availability_not_found', 'pending_sales_followup', 'contacted', 'closed'
    )),
  add column assigned_salesperson text,
  add column source text not null default 'whatsapp'
    check (source in ('whatsapp')),
  add column source_message_id text;

create unique index booking_enquiries_whatsapp_source_message_idx
  on public.booking_enquiries (source, source_message_id)
  where source_message_id is not null;

create index booking_enquiries_enquiry_status_created_at_idx
  on public.booking_enquiries (enquiry_status, created_at desc);

create or replace function public.booking_enquiry_schema_ready()
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'table_exists', to_regclass('public.booking_enquiries') is not null,
    'expected_columns_exist', (select count(*) = 8 from information_schema.columns
      where table_schema = 'public' and table_name = 'booking_enquiries'
      and column_name in ('requested_service_id','requested_service_text','total_guests','availability_status','enquiry_status','assigned_salesperson','source','source_message_id')),
    'idempotency_index_exists', exists(select 1 from pg_indexes where schemaname='public' and indexname='booking_enquiries_whatsapp_source_message_idx'),
    'status_fields_exist', exists(select 1 from information_schema.columns where table_schema='public' and table_name='booking_enquiries' and column_name='enquiry_status'),
    'availability_fields_exist', exists(select 1 from information_schema.columns where table_schema='public' and table_name='booking_enquiries' and column_name='availability_status')
  );
$$;
