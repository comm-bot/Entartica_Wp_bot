from __future__ import annotations

from app.schemas.outbound_drafts import DraftCreateRequest
from app.services.raipur_draft_review import RaipurDraftReviewService
from scripts.list_raipur_drafts import run as list_run
from scripts.review_raipur_draft import run as review_run
from tests.support.fake_outbound_drafts import FakeOutboundDraftRepository

def service_and_id() -> tuple[FakeOutboundDraftRepository,RaipurDraftReviewService,str]:
 repo=FakeOutboundDraftRepository();record=DraftCreateRequest('customer-1','conversation-1','inbound-1','safe response','english','information',None,False,True);row,_=repo.create_pending_draft(record);return repo,RaipurDraftReviewService(repo),row['id']

def test_listing_arguments_safe_output_and_migration_gate() -> None:
 repo,service,_=service_and_id()
 code,lines=list_run(None,20,migration_ready=False)
 assert code==1 and lines[-1]=='reason=migration_008_required'
 code,lines=list_run(None,20,migration_ready=True,service_factory=lambda:service)
 output='\n'.join(lines)
 assert code==0 and 'draft_list_complete' in output and 'write_performed=false' in output
 assert 'customer-1' not in output and 'safe response' in output
 assert list_run(None,0,migration_ready=True)[0]==2
 assert repo.database_writes==0

def test_review_defaults_to_dry_run_and_confirmed_actions_only_update_fake() -> None:
 repo,service,draft_id=service_and_id()
 code,lines=review_run(draft_id,'approve',None,False,migration_ready=True,service_factory=lambda:service)
 assert code==0 and 'mode=dry_run' in lines and repo.get_draft_by_id(draft_id)['draft_status']=='pending_review'
 code,lines=review_run(draft_id,'approve',None,True,migration_ready=True,service_factory=lambda:service)
 assert code==0 and 'review_update_performed=true' in lines and repo.get_draft_by_id(draft_id)['draft_status']=='approved'
 code,lines=review_run(draft_id,'reject','note',True,migration_ready=True,service_factory=lambda:service)
 assert code==0 and 'new_status=rejected' in lines
 code,lines=review_run('missing','approve',None,False,migration_ready=False)
 assert code==0 and 'mode=dry_run' in lines and 'message_sent=false' in lines
 assert repo.exotel_called is False and repo.whatsapp_sent is False and repo.openai_called is False
