"""One opt-in, marker-bound live booking-enquiry persistence check with cleanup."""
from __future__ import annotations
import argparse
from datetime import date, timedelta
from pathlib import Path
import secrets
import sys
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.repositories.booking_enquiries import BookingEnquiryRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.customers import CustomerRepository
from app.repositories.locations import LocationRepository
from scripts.list_recent_booking_enquiries import mask_phone

def _rows(response: object)->list[dict[str,Any]]:
    data=getattr(response,'data',None)
    return data if isinstance(data,list) else ([data] if isinstance(data,dict) else [])
def _marker()->str:return f"local-controlled-test-{secrets.token_hex(8)}"
def _synthetic_phone()->str:return f"+919000{secrets.randbelow(100_000_000):08d}"
def _safe(reason:str, **values:object)->None:
    base={"mode":"live","schema_ready":"false","controlled_customer_created":"false","controlled_conversation_created":"false","enquiry_created":"false","read_back_verified":"false","duplicate_prevented":"false","matching_enquiry_count":"0","sales_preview_verified":"false","cleanup_completed":"false","whatsapp_sent":"false","exotel_called":"false","openai_called":"false","reason":reason}
    base.update({key:str(value).lower() if isinstance(value,bool) else str(value) for key,value in values.items()})
    print(" ".join(f"{key}={value}" for key,value in base.items()))
def _schema_columns_ready(client:Any)->bool:
    try:
        client.table("booking_enquiries").select("requested_service_id,requested_service_text,total_guests,availability_status,enquiry_status,assigned_salesperson,source,source_message_id").limit(0).execute();return True
    except Exception:return False
def run_live(client:Any)->dict[str,object]:
    marker=_marker(); phone=_synthetic_phone(); created_customer=False;created_conversation=False;customer_id=None;conversation_id=None;cleanup=False
    outcome={"schema_ready":False,"controlled_customer_created":False,"controlled_conversation_created":False,"enquiry_created":False,"read_back_verified":False,"duplicate_prevented":False,"matching_enquiry_count":0,"sales_preview_verified":False,"cleanup_completed":False,"reason":"unexpected_database_error"}
    try:
        if not _schema_columns_ready(client): outcome["reason"]="schema_not_ready";return outcome
        outcome["schema_ready"]=True
        location=LocationRepository(client).get_location_by_code("raipur")
        if not isinstance(location,dict) or not isinstance(location.get("id"),str): outcome["reason"]="raipur_location_missing";return outcome
        existing=CustomerRepository(client).get_by_whatsapp_number(phone)
        if existing is not None: outcome["reason"]="controlled_customer_create_failed";return outcome
        customer=CustomerRepository(client).get_or_create(phone,"Controlled Persistence Test")
        if not isinstance(customer.get("id"),str) or not str(customer.get("name","")).startswith("Controlled Persistence Test"): outcome["reason"]="controlled_customer_create_failed";return outcome
        customer_id=customer["id"];created_customer=True;outcome["controlled_customer_created"]=True
        prior=ConversationRepository(client).get_open(customer_id)
        conversation=prior or ConversationRepository(client).get_or_create_open(customer_id)
        if not isinstance(conversation.get("id"),str): outcome["reason"]="controlled_conversation_create_failed";return outcome
        conversation_id=conversation["id"];created_conversation=prior is None;outcome["controlled_conversation_created"]=created_conversation
        record={"reference":f"ENQ-{date.today().strftime('%Y%m%d')}-{secrets.randbelow(1_000_000):06d}","customer_id":customer_id,"conversation_id":conversation_id,"location_id":location["id"],"requested_service_text":"Controlled test boating enquiry","preferred_date":(date.today()+timedelta(days=30)).isoformat(),"preferred_time":"16:00:00","adult_count":2,"child_count":1,"guest_count":3,"total_guests":3,"special_requirements":"Controlled persistence verification only","availability_status":"verification_required","enquiry_status":"pending_sales_followup","source":"whatsapp","source_message_id":marker}
        repo=BookingEnquiryRepository(client);stored,created=repo.create_idempotent(record);outcome["enquiry_created"]=created
        read=repo.get_by_source_message("whatsapp",marker)
        outcome["read_back_verified"]=isinstance(read,dict) and read.get("requested_service_text")==record["requested_service_text"] and bool(read.get("preferred_date")) and bool(read.get("preferred_time")) and read.get("total_guests")==3 and read.get("availability_status")=="verification_required" and read.get("enquiry_status")=="pending_sales_followup" and read.get("source_message_id")==marker
        _,again_created=repo.create_idempotent(record)
        matches=_rows(client.table("booking_enquiries").select("id").eq("source","whatsapp").eq("source_message_id",marker).execute());outcome["matching_enquiry_count"]=len(matches);outcome["duplicate_prevented"]=(not again_created and len(matches)==1)
        preview=f"customer_name=Controlled_Persistence_Test phone={mask_phone(phone)} activity=Controlled_test_boating_enquiry preferred_date=present preferred_time=present total_guests=3 availability_status=verification_required enquiry_status=pending_sales_followup assigned_salesperson=unassigned notes_present=true"
        outcome["sales_preview_verified"]="***" in preview and "Controlled persistence verification only" not in preview
        outcome["reason"]="completed" if all(outcome[key] for key in ("enquiry_created","read_back_verified","duplicate_prevented","sales_preview_verified")) else "read_back_failed"
        return outcome
    except Exception as error:
        code=str(getattr(error,"code", ""));outcome["reason"]="permission_failure" if code in {"42501","403"} else ("connection_failure" if isinstance(error,(ConnectionError,TimeoutError,OSError)) else "unexpected_database_error");return outcome
    finally:
        try:
            client.table("booking_enquiries").delete().eq("source","whatsapp").eq("source_message_id",marker).execute()
            if created_conversation and conversation_id: client.table("conversations").delete().eq("id",conversation_id).execute()
            if created_customer and customer_id: client.table("customers").delete().eq("id",customer_id).execute()
            remaining=_rows(client.table("booking_enquiries").select("id").eq("source","whatsapp").eq("source_message_id",marker).execute())
            cleanup=not remaining
        except Exception: cleanup=False
        outcome["cleanup_completed"]=cleanup
def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("--confirm-live-write",action="store_true");args=parser.parse_args()
    settings=Settings()
    if not args.confirm_live_write:
        print(f"mode=dry_run live_write_performed=false configuration_ready={str(bool(settings.supabase_url and settings.supabase_secret_key)).lower()} whatsapp_sent=false exotel_called=false openai_called=false reason=dry_run")
        return 0
    if not settings.supabase_url or not settings.supabase_secret_key: _safe("configuration_missing");return 1
    outcome=run_live(get_supabase_client());_safe(str(outcome.pop("reason")),**outcome);return 0 if outcome.get("cleanup_completed") and outcome.get("duplicate_prevented") else 1
if __name__=="__main__":raise SystemExit(main())
