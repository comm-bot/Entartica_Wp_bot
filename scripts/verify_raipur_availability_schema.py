"""Read-only safety check for migration 011 availability storage."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from app.integrations.supabase import get_supabase_client

def _rows(response: object) -> list[dict[str, Any]]:
    data=getattr(response,"data",None); return data if isinstance(data,list) else [data] if isinstance(data,dict) else []

def inspect_availability_schema(client: Any, *, now: datetime | None = None) -> dict[str, object]:
    base={"availability_table_ready":False,"raipur_location_ready":False,"active_services_count":0,"availability_rows":0,"fresh_slots":0,"stale_slots":0,"invalid_capacity_rows":0,"duplicate_slot_groups":0,"reason":"availability_table_missing"}
    try:
        locations=_rows(client.table("locations").select("id,is_active").eq("slug","raipur").execute())
    except Exception: base["reason"]="raipur_location_unavailable"; return base
    active=[row for row in locations if row.get("is_active") is True and isinstance(row.get("id"),str)]
    if len(active)!=1: base["reason"]="raipur_location_missing" if not active else "duplicate_raipur_locations_require_review"; return base
    base["raipur_location_ready"]=True; location_id=active[0]["id"]
    try:
        services=_rows(client.table("services").select("id").eq("location_id",location_id).eq("is_active",True).execute())
        rows=_rows(client.table("service_availability").select("service_id,availability_date,start_time,end_time,total_capacity,available_capacity,last_verified_at").eq("location_id",location_id).execute())
    except Exception: base["reason"]="availability_table_missing"; return base
    base["availability_table_ready"]=True; base["active_services_count"]=len(services); base["availability_rows"]=len(rows)
    threshold=(now or datetime.now(timezone.utc))-timedelta(minutes=30); groups:dict[tuple[object,...],int]={}
    for row in rows:
        key=tuple(row.get(k) for k in ("service_id","availability_date","start_time","end_time"));groups[key]=groups.get(key,0)+1
        if not isinstance(row.get("total_capacity"),int) or not isinstance(row.get("available_capacity"),int) or row["available_capacity"]<0 or row["available_capacity"]>row["total_capacity"]: base["invalid_capacity_rows"]+=1
        try:
            verified=datetime.fromisoformat(str(row.get("last_verified_at")).replace("Z","+00:00")); verified=verified if verified.tzinfo else verified.replace(tzinfo=timezone.utc)
            base["fresh_slots" if verified>=threshold else "stale_slots"]+=1
        except ValueError: base["stale_slots"]+=1
    base["duplicate_slot_groups"]=sum(1 for count in groups.values() if count>1)
    base["reason"]="ready" if not base["invalid_capacity_rows"] and not base["duplicate_slot_groups"] else "invalid_availability_rows"
    return base

def main()->int:
    result=inspect_availability_schema(get_supabase_client());print(" ".join(f"{key}={str(value).lower() if isinstance(value,bool) else value}" for key,value in result.items()));return 0 if result["reason"]=="ready" else 1
if __name__=="__main__": raise SystemExit(main())
