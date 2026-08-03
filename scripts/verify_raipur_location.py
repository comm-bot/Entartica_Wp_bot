"""Read-only verification of the approved Raipur location record."""
from __future__ import annotations
from pathlib import Path
import sys
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.integrations.supabase import get_supabase_client

EXPECTED={"slug":"raipur","name":"Entartica Sea World Raipur","city":"Raipur","state":"Chhattisgarh"}
def _rows(response:object)->list[dict[str,Any]]:
    data=getattr(response,"data",None);return data if isinstance(data,list) else ([data] if isinstance(data,dict) else [])
def inspect_raipur_location(client:Any)->dict[str,object]:
    try:
        rows=_rows(client.table("locations").select("id,slug,name,city,state,is_active").execute())
    except Exception as error:
        code=str(getattr(error,"code", ""));reason="permission_failure" if code in {"42501","403"} else ("connection_failure" if isinstance(error,(ConnectionError,TimeoutError,OSError)) else "locations_table_missing")
        return {"locations_table_ready":False,"raipur_exists":False,"raipur_active":False,"matching_records":0,"required_fields_ready":False,"related_services_count":0,"reason":reason}
    matches=[row for row in rows if row.get("slug")=="raipur" or row.get("name")==EXPECTED["name"]]
    if len(matches)>1:return {"locations_table_ready":True,"raipur_exists":True,"raipur_active":False,"matching_records":len(matches),"required_fields_ready":False,"related_services_count":0,"reason":"duplicate_raipur_locations_require_review"}
    if not matches:return {"locations_table_ready":True,"raipur_exists":False,"raipur_active":False,"matching_records":0,"required_fields_ready":False,"related_services_count":0,"reason":"raipur_location_missing"}
    row=matches[0]; fields_ready=all(row.get(k)==v for k,v in EXPECTED.items()) and isinstance(row.get("id"),str)
    if not fields_ready:return {"locations_table_ready":True,"raipur_exists":True,"raipur_active":False,"matching_records":1,"required_fields_ready":False,"related_services_count":0,"reason":"existing_raipur_location_conflict"}
    try:
        services=_rows(client.table("services").select("id").eq("location_id",row["id"]).execute())
    except Exception: services=[]
    active=row.get("is_active") is True
    return {"locations_table_ready":True,"raipur_exists":True,"raipur_active":active,"matching_records":1,"required_fields_ready":True,"related_services_count":len(services),"reason":"ready" if active else "raipur_location_inactive"}
def main()->int:
    result=inspect_raipur_location(get_supabase_client())
    print(" ".join(f"{key}={str(value).lower() if isinstance(value,bool) else value}" for key,value in result.items()))
    return 0 if result["reason"]=="ready" else 1
if __name__=="__main__":raise SystemExit(main())
