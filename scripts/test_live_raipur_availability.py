"""Opt-in, marker-bound live availability provider verification with cleanup."""
from __future__ import annotations
import argparse
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import secrets
import sys
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.repositories.locations import LocationRepository
from app.repositories.services import ServiceRepository
from app.repositories.service_availability import ServiceAvailabilityRepository
from app.repositories.booking_enquiries import BookingEnquiryRepository
from app.repositories.customers import CustomerRepository
from app.repositories.conversations import ConversationRepository
from app.services.availability import AvailabilityRequest, SupabaseAvailabilityProvider
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
def _marker()->str:return f"local-controlled-availability-test-{secrets.token_hex(8)}"
def _rows(response:object)->list[dict[str,Any]]:
 data=getattr(response,"data",None);return data if isinstance(data,list) else [data] if isinstance(data,dict) else []
def run_live(client:Any)->dict[str,object]:
 marker=_marker();customer_id=None;conversation_id=None;created_customer=False;created_conversation=False;out={"schema_ready":False,"raipur_location_ready":False,"approved_service_ready":False,"fresh_available_verified":False,"full_slot_verified":False,"stale_slot_verified":False,"missing_slot_verified":False,"provider_failure_verified":False,"alternative_slots_verified":False,"booking_enquiry_status_verified":False,"cleanup_completed":False,"reason":"unexpected_database_error"}
 try:
  client.table("service_availability").select("location_id,service_id,availability_date,start_time,end_time,total_capacity,available_capacity,operational_status,last_verified_at,internal_note").limit(0).execute();out["schema_ready"]=True
  loc=LocationRepository(client).get_location_by_code("raipur")
  if not isinstance(loc,dict) or not isinstance(loc.get("id"),str):out["reason"]="raipur_location_missing";return out
  out["raipur_location_ready"]=True;svc=ServiceRepository(client).get_active_by_slug(loc["id"],"jet-ski")
  if not isinstance(svc,dict) or not isinstance(svc.get("id"),str):out["reason"]="approved_service_missing";return out
  out["approved_service_ready"]=True; day=date.today()+timedelta(days=14);now=datetime.now(timezone.utc)
  slots=[("10:00:00","11:00:00","available",5,5,now),("12:00:00","13:00:00","full",5,0,now),("14:00:00","15:00:00","available",5,5,now-timedelta(hours=2)),("16:00:00","17:00:00","limited",5,1,now)]
  for start,end,status,total,available,verified in slots:client.table("service_availability").insert({"location_id":loc["id"],"service_id":svc["id"],"availability_date":day.isoformat(),"start_time":start,"end_time":end,"total_capacity":total,"available_capacity":available,"operational_status":status,"last_verified_at":verified.isoformat(),"internal_note":marker}).execute()
  provider=SupabaseAvailabilityProvider(ServiceAvailabilityRepository(client),now=lambda:now)
  request=lambda value:AvailabilityRequest("Jet Ski",day.isoformat(),value,2,loc["id"],svc["id"],"Jet Ski")
  out["fresh_available_verified"]=provider.check(request("10:00:00")).status=="available";out["full_slot_verified"]=provider.check(request("12:00:00")).status=="not_available";out["stale_slot_verified"]=provider.check(request("14:00:00")).status=="stale";out["missing_slot_verified"]=provider.check(request("18:00:00")).status=="verification_required";out["alternative_slots_verified"]=provider.check(request("")).approved_alternatives==("10:00:00","16:00:00")
  class Fail: 
   def get_exact_slot(self,*_):raise RuntimeError()
  out["provider_failure_verified"]=SupabaseAvailabilityProvider(Fail(),now=lambda:now).check(request("10:00:00")).status=="provider_error"
  phone=f"+919002{secrets.randbelow(100_000_000):08d}";customer_repository=CustomerRepository(client)
  if customer_repository.get_by_whatsapp_number(phone) is not None:out["reason"]="controlled_customer_collision";return out
  customer=customer_repository.get_or_create(phone,"Controlled Availability Test");customer_id=customer.get("id") if isinstance(customer.get("id"),str) else None;created_customer=customer_id is not None
  conversation_repository=ConversationRepository(client)
  if not customer_id or conversation_repository.get_open(customer_id) is not None:out["reason"]="controlled_conversation_collision";return out
  conversation=conversation_repository.get_or_create_open(customer_id);conversation_id=conversation.get("id") if isinstance(conversation.get("id"),str) else None;created_conversation=conversation_id is not None
  details=BookingDetails("Controlled Availability Test","Jet Ski",day,time(10),2,0,2)
  booking=BookingEnquiryService(BookingEnquiryRepository(client),provider,ServiceRepository(client),availability_max_age=timedelta(minutes=30))
  result=booking.submit(details,customer_id=customer_id or "",conversation_id=conversation_id or "",location_id=loc["id"],source_message_id=marker,now=now)
  stored=BookingEnquiryRepository(client).get_by_source_message("whatsapp",marker);out["booking_enquiry_status_verified"]=result.availability_status=="available" and isinstance(stored,dict) and stored.get("availability_status")=="available" and stored.get("requested_service_id")==svc["id"]
  out["reason"]="completed";return out
 except Exception:out["reason"]="unexpected_database_error";return out
 finally:
  try:
   client.table("booking_enquiries").delete().eq("source","whatsapp").eq("source_message_id",marker).execute()
   if created_conversation and conversation_id:client.table("conversations").delete().eq("id",conversation_id).execute()
   if created_customer and customer_id:client.table("customers").delete().eq("id",customer_id).execute()
   client.table("service_availability").delete().eq("internal_note",marker).execute();out["cleanup_completed"]=not _rows(client.table("service_availability").select("id").eq("internal_note",marker).execute())
  except Exception:out["cleanup_completed"]=False
def main()->int:
 parser=argparse.ArgumentParser();parser.add_argument("--confirm-live-write",action="store_true");args=parser.parse_args()
 if not args.confirm_live_write:print("mode=dry_run live_write_performed=false whatsapp_sent=false exotel_called=false openai_called=false reason=dry_run");return 0
 settings=Settings()
 if not settings.supabase_url or not settings.supabase_secret_key:print("mode=live live_write_performed=false reason=configuration_missing");return 1
 result=run_live(get_supabase_client());print(" ".join(f"{key}={str(value).lower() if isinstance(value,bool) else value}" for key,value in {"mode":"live",**result,"whatsapp_sent":False,"exotel_called":False,"openai_called":False}.items()));return 0 if result["reason"]=="completed" and result["cleanup_completed"] else 1
if __name__=="__main__":raise SystemExit(main())
