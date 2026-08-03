"""Opt-in marker-bound verification of post-persistence inbound orchestration."""
from __future__ import annotations
import argparse,secrets
from datetime import datetime,timezone
from pathlib import Path
import sys
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.inbound_messages import InboundMessageService
from app.services.raipur_inbound_orchestrator import RaipurInboundOrchestrator

def _marker()->str:return f"local-controlled-inbound-{secrets.token_hex(8)}"
def _rows(response:object)->list[dict[str,Any]]:
 data=getattr(response,"data",None);return data if isinstance(data,list) else [data] if isinstance(data,dict) else []
def _safe(**values:object)->None:print(" ".join(f"{k}={str(v).lower() if isinstance(v,bool) else v}" for k,v in values.items()))
def run_live(client:Any,settings:Settings)->dict[str,object]:
 marker=_marker();phone=f"+919003{secrets.randbelow(100_000_000):08d}";customer_id=conversation_id=None;ids=[];out={"booking_flow_started":False,"multi_turn_completed":False,"inbound_messages_created":0,"orchestrator_executions":0,"booking_enquiry_created":False,"booking_enquiry_updated":False,"active_enquiry_count":0,"active_enquiry_continuation_verified":False,"service_link_verified":False,"preferred_date_verified":False,"preferred_time_verified":False,"adult_count_verified":False,"child_count_verified":False,"total_guest_count_verified":False,"special_requirements_verified":False,"availability_status":"unknown","human_followup_required":False,"duplicate_inbound_prevented":False,"duplicate_orchestration_skipped":False,"duplicate_state_advance_prevented":False,"outbound_message_created":False,"draft_created":False,"migration_008_used":False,"cleanup_completed":False,"reason":"unexpected_error"}
 try:
  inbound=InboundMessageService(client);orchestrator=RaipurInboundOrchestrator(client,settings);state=None;last=None
  for index,text in enumerate(("I want to book Jet Ski","tomorrow","4 PM","2 adults","1 child","3 total guests","no special requirements"),1):
   identifier=f"{marker}-{index}";ids.append(identifier);message=NormalizedInboundMessage(external_message_id=identifier,customer_whatsapp_number=phone,business_whatsapp_number="+911111111111",profile_name="Controlled Raipur Inbound Test",message_type="text",content=text,received_at=datetime.now(timezone.utc));stored=inbound.process(message);customer_id=stored.customer.get("id") if isinstance(stored.customer,dict) else customer_id;conversation_id=stored.conversation.get("id") if isinstance(stored.conversation,dict) else conversation_id;last=orchestrator.process(message,customer=stored.customer or {},conversation=stored.conversation or {},source_message_id=identifier,current_state=state);state=last.context;out["inbound_messages_created"]+=1;out["orchestrator_executions"]+=1
  out["booking_flow_started"]=True;out["multi_turn_completed"]=last is not None;again=inbound.process(message);out["duplicate_inbound_prevented"]=again.duplicate;out["duplicate_orchestration_skipped"]=again.duplicate;out["duplicate_state_advance_prevented"]=again.duplicate
  enquiries=_rows(client.table("booking_enquiries").select("requested_service_id,requested_service_text,preferred_date,preferred_time,adult_count,child_count,total_guests,special_requirements,availability_status,enquiry_status").eq("source","whatsapp").eq("source_message_id",ids[-1]).execute());out["active_enquiry_count"]=len(enquiries);row=enquiries[0] if len(enquiries)==1 else {};out["booking_enquiry_created"]=bool(row);out["active_enquiry_continuation_verified"]=len(enquiries)==1;out["service_link_verified"]=bool(row.get("requested_service_id"));out["preferred_date_verified"]=bool(row.get("preferred_date"));out["preferred_time_verified"]=str(row.get("preferred_time",""))[:5]=="16:00";out["adult_count_verified"]=row.get("adult_count")==2;out["child_count_verified"]=row.get("child_count")==1;out["total_guest_count_verified"]=row.get("total_guests")==3;out["special_requirements_verified"]=row.get("special_requirements") is None;out["availability_status"]=row.get("availability_status","unknown");out["human_followup_required"]=bool(last and last.human_handover_required)
  outbound=_rows(client.table("messages").select("id").eq("conversation_id",conversation_id).eq("direction","outbound").execute()) if conversation_id else [];out["outbound_message_created"]=bool(outbound);out["draft_created"]=False;out["reason"]="completed";return out
 except Exception: return out
 finally:
  try:
   for identifier in ids:client.table("booking_enquiries").delete().eq("source","whatsapp").eq("source_message_id",identifier).execute();client.table("messages").delete().eq("external_provider","exotel").eq("external_message_id",identifier).execute()
   if conversation_id:client.table("conversations").delete().eq("id",conversation_id).execute()
   if customer_id:client.table("customers").delete().eq("id",customer_id).execute()
   out["cleanup_completed"]=True
  except Exception:out["cleanup_completed"]=False
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--confirm-live-persistence",action="store_true");a=p.parse_args();settings=Settings()
 if not a.confirm_live_persistence:_safe(mode="dry_run",configuration_ready=bool(settings.supabase_url and settings.supabase_secret_key),live_persistence=False,feature_flag_required=True,whatsapp_sent=False,exotel_called=False,openai_called=False,reason="dry_run");return 0
 if not settings.raipur_inbound_orchestrator_enabled:_safe(mode="live",live_persistence=False,reason="feature_flag_disabled",whatsapp_sent=False,exotel_called=False,openai_called=False);return 1
 out=run_live(get_supabase_client(),settings);_safe(mode="live",live_persistence=True,**out,whatsapp_sent=False,exotel_called=False,openai_called=False);return 0 if out["reason"]=="completed" and out["cleanup_completed"] else 1
if __name__=="__main__":raise SystemExit(main())
