"""Dry-run-by-default Raipur draft reviewer; this script never sends a message."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
from typing import Callable
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.config import get_settings
from app.integrations.supabase import get_supabase_client
from app.repositories.outbound_drafts import OutboundDraftRepository
from app.schemas.outbound_drafts import DraftReviewRequest
from app.services.raipur_draft_review import RaipurDraftReviewService

def _service()->RaipurDraftReviewService:return RaipurDraftReviewService(OutboundDraftRepository(get_supabase_client()))
def parser()->argparse.ArgumentParser:
 p=argparse.ArgumentParser();p.add_argument('--draft-id',required=True);p.add_argument('--decision',choices=('approve','reject'),required=True);p.add_argument('--note');p.add_argument('--confirm-review',action='store_true');return p
def run(draft_id:str,decision:str,note:str|None,confirm:bool,*,migration_ready:bool,service_factory:Callable[[],RaipurDraftReviewService]=_service)->tuple[int,list[str]]:
 # Dry mode deliberately avoids client construction when migration is unavailable.
 if not confirm and not migration_ready:return 0,['mode=dry_run','draft_reference=unknown','current_status=unknown',f'requested_decision={decision}','transition_valid=false','review_update_performed=false','message_sent=false','reason=migration_008_required']
 if not migration_ready:return 1,['migration_ready=false','operation_performed=false','reason=migration_008_required']
 try:service=service_factory();detail=service.get_draft(draft_id)
 except Exception:return 1,['mode=dry_run' if not confirm else 'mode=confirmed_review','review_update_performed=false','message_sent=false','reason=repository_unavailable']
 reference=detail.item.draft_reference if detail else 'unknown';status=detail.item.draft_status if detail else 'unknown'
 if not confirm:
  valid=bool(detail and ((decision=='approve' and status=='pending_review' and detail.item.response_valid) or (decision=='reject' and status in {'pending_review','approved'})))
  return 0,['mode=dry_run',f'draft_reference={reference}',f'current_status={status}',f'requested_decision={decision}',f'transition_valid={str(valid).lower()}','review_update_performed=false','message_sent=false',f'reason={"would_review" if valid else "transition_not_allowed"}']
 result=service.approve_draft(DraftReviewRequest(draft_id,'approve',note)) if decision=='approve' else service.reject_draft(DraftReviewRequest(draft_id,'reject',note))
 return (0 if result.performed else 1),['mode=confirmed_review',f'draft_reference={reference}',f'previous_status={result.previous_status or "unknown"}',f'new_status={result.new_status or "unknown"}',f'review_update_performed={str(result.performed).lower()}','message_sent=false','exotel_called=false','whatsapp_sent=false','openai_called=false',f'reason={result.reason}']
def main(argv:list[str]|None=None)->int:
 args=parser().parse_args(argv);code,lines=run(args.draft_id,args.decision,args.note,args.confirm_review,migration_ready=get_settings().raipur_draft_review_migration_ready);print('\n'.join(lines));return code
if __name__=='__main__':raise SystemExit(main())
