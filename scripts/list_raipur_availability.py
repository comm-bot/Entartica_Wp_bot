from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.repositories.locations import LocationRepository
from app.repositories.services import ServiceRepository
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--service");p.add_argument("--date");p.add_argument("--status");p.add_argument("--stale-only",action="store_true");p.add_argument("--limit",type=int,default=25);a=p.parse_args();client=get_supabase_client();loc=LocationRepository(client).get_location_by_code("raipur")
 if not isinstance(loc,dict):print("availability_report_failed reason=raipur_location_missing");return 1
 q=client.table("service_availability").select("service_id,availability_date,start_time,end_time,operational_status,last_verified_at").eq("location_id",loc["id"])
 if a.date:q=q.eq("availability_date",a.date)
 if a.status:q=q.eq("operational_status",a.status)
 rows=getattr(q.order("availability_date").limit(min(max(a.limit,1),100)).execute(),"data",[]) or [];services={r["id"]:r for r in ServiceRepository(client).list_active_for_location(loc["id"])};threshold=datetime.now(timezone.utc)-timedelta(minutes=Settings().availability_max_age_minutes);count=0
 for row in rows:
  try:fresh=datetime.fromisoformat(row["last_verified_at"].replace("Z","+00:00"))>=threshold
  except Exception:fresh=False
  if a.stale_only and fresh:continue
  name=services.get(row.get("service_id"),{}).get("name","unknown");print(f"service_name={name} date={row.get('availability_date')} start_time={row.get('start_time')} end_time={row.get('end_time')} operational_status={row.get('operational_status')} freshness={'fresh' if fresh else 'stale'}");count+=1
 print(f"availability_report_complete row_count={count}");return 0
if __name__=="__main__":raise SystemExit(main())
