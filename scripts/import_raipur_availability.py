"""Approval-gated Raipur availability import; dry-run by default."""
from __future__ import annotations
import argparse, re
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.repositories.locations import LocationRepository
from app.repositories.services import ServiceRepository
from app.services.raipur_availability_input import checksum, validate

def approval_valid(path:Path,source:Path)->bool:
 try:text=path.read_text(encoding="utf-8")
 except OSError:return False
 return bool(re.search(r"Approval status:\s*APPROVED\b",text) and re.search(rf"Source CSV filename:\s*{re.escape(source.name)}\s*$",text,re.M) and checksum(source) in text)
def main()->int:
 parser=argparse.ArgumentParser();parser.add_argument("--file",type=Path,required=True);parser.add_argument("--approval-file",type=Path,default=ROOT/"reports/raipur_availability_management_approval.md");parser.add_argument("--confirm-live-import",action="store_true");args=parser.parse_args();report=validate(args.file,max_age_minutes=Settings().availability_max_age_minutes)
 if not report.file_valid:print(f"availability_import_refused file_valid=false reason={report.reason}");return 1
 if not approval_valid(args.approval_file,args.file):print("availability_import_refused approval_valid=false reason=management_approval_required");return 1
 if not args.confirm_live_import:print(f"mode=dry_run live_write_performed=false proposed_inserts={len(report.rows)} proposed_updates=0 rows_unchanged=0 duplicates_prevented={report.metrics['duplicate_rows']} reason=dry_run");return 0
 client=get_supabase_client();location=LocationRepository(client).get_location_by_code("raipur")
 if not isinstance(location,dict) or not isinstance(location.get("id"),str):print("availability_import_refused reason=raipur_location_missing");return 1
 services=ServiceRepository(client);inserted=updated=unchanged=0
 for row in report.rows:
  service=services.find_active_by_customer_text(location["id"],row["service_name"])
  if not isinstance(service,dict) or not isinstance(service.get("id"),str):print("availability_import_refused reason=approved_service_missing");return 1
  query=client.table("service_availability").select("id,total_capacity,available_capacity,operational_status,last_verified_at,internal_note").eq("location_id",location["id"]).eq("service_id",service["id"]).eq("availability_date",row["availability_date"]).eq("start_time",row["start_time"]).eq("end_time",row["end_time"]).execute();existing=getattr(query,"data",[]) or []
  payload={"total_capacity":int(row["total_capacity"]),"available_capacity":int(row["available_capacity"]),"operational_status":row["operational_status"],"last_verified_at":row["verified_at"],"internal_note":row["internal_note"]}
  if not existing:client.table("service_availability").insert({"location_id":location["id"],"service_id":service["id"],"availability_date":row["availability_date"],"start_time":row["start_time"],"end_time":row["end_time"],**payload}).execute();inserted+=1
  elif all(existing[0].get(k)==v for k,v in payload.items()):unchanged+=1
  else:client.table("service_availability").update(payload).eq("id",existing[0]["id"]).execute();updated+=1
 print(f"mode=live rows_inserted={inserted} rows_updated={updated} rows_unchanged={unchanged} duplicates_prevented={report.metrics['duplicate_rows']} reason=completed");return 0
if __name__=="__main__":raise SystemExit(main())
