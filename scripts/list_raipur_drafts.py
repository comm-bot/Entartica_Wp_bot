"""Read-only, migration-gated listing of Raipur outbound drafts."""
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
from app.schemas.outbound_drafts import DraftListRequest
from app.services.raipur_draft_review import RaipurDraftReviewService

STATUSES=('pending_review','approved','rejected','sent','failed')
def _service()->RaipurDraftReviewService:return RaipurDraftReviewService(OutboundDraftRepository(get_supabase_client()))
def parser()->argparse.ArgumentParser:
 p=argparse.ArgumentParser();p.add_argument('--status',choices=STATUSES);p.add_argument('--limit',type=int,default=20);return p
def run(status:str|None,limit:int,*,migration_ready:bool,service_factory:Callable[[],RaipurDraftReviewService]=_service)->tuple[int,list[str]]:
 if not 1<=limit<=100:return 2,['reason=invalid_limit','operation_performed=false']
 if not migration_ready:return 1,['migration_ready=false','operation_performed=false','reason=migration_008_required']
 try:result=service_factory().list_drafts(DraftListRequest(status,limit))
 except Exception:return 1,['migration_ready=true','operation_performed=false','reason=repository_unavailable']
 if result.reason!='ok':return 1,['migration_ready=true','operation_performed=false',f'reason={result.reason}']
 lines=[]
 for item in result.items:
  lines.append(f'draft_reference={item.draft_reference} customer_reference={item.customer_reference} created_at={item.created_at or "unknown"} language={item.language or "unknown"} action={item.action or "unknown"} template_key={item.template_key or "none"} human_handover_required={str(item.human_handover_required).lower()} response_valid={str(item.response_valid).lower()} draft_status={item.draft_status} response_preview={item.response_preview} reviewer_note_present={str(item.reviewer_note_present).lower()}')
 lines.extend([f'draft_list_complete status={status or "all"} count={len(result.items)} limit={limit}','write_performed=false','exotel_called=false','whatsapp_sent=false','openai_called=false'])
 return 0,lines
def main(argv:list[str]|None=None)->int:
 args=parser().parse_args(argv);code,lines=run(args.status,args.limit,migration_ready=get_settings().raipur_draft_review_migration_ready)
 print('\n'.join(lines));return code
if __name__=='__main__':raise SystemExit(main())
