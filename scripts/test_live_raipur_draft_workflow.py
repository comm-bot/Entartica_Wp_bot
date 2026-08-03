"""Opt-in, marker-bound live Raipur draft persistence verification; never sends."""
from __future__ import annotations
import argparse,secrets
from datetime import datetime,timezone
from pathlib import Path
import sys
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.config import get_settings
from app.integrations.supabase import get_supabase_client
from app.repositories.outbound_drafts import OutboundDraftRepository
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.schemas.outbound_drafts import DraftReviewRequest
from app.services.inbound_messages import InboundMessageService
from app.services.raipur_draft_integration import create_draft_after_orchestration
from app.services.raipur_draft_review import RaipurDraftReviewService
from app.services.raipur_inbound_orchestrator import RaipurInboundOrchestrator

def _rows(response:object)->list[dict[str,Any]]:
 data=getattr(response,'data',None);return data if isinstance(data,list) else [data] if isinstance(data,dict) else []
def _marker()->str:return f'controlled-raipur-draft-{secrets.token_hex(8)}'
def _phone()->str:return f'+919009{secrets.randbelow(100_000_000):08d}'
def _lines(out:dict[str,object])->list[str]:
 keys=('mode','configuration_ready','migration_ready','live_persistence','customer_created','conversation_created','inbound_created','orchestrator_executed','response_valid','draft_created','draft_status','duplicate_inbound_prevented','duplicate_draft_prevented','draft_approved','message_sent','cleanup_completed','exotel_called','whatsapp_sent','openai_called','reason')
 return [f'{key}={str(out.get(key,"unknown")).lower() if isinstance(out.get(key),bool) else out.get(key,"unknown")}' for key in keys]
def _base(reason:str)->dict[str,object]:return {'mode':'live','configuration_ready':False,'migration_ready':False,'live_persistence':False,'customer_created':False,'conversation_created':False,'inbound_created':False,'orchestrator_executed':False,'response_valid':False,'draft_created':False,'draft_status':'unknown','duplicate_inbound_prevented':False,'duplicate_draft_prevented':False,'draft_approved':False,'message_sent':False,'cleanup_completed':False,'exotel_called':False,'whatsapp_sent':False,'openai_called':False,'reason':reason}
def run_live(client:Any,settings:Any)->dict[str,object]:
 marker=_marker();external_id=f'{marker}-inbound';phone=_phone();customer_id=conversation_id=inbound_id=draft_id=None;out=_base('unexpected_database_error');out.update(configuration_ready=True,migration_ready=True,live_persistence=True)
 try:
  message=NormalizedInboundMessage(external_message_id=external_id,customer_whatsapp_number=phone,business_whatsapp_number='+911111111111',profile_name='Controlled Raipur Draft Test',message_type='text',content='I want to book Jet Ski',received_at=datetime.now(timezone.utc))
  inbound=InboundMessageService(client);stored=inbound.process(message)
  if stored.duplicate or not stored.customer or not stored.conversation or not stored.inbound_message:out['reason']='inbound_persistence_failed';return out
  customer_id=stored.customer['id'];conversation_id=stored.conversation['id'];inbound_id=stored.inbound_message['id'];out.update(customer_created=True,conversation_created=True,inbound_created=True)
  orchestration=RaipurInboundOrchestrator(client,settings).process(message,customer=stored.customer,conversation=stored.conversation,source_message_id=external_id)
  out.update(orchestrator_executed=True,response_valid=bool(orchestration.response_valid))
  draft_result=create_draft_after_orchestration(settings=settings,inbound_message=stored.inbound_message,customer=stored.customer,conversation=stored.conversation,orchestration=orchestration,repository_factory=lambda:OutboundDraftRepository(client))
  out.update(draft_created=draft_result.draft_saved,draft_status=draft_result.draft_status or 'unknown')
  if not draft_result.draft_saved:out['reason']=draft_result.reason_code;return out
  draft_rows=_rows(client.table('messages').select('id,draft_status,sent_at,draft_metadata,conversation_id,related_inbound_message_id,content').eq('related_inbound_message_id',inbound_id).eq('generated_by','raipur_draft_orchestrator').execute())
  if len(draft_rows)!=1 or not draft_result.draft_saved:out['reason']='draft_verification_failed';return out
  draft=draft_rows[0];draft_id=draft['id'];meta=draft.get('draft_metadata') if isinstance(draft.get('draft_metadata'),dict) else {}
  if not (draft.get('draft_status')=='pending_review' and draft.get('sent_at') is None and draft.get('conversation_id')==conversation_id and bool(draft.get('content')) and bool(meta.get('response_valid')) and bool(meta.get('language')) and bool(meta.get('action'))):out['reason']='draft_verification_failed';return out
  again=inbound.process(message);out['duplicate_inbound_prevented']=again.duplicate;out['duplicate_draft_prevented']=again.duplicate and len(_rows(client.table('messages').select('id').eq('related_inbound_message_id',inbound_id).eq('generated_by','raipur_draft_orchestrator').execute()))==1
  approval=RaipurDraftReviewService(OutboundDraftRepository(client)).approve_draft(DraftReviewRequest(draft_id,'approve'))
  checked=OutboundDraftRepository(client).get_draft_by_id(draft_id);out['draft_approved']=approval.performed and isinstance(checked,dict) and checked.get('draft_status')=='approved' and checked.get('sent_at') is None and checked.get('reviewed_at') is not None;out['draft_status']='approved' if out['draft_approved'] else 'pending_review';out['reason']='completed' if out['duplicate_inbound_prevented'] and out['duplicate_draft_prevented'] and out['draft_approved'] else 'verification_failed';return out
 except Exception:return out
 finally:
  try:
   if draft_id:client.table('messages').delete().eq('id',draft_id).execute()
   client.table('booking_enquiries').delete().eq('source','whatsapp').eq('source_message_id',external_id).execute()
   client.table('messages').delete().eq('external_provider','exotel').eq('external_message_id',external_id).execute()
   if conversation_id:client.table('conversations').delete().eq('id',conversation_id).execute()
   if customer_id:client.table('customers').delete().eq('id',customer_id).execute()
   out['cleanup_completed']=not _rows(client.table('messages').select('id').eq('external_provider','exotel').eq('external_message_id',external_id).execute())
  except Exception:out['cleanup_completed']=False
def run(confirm:bool,settings=None,client=None)->tuple[int,list[str]]:
 settings=settings or get_settings();ready=all((settings.raipur_inbound_orchestrator_enabled,settings.raipur_draft_creation_enabled,settings.raipur_draft_review_migration_ready,not settings.exotel_outbound_enabled))
 if not confirm:return 0,['mode=dry_run',f'configuration_ready={str(ready).lower()}','live_persistence=false','migration_required=true','draft_created=false','draft_approved=false','duplicate_draft_prevented=false','cleanup_completed=false','exotel_called=false','whatsapp_sent=false','openai_called=false','reason=dry_run']
 if not ready:return 1,['mode=live','configuration_ready=false','live_persistence=false','reason=configuration_required']
 out=run_live(client or get_supabase_client(),settings);return (0 if out['reason']=='completed' and out['cleanup_completed'] else 1),_lines(out)
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--confirm-live-persistence',action='store_true');a=p.parse_args(argv);code,lines=run(a.confirm_live_persistence);print('\n'.join(lines));return code
if __name__=='__main__':raise SystemExit(main())
