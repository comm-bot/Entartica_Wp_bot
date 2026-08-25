"""Feature-gated, post-persistence draft creation with no send capability."""
from __future__ import annotations
from dataclasses import dataclass
import logging
from typing import Any, Callable
from app.schemas.outbound_drafts import DraftCreateRequest
from app.services.raipur_drafts import RaipurDraftService
from app.services.latency import current_latency_trace

logger=logging.getLogger('uvicorn.error')
@dataclass(frozen=True)
class DraftIntegrationResult:
 orchestration_completed:bool;response_valid:bool;response_sent:bool=False;draft_creation_attempted:bool=False;draft_saved:bool=False;draft_status:str|None=None;human_handover_required:bool=False;reason_code:str='draft_feature_disabled'

def create_draft_after_orchestration(*,settings:Any,inbound_message:dict[str,Any]|None,customer:dict[str,Any]|None,conversation:dict[str,Any]|None,orchestration:Any,repository_factory:Callable[[],Any])->DraftIntegrationResult:
 response_valid=bool(getattr(orchestration,'response_valid',False));handover=bool(getattr(orchestration,'human_handover_required',False));text=getattr(orchestration,'draft_text','')
 base=dict(orchestration_completed=True,response_valid=response_valid,human_handover_required=handover)
 if not getattr(settings,'raipur_inbound_orchestrator_enabled',False):
  logger.info('draft_creation_feature_disabled');return DraftIntegrationResult(**base,reason_code='draft_feature_disabled')
 if not getattr(settings,'raipur_draft_creation_enabled',False):
  logger.info('draft_creation_feature_disabled');return DraftIntegrationResult(**base,reason_code='draft_feature_disabled')
 if not getattr(settings,'raipur_draft_review_migration_ready',False):
  logger.info('draft_creation_migration_blocked');return DraftIntegrationResult(**base,reason_code='migration_008_required')
 if not all(isinstance(value,dict) and isinstance(value.get('id'),str) for value in (inbound_message,customer,conversation)):
  return DraftIntegrationResult(**base,reason_code='invalid_inbound_context')
 if not response_valid:return DraftIntegrationResult(**base,reason_code='invalid_response')
 if not isinstance(text,str) or not text.strip():return DraftIntegrationResult(**base,reason_code='empty_response')
 metadata=getattr(orchestration,'safe_metadata',None) if isinstance(getattr(orchestration,'safe_metadata',None),dict) else {}
 interactive=metadata.get('interactive_message') if isinstance(metadata.get('interactive_message'),dict) else None
 media=metadata.get('media_message') if isinstance(metadata.get('media_message'),dict) else None
 template=metadata.get('template_message') if isinstance(metadata.get('template_message'),dict) else None
 package_metadata={key:metadata[key] for key in ('package_id','package_presentation_pending','approved_package','exact_kb_package_block','source_filename','source_heading','knowledge_location','media_sequence','document_message') if key in metadata}
 request=DraftCreateRequest(customer['id'],conversation['id'],inbound_message['id'],text,str(getattr(orchestration,'response_language','en')),str(getattr(orchestration,'detected_intent','unknown')),getattr(orchestration,'template_key',None),handover,response_valid,interactive,media,template,package_metadata or None)
 try:
  logger.info('draft_creation_started');result=RaipurDraftService(repository_factory(),enabled=True).create(request,inbound_persisted=True,duplicate=False,response_sent=False,draft_saved=False)
 except Exception:
  logger.error('draft_creation_failed_safe');return DraftIntegrationResult(**base,draft_creation_attempted=True,reason_code='draft_repository_unavailable')
 if result.created:
  if package_metadata:
   logger.info('package_content_draft_created package_id=%s media_present=%s',package_metadata.get('package_id','none'),media is not None)
   logger.info('package_actions_draft_created package_id=%s actions_present=%s',package_metadata.get('package_id','none'),interactive is not None)
  if (trace := current_latency_trace()) is not None:trace.event('draft_created')
  logger.info('draft_created');return DraftIntegrationResult(**base,draft_creation_attempted=True,draft_saved=True,draft_status='pending_review',reason_code='draft_created')
 if result.reason=='repository_unavailable':
  logger.error('draft_creation_failed_safe');return DraftIntegrationResult(**base,draft_creation_attempted=True,reason_code='draft_repository_unavailable')
 logger.info('draft_duplicate_skipped');return DraftIntegrationResult(**base,draft_creation_attempted=True,reason_code='existing_draft' if result.reason=='already_pending' else result.reason)
