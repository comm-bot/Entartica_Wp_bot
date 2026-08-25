-- Approved Raipur services only. Review and apply manually in Supabase SQL Editor.
-- This migration does not change enquiries, customers, messages, knowledge, or other locations.

do $$
declare
  raipur_location_id uuid;
  location_count integer;
  item record;
  matching_count integer;
begin
  select count(*) into location_count
  from public.locations
  where slug = 'raipur' and is_active = true;

  if location_count = 0 then
    raise exception 'approved Raipur location is missing or inactive';
  end if;
  if location_count <> 1 then
    raise exception 'multiple active Raipur locations require review';
  end if;
  select id into raipur_location_id from public.locations where slug = 'raipur' and is_active = true;

  for item in
    select * from (values
      ('Staycation Combo', 'staycation-combo', 'staycation_daycation', 'Staycation and Daycation'),
      ('Daycation Package', 'daycation-package', 'staycation_daycation', 'Staycation and Daycation'),
      ('Pontoon Boat', 'pontoon-boat', 'water_ride', 'Water Ride Portfolio'),
      ('Kayak', 'kayak', 'water_ride', 'Water Ride Portfolio'),
      ('Speed Boat', 'speed-boat', 'water_ride', 'Water Ride Portfolio'),
      ('Aqua Cycle', 'aqua-cycle', 'water_ride', 'Water Ride Portfolio'),
      ('Aqua Roller', 'aqua-roller', 'water_ride', 'Water Ride Portfolio'),
      ('Jet Ski', 'jet-ski', 'water_ride', 'Water Ride Portfolio'),
      ('Water Bike', 'water-bike', 'water_ride', 'Water Ride Portfolio'),
      ('Inflatable Sofa Ride', 'inflatable-sofa-ride', 'water_ride', 'Water Ride Portfolio'),
      ('Bumper Boat', 'bumper-boat', 'water_ride', 'Water Ride Portfolio'),
      ('Kids'' Paddle Boat', 'kids-paddle-boat', 'water_ride', 'Water Ride Portfolio'),
      ('Zorbing Ball', 'zorbing-ball', 'water_ride', 'Water Ride Portfolio'),
      ('Kids Bumper Boat', 'kids-bumper-boat', 'water_ride', 'Water Ride Portfolio'),
      ('Pontoon Celebration', 'pontoon-celebration', 'floating_celebration', 'Floating Celebration Services'),
      ('Floating Gazebo', 'floating-gazebo', 'floating_celebration', 'Floating Celebration Services'),
      ('Jetty Gazebo', 'jetty-gazebo', 'floating_celebration', 'Floating Celebration Services'),
      ('Houseboat Celebration', 'houseboat-celebration', 'floating_celebration', 'Floating Celebration Services'),
      ('Party Boat Celebration', 'party-boat-celebration', 'floating_celebration', 'Floating Celebration Services')
    ) as approved(name, slug, category, source_section)
  loop
    select count(*) into matching_count
    from public.services
    where location_id = raipur_location_id
      and (slug = item.slug or lower(trim(name)) = lower(trim(item.name)));

    if matching_count > 1 then
      raise exception 'duplicate Raipur service records require review';
    elsif matching_count = 1 then
      if exists (
        select 1 from public.services
        where location_id = raipur_location_id and slug = item.slug
          and lower(trim(name)) = lower(trim(item.name))
      ) then
        update public.services set is_active = true
        where location_id = raipur_location_id and slug = item.slug
          and lower(trim(name)) = lower(trim(item.name)) and is_active = false;
      else
        raise exception 'existing Raipur service conflicts with approved source';
      end if;
    else
      insert into public.services (location_id, name, slug, is_active, metadata)
      values (
        raipur_location_id, item.name, item.slug, true,
        jsonb_build_object(
          'location_code', 'raipur', 'approval_status', 'approved',
          'source_filename', 'raipur_services.docx', 'source_section', item.source_section,
          'category', item.category
        )
      );
    end if;
  end loop;
end $$;
