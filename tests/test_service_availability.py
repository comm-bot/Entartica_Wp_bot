from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.availability import AvailabilityRequest, SupabaseAvailabilityProvider
from scripts import verify_raipur_availability_schema as verifier

NOW=datetime(2026,7,22,10,tzinfo=timezone.utc)
def request(time="10:00:00"):return AvailabilityRequest("Jet Ski","2026-08-01",time,2,"raipur","jet","Jet Ski")
class Repo:
 def __init__(self,row=None,rows=(),error=False):self.row=row;self.rows=rows;self.error=error
 def get_exact_slot(self,*_):
  if self.error:raise RuntimeError()
  return self.row
 def list_slots_for_service_date(self,*_,**__):return list(self.rows)
def row(status="available",capacity=2,verified=NOW):return {"start_time":"10:00:00","end_time":"11:00:00","available_capacity":capacity,"operational_status":status,"last_verified_at":verified.isoformat()}
def test_provider_maps_live_statuses_staleness_missing_errors_and_alternatives():
 for db,capacity,result in (("available",2,"available"),("limited",1,"limited"),("full",0,"not_available"),("closed",0,"not_available"),("maintenance",0,"not_available"),("weather_hold",2,"verification_required"),("verification_required",2,"verification_required")):
  assert SupabaseAvailabilityProvider(Repo(row(db,capacity)),now=lambda:NOW).check(request()).status==result
 assert SupabaseAvailabilityProvider(Repo(row(verified=NOW-timedelta(minutes=31))),now=lambda:NOW).check(request()).status=="stale"
 assert SupabaseAvailabilityProvider(Repo(),now=lambda:NOW).check(request()).status=="verification_required"
 assert SupabaseAvailabilityProvider(Repo(error=True),now=lambda:NOW).check(request()).status=="provider_error"
 alternatives=SupabaseAvailabilityProvider(Repo(rows=[row("available",2),row("full",0),row("limited",1)|{"start_time":"16:00:00"}]),now=lambda:NOW).check(request(""))
 assert alternatives.approved_alternatives==("10:00:00","16:00:00") and alternatives.status=="verification_required"
def test_unknown_service_never_queries_provider():
 assert SupabaseAvailabilityProvider(Repo(error=True),now=lambda:NOW).check(AvailabilityRequest("unknown","2026-08-01","10:00:00",2,"raipur",None)).safe_reason_code=="approved_service_required"
def test_migration_has_constraints_without_reservations_prices_or_payment():
 sql=(Path(__file__).resolve().parents[1]/"supabase/migrations/202607200011_raipur_service_availability.sql").read_text().casefold()
 executable="\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
 assert "available_capacity <= total_capacity" in sql and "end_time > start_time" in sql and "unique (service_id, availability_date, start_time, end_time)" in sql
 assert all(word not in executable for word in ("reservation","price","payment"))
class Query:
 def __init__(self,data):self.data=data
 def select(self,*_):return self
 def eq(self,*_):return self
 def execute(self):return type("R",(),{"data":self.data})()
class Client:
 def __init__(self,locations,services,slots):self.data={"locations":locations,"services":services,"service_availability":slots}
 def table(self,name):return Query(self.data[name])
def test_schema_verifier_handles_missing_and_ready_rows():
 assert verifier.inspect_availability_schema(Client([],[],[]))["reason"]=="raipur_location_missing"
 ready=verifier.inspect_availability_schema(Client([{"id":"r","is_active":True}],[{"id":"s"}],[{"service_id":"s","availability_date":"2026-08-01","start_time":"10:00","end_time":"11:00","total_capacity":2,"available_capacity":1,"last_verified_at":NOW.isoformat()}]),now=NOW)
 assert ready["reason"]=="ready" and ready["fresh_slots"]==1
