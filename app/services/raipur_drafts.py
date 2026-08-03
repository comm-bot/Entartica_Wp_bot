"""Feature-gated, validated draft creation without any outbound send path."""
from app.schemas.outbound_drafts import DraftCreateRequest,DraftCreationResult
class RaipurDraftService:
 def __init__(self,repository,*,enabled:bool):self._repository=repository;self._enabled=enabled
 def create(self,request:DraftCreateRequest,*,inbound_persisted:bool,duplicate:bool,response_sent:bool,draft_saved:bool)->DraftCreationResult:
  if not self._enabled:return DraftCreationResult(False,None,'feature_disabled')
  if not inbound_persisted or duplicate or response_sent or draft_saved or not request.response_valid or not request.content.strip():return DraftCreationResult(False,None,'draft_not_eligible')
  try:record,created=self._repository.create_pending_draft(request)
  except Exception:return DraftCreationResult(False,None,'repository_unavailable')
  if not created and not record:return DraftCreationResult(False,None,'repository_unavailable')
  return DraftCreationResult(created,'pending_review' if created else None,'created' if created else 'already_pending')
