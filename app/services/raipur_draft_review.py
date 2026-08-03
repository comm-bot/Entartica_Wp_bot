"""Non-sending Raipur draft review service."""
from __future__ import annotations

from hashlib import sha256
import logging
import re
from typing import Any, Protocol

from app.schemas.outbound_drafts import (
    DraftListRequest, DraftListResult, DraftReviewRequest, DraftReviewResult,
    SafeDraftDetail, SafeDraftListItem,
)

logger = logging.getLogger("uvicorn.error")
_STATUSES = {"pending_review", "approved", "rejected", "sent", "failed"}

class OutboundDraftReviewRepository(Protocol):
 def list_drafts(self,status:str|None=None,limit:int=20)->list[dict[str,Any]]: ...
 def get_draft_by_id(self,draft_id:str)->dict[str,Any]|None: ...
 def approve_draft(self,draft_id:str,reviewer_note:str|None=None)->bool: ...
 def reject_draft(self,draft_id:str,reviewer_note:str|None=None)->bool: ...

def _token(value:object,prefix:str)->str:
 digest=sha256(str(value or '').encode()).hexdigest()
 return f'{prefix}_{digest[:6]}'

def _preview(value:object)->str:
 value=' '.join(str(value or '').split())
 return value if len(value)<=120 else value[:119]+'…'

def _note(value:str|None)->str|None:
 if value is None:return None
 value=re.sub(r'[\x00-\x1f\x7f]',' ',value)
 return ' '.join(value.split())[:500] or None

def _item(draft:dict[str,Any])->SafeDraftListItem:
 meta=draft.get('draft_metadata') if isinstance(draft.get('draft_metadata'),dict) else {}
 status=draft.get('draft_status')
 return SafeDraftListItem(
  draft_reference=_token(draft.get('id'),'draft'),customer_reference=_token(draft.get('customer_id'),'customer_****'),
  draft_status=status if status in _STATUSES else 'pending_review',language=meta.get('language') if isinstance(meta.get('language'),str) else None,
  action=meta.get('action') if isinstance(meta.get('action'),str) else None,template_key=meta.get('template_key') if isinstance(meta.get('template_key'),str) else None,
  human_handover_required=bool(meta.get('human_handover_required')),response_valid=bool(meta.get('response_valid')),
  created_at=draft.get('created_at') if isinstance(draft.get('created_at'),str) else None,reviewed_at=draft.get('reviewed_at') if isinstance(draft.get('reviewed_at'),str) else None,
  response_preview=_preview(draft.get('content')),reviewer_note_present=bool(_note(draft.get('reviewer_note')) if isinstance(draft.get('reviewer_note'),str) else None))

class RaipurDraftReviewService:
 def __init__(self,repository:OutboundDraftReviewRepository):self._repository=repository
 def list_drafts(self,request:DraftListRequest=DraftListRequest())->DraftListResult:
  if request.status is not None and request.status not in _STATUSES or not 1<=request.limit<=100:return DraftListResult((),"invalid_request")
  try: rows=self._repository.list_drafts(request.status,request.limit)
  except Exception:
   logger.error('draft_list_failed_safe');return DraftListResult((),"repository_unavailable")
  return DraftListResult(tuple(_item(row) for row in rows if isinstance(row,dict)))
 def get_draft(self,draft_id:str)->SafeDraftDetail|None:
  try:draft=self._repository.get_draft_by_id(draft_id)
  except Exception:
   logger.error('draft_review_failed_safe');return None
  return SafeDraftDetail(draft_id,_item(draft)) if isinstance(draft,dict) else None
 def approve_draft(self,request:DraftReviewRequest)->DraftReviewResult:
  return self._review(request,'approve')
 def reject_draft(self,request:DraftReviewRequest)->DraftReviewResult:
  return self._review(request,'reject')
 def _review(self,request:DraftReviewRequest,decision:str)->DraftReviewResult:
  if request.decision!=decision:return DraftReviewResult(False,None,None,'invalid_decision')
  try:draft=self._repository.get_draft_by_id(request.draft_id)
  except Exception:
   logger.error('draft_review_failed_safe');return DraftReviewResult(False,None,None,'repository_unavailable')
  if not isinstance(draft,dict):return DraftReviewResult(False,None,None,'draft_not_found')
  status=draft.get('draft_status')
  meta=draft.get('draft_metadata') if isinstance(draft.get('draft_metadata'),dict) else {}
  allowed=(decision=='approve' and status=='pending_review' and bool(meta.get('response_valid'))) or (decision=='reject' and status in {'pending_review','approved'} and not (status=='approved' and draft.get('sent_at') is not None))
  if not allowed:
   logger.warning('draft_review_refused action=%s',decision);return DraftReviewResult(False,status if status in _STATUSES else None,None,'transition_not_allowed')
  note=_note(request.reviewer_note)
  try:updated=self._repository.approve_draft(request.draft_id,note) if decision=='approve' else self._repository.reject_draft(request.draft_id,note)
  except Exception:
   logger.error('draft_review_failed_safe');return DraftReviewResult(False,status,None,'repository_unavailable')
  if not updated:return DraftReviewResult(False,status,None,'transition_not_allowed')
  logger.info('draft_approved' if decision=='approve' else 'draft_rejected')
  return DraftReviewResult(True,status,'approved' if decision=='approve' else 'rejected','reviewed')
