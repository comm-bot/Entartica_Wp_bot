-- Approved Raipur location only. Review and apply manually in Supabase SQL Editor.
-- No services, messages, knowledge, enquiries, or other locations are changed.

insert into public.locations (name, slug, city, state, country, is_active)
values ('Entartica Sea World Raipur', 'raipur', 'Raipur', 'Chhattisgarh', 'India', true)
on conflict (slug) do update
  set is_active = true
  where public.locations.name = 'Entartica Sea World Raipur'
    and public.locations.city = 'Raipur'
    and public.locations.state = 'Chhattisgarh';
