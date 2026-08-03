-- Correct the approved, structured Raipur location details only.
-- Review and apply manually through the Supabase SQL Editor or CLI.

update public.locations
set
  name = 'Entartica Sea World Raipur',
  address = 'Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh',
  metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
    'location_name', 'Entartica Sea World Raipur',
    'address_line', 'Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh',
    'landmark', 'Near MAYFAIR Resort',
    'maps_url', 'https://maps.app.goo.gl/VtxPyANfMC3rztex8'
  )
where slug = 'raipur';
