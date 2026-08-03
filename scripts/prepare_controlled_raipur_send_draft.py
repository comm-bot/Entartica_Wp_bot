"""Prepare a marker-bound approved draft only when explicitly authorized."""
from __future__ import annotations
import argparse,secrets
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dataclasses import dataclass
from datetime import datetime,timezone
from typing import Any

def marker() -> str: return f"controlled-raipur-send-{secrets.token_hex(12)}"
def synthetic_phone() -> str: return f"+919008{secrets.randbelow(100_000_000):08d}"

@dataclass(frozen=True)
class PreparationResult:
 marker: str; draft_id: str | None; draft_reference: str | None; response_valid: bool; reason: str; failed_stage: str|None=None
class PreparationStageError(Exception):
 def __init__(self,stage:str):self.stage=stage
class LivePreparationWorkflow:
 def __init__(self,settings,inbound,orchestrator,drafts,review,marker_value,phone):self.settings,self.inbound,self.orchestrator,self.drafts,self.review,self.marker,self.phone=settings,inbound,orchestrator,drafts,review,marker_value,phone
 def prepare(self,question:str)->dict[str,Any]:
  from app.schemas.exotel_webhook import NormalizedInboundMessage
  from app.schemas.outbound_drafts import DraftReviewRequest
  from app.services.raipur_draft_integration import create_draft_after_orchestration
  message=NormalizedInboundMessage(external_provider='exotel',external_message_id=self.marker,customer_whatsapp_number=self.phone,business_whatsapp_number='+911111111111',profile_name='Controlled Raipur Draft Test',message_type='text',content=question,received_at=datetime.now(timezone.utc))
  try:result=self.inbound.process(message)
  except Exception:raise PreparationStageError('inbound_message_create')
  if result.duplicate or not result.customer or not result.conversation or not result.inbound_message:raise PreparationStageError('inbound_message_create')
  try:out=self.orchestrator.process(message,customer=result.customer,conversation=result.conversation,source_message_id=self.marker)
  except Exception:raise PreparationStageError('orchestration')
  if not getattr(out,'response_valid',False) or not getattr(out,'draft_text',''):raise PreparationStageError('response_validation')
  created=create_draft_after_orchestration(settings=self.settings,inbound_message=result.inbound_message,customer=result.customer,conversation=result.conversation,orchestration=out,repository_factory=lambda:self.drafts)
  if not created.draft_saved:raise PreparationStageError('draft_create')
  draft=self.drafts.find_draft_for_inbound_message(result.inbound_message['id'])
  if not draft:raise PreparationStageError('draft_create')
  approved=self.review.approve_draft(DraftReviewRequest(draft['id'],'approve'))
  if not approved.performed:raise PreparationStageError('draft_approval')
  draft=self.drafts.get_draft_by_id(draft['id'])
  if not draft or draft.get('sent_at') or draft.get('external_message_id') or draft.get('draft_status')!='approved':raise PreparationStageError('final_verification')
  return {'id':draft['id'],'draft_reference':'draft_'+str(draft['id'])[:6],'draft_status':'approved','response_valid':True}

def build_live_preparation_workflow(dependencies, marker_value, phone):
 _,settings,inbound,orchestrator,drafts,review=dependencies
 return LivePreparationWorkflow(settings,inbound,orchestrator,drafts,review,marker_value,phone)

def build_live_preparation_dependencies():
 """Construct real persistence/orchestration dependencies only after confirmation."""
 from app.config import get_settings
 from app.integrations.supabase import get_supabase_client
 from app.services.inbound_messages import InboundMessageService
 from app.services.raipur_inbound_orchestrator import RaipurInboundOrchestrator
 from app.repositories.outbound_drafts import OutboundDraftRepository
 from app.services.raipur_draft_review import RaipurDraftReviewService
 from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
 client=get_supabase_client();settings=get_settings();provider=RaipurKnowledgeProvider(client,settings);drafts=OutboundDraftRepository(client)
 return client,settings,InboundMessageService(client),RaipurInboundOrchestrator(client,settings,knowledge_provider=provider),drafts,RaipurDraftReviewService(drafts)

def prepare(*, factory, marker_value: str | None = None) -> PreparationResult:
 """Run the injected real-service preparation sequence; no sender is involved."""
 value=marker_value or marker()
 try:
  workflow=factory(value,synthetic_phone())
  draft=workflow.prepare("Where is the Raipur location?")
  if not isinstance(draft,dict) or draft.get("draft_status")!='approved' or not draft.get("response_valid"):raise RuntimeError
  return PreparationResult(value,draft.get("id"),draft.get("draft_reference"),True,"ready")
 except PreparationStageError as error:return PreparationResult(value,None,None,False,"preparation_failed_cleanup_required",error.stage)
 except Exception:return PreparationResult(value,None,None,False,"preparation_failed_cleanup_required",'unknown')

def run_confirmed(*, builder=build_live_preparation_dependencies, workflow_factory=None) -> PreparationResult:
 value=marker()
 try:
  dependencies=builder()
  if workflow_factory is None: raise RuntimeError
  return prepare(factory=lambda marker_value,phone: workflow_factory(dependencies,marker_value,phone),marker_value=value)
 except PreparationStageError as error:return PreparationResult(value,None,None,False,'preparation_failed_cleanup_required',error.stage)
 except Exception:return PreparationResult(value,None,None,False,'preparation_failed_cleanup_required','dependency_build')

def cleanup_marker(marker_value: str, *, builder) -> tuple[bool,str,str]:
 """Delete only records reached from one exact provider/marker inbound row."""
 if not marker_value.strip(): return False,'marker_not_found','marker_lookup'
 stage='dependency_build'
 try:
  client=builder()
  stage='marker_lookup'
  response=(client.table('messages').select('id,conversation_id')
   .eq('external_provider','exotel').eq('external_message_id',marker_value).limit(1).execute())
  rows=getattr(response,'data',None)
  if not isinstance(rows,list) or not rows:return False,'marker_not_found','marker_lookup'
  inbound=rows[0]
  if not isinstance(inbound,dict) or not inbound.get('id') or not inbound.get('conversation_id'):
   return False,'cleanup_failed_safe','marker_lookup'
  inbound_id=str(inbound['id']); conversation_id=str(inbound['conversation_id'])
  stage='draft_delete'; client.table('messages').delete().eq('related_inbound_message_id',inbound_id).execute()
  stage='enquiry_delete'; client.table('booking_enquiries').delete().eq('source_message_id',marker_value).execute()
  stage='message_delete'; client.table('messages').delete().eq('id',inbound_id).execute()
  stage='conversation_delete'
  remaining_messages=client.table('messages').select('id').eq('conversation_id',conversation_id).limit(1).execute()
  remaining_message_rows=getattr(remaining_messages,'data',None)
  if not isinstance(remaining_message_rows,list): raise RuntimeError
  if remaining_message_rows: return True,'completed','none'
  conversation_response=client.table('conversations').select('customer_id').eq('id',conversation_id).limit(1).execute()
  conversation_rows=getattr(conversation_response,'data',None)
  if not isinstance(conversation_rows,list) or not conversation_rows:return True,'completed','none'
  customer_id=conversation_rows[0].get('customer_id') if isinstance(conversation_rows[0],dict) else None
  client.table('conversations').delete().eq('id',conversation_id).execute()
  if not customer_id:return True,'completed','none'
  stage='customer_delete'
  remaining_conversations=client.table('conversations').select('id').eq('customer_id',customer_id).limit(1).execute()
  remaining_conversation_rows=getattr(remaining_conversations,'data',None)
  if not isinstance(remaining_conversation_rows,list): raise RuntimeError
  if remaining_conversation_rows: return True,'completed','none'
  client.table('customers').delete().eq('id',customer_id).execute()
  stage='final_verification'
  return True,'completed','none'
 except Exception:return False,'cleanup_failed_safe',stage

def build_live_cleanup_dependencies():
 from app.integrations.supabase import get_supabase_client
 return get_supabase_client()
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--confirm-live-persistence',action='store_true');p.add_argument('--cleanup-marker');p.add_argument('--confirm-cleanup',action='store_true');a=p.parse_args(argv)
 if a.cleanup_marker or a.confirm_cleanup:
  if a.confirm_live_persistence: print('mode=cleanup\ncleanup_completed=false\nreason=invalid_mode');return 1
  if not a.cleanup_marker or not a.confirm_cleanup: print('mode=cleanup\ncleanup_completed=false\nreason=confirmation_required');return 1
  dependencies=build_live_cleanup_dependencies()
  ok,reason,stage=cleanup_marker(a.cleanup_marker,builder=lambda: dependencies)
  if ok: print('mode=cleanup\ncontrolled_drafts_remaining=0\ncontrolled_enquiries_remaining=0\ncontrolled_messages_remaining=0\ncontrolled_conversations_remaining=0\ncontrolled_customers_remaining=0\ncleanup_completed=true\nreason=completed');return 0
  print(f'mode=cleanup\ncleanup_completed=false\nrecords_deleted=false\ncleanup_failed_stage={stage}\nreason={reason}');return 1
 if not a.confirm_live_persistence:
  print('mode=dry_run\nlive_persistence=false\ndraft_created=false\nmessage_sent=false\nreason=dry_run');return 0
 result=run_confirmed(builder=build_live_preparation_dependencies,workflow_factory=build_live_preparation_workflow)
 if result.reason=='ready':
  print(f'mode=live\nmarker={result.marker}\ndraft_id={result.draft_id}\ndraft_reference={result.draft_reference}\ndraft_status=approved\nresponse_valid=true\nmessage_sent=false\nreason=ready');return 0
 print(f'mode=live\nmarker={result.marker}\ndraft_created=false\nmessage_sent=false\nfailed_stage={result.failed_stage or "unknown"}\nreason=preparation_failed_cleanup_required');return 1
if __name__=='__main__':raise SystemExit(main())
