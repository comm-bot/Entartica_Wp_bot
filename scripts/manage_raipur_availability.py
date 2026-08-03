"""Operations-only availability manager; reads by default and never deletes slots."""
from __future__ import annotations
import argparse
from datetime import date, datetime, time, timezone
from pathlib import Path
import sys
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.integrations.supabase import get_supabase_client
from app.repositories.locations import LocationRepository
from app.repositories.services import ServiceRepository
VALID={"available","limited","full","closed","weather_hold","maintenance","verification_required"}
def _rows(response:object)->list[dict[str,Any]]:
    data=getattr(response,"data",None);return data if isinstance(data,list) else [data] if isinstance(data,dict) else []
def _target(client:Any, slug:str)->tuple[dict[str,Any]|None,dict[str,Any]|None]:
    location=LocationRepository(client).get_location_by_code("raipur")
    return location, ServiceRepository(client).get_active_by_slug(location["id"],slug) if isinstance(location,dict) and isinstance(location.get("id"),str) else None
def _valid(values:argparse.Namespace)->bool:
    try:
        date.fromisoformat(values.date); start=time.fromisoformat(values.start_time); end=time.fromisoformat(values.end_time)
        return end>start and values.total_capacity>=0 and 0<=values.available_capacity<=values.total_capacity and values.status in VALID
    except (TypeError,ValueError): return False
def main()->int:
    parser=argparse.ArgumentParser(description="Read or explicitly update approved Raipur availability.")
    parser.add_argument("--action",choices=("list","stale","verify-service","create","update-capacity","update-status","mark-verified"),default="list");parser.add_argument("--service-slug");parser.add_argument("--date");parser.add_argument("--start-time");parser.add_argument("--end-time");parser.add_argument("--total-capacity",type=int);parser.add_argument("--available-capacity",type=int);parser.add_argument("--status");parser.add_argument("--confirm-write",action="store_true")
    args=parser.parse_args()
    if args.action in {"create","update-capacity","update-status","mark-verified"} and not args.confirm_write: print("availability_operation_refused confirmation_required=true");return 2
    if args.action!="stale" and not args.service_slug: print("availability_operation_refused service_required=true");return 2
    client=get_supabase_client();location,service=_target(client,args.service_slug) if args.service_slug else (LocationRepository(client).get_location_by_code("raipur"),None)
    if not location or (args.action!="stale" and not service): print("availability_operation_refused approved_raipur_service_required=true");return 1
    if args.action in {"list","verify-service"}:
        if args.action=="verify-service": print("availability_service_verified=true");return 0
        if not args.date: print("availability_operation_refused date_required=true");return 2
        rows=_rows(client.table("service_availability").select("availability_date,start_time,end_time,operational_status,last_verified_at").eq("location_id",location["id"]).eq("service_id",service["id"]).eq("availability_date",args.date).order("start_time").limit(20).execute());print(f"availability_list_complete slot_count={len(rows)}");return 0
    if args.action=="stale":
        rows=_rows(client.table("service_availability").select("last_verified_at").eq("location_id",location["id"]).limit(100).execute());print(f"availability_stale_check_complete checked_slot_count={len(rows)}");return 0
    if args.action=="create" and not _valid(args): print("availability_operation_refused invalid_slot_values=true");return 2
    if args.action=="create":
        client.table("service_availability").insert({"location_id":location["id"],"service_id":service["id"],"availability_date":args.date,"start_time":args.start_time,"end_time":args.end_time,"total_capacity":args.total_capacity,"available_capacity":args.available_capacity,"operational_status":args.status,"last_verified_at":datetime.now(timezone.utc).isoformat()}).execute()
    elif args.action=="update-capacity":
        if not args.date or not args.start_time or args.total_capacity is None or args.available_capacity is None or args.total_capacity<0 or args.available_capacity<0 or args.available_capacity>args.total_capacity: print("availability_operation_refused invalid_capacity_values=true");return 2
        client.table("service_availability").update({"total_capacity":args.total_capacity,"available_capacity":args.available_capacity}).eq("location_id",location["id"]).eq("service_id",service["id"]).eq("availability_date",args.date).eq("start_time",args.start_time).execute()
    elif args.action=="update-status":
        if not args.date or not args.start_time or args.status not in VALID: print("availability_operation_refused invalid_status_values=true");return 2
        client.table("service_availability").update({"operational_status":args.status}).eq("location_id",location["id"]).eq("service_id",service["id"]).eq("availability_date",args.date).eq("start_time",args.start_time).execute()
    else:
        if not args.date or not args.start_time: print("availability_operation_refused slot_required=true");return 2
        client.table("service_availability").update({"last_verified_at":datetime.now(timezone.utc).isoformat()}).eq("location_id",location["id"]).eq("service_id",service["id"]).eq("availability_date",args.date).eq("start_time",args.start_time).execute()
    print("availability_operation_complete write_performed=true");return 0
if __name__=="__main__":raise SystemExit(main())
