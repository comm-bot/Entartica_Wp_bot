from __future__ import annotations

from app.schemas.outbound_drafts import DraftListRequest, DraftReviewRequest, DraftCreateRequest
from app.services.raipur_draft_review import RaipurDraftReviewService
from tests.support.fake_outbound_drafts import FakeOutboundDraftRepository


def request(inbound: str, *, valid: bool = True, content: str = "A short safe response") -> DraftCreateRequest:
 return DraftCreateRequest('customer-123456','conversation-1',inbound,content,'english','information',None,False,valid)

def draft(repository: FakeOutboundDraftRepository, inbound: str, **kwargs: object) -> str:
 repository.create_pending_draft(request(inbound,**kwargs));return repository.list_drafts()[0]['id']

def test_lists_each_status_newest_first_and_validates_request() -> None:
 repo=FakeOutboundDraftRepository();service=RaipurDraftReviewService(repo)
 pending=draft(repo,'one');approved=draft(repo,'two');repo.approve_draft(approved);rejected=draft(repo,'three');repo.reject_draft(rejected);sent=draft(repo,'four');repo.approve_draft(sent);repo.mark_sent(sent);failed=draft(repo,'five');repo.approve_draft(failed);repo.mark_failed(failed)
 assert service.list_drafts().items[0].draft_status=='failed'
 for status in ('pending_review','approved','rejected','sent','failed'):
  assert len(service.list_drafts(DraftListRequest(status,20)).items)==1
 assert service.list_drafts(DraftListRequest('bad',20)).reason=='invalid_request'
 assert service.list_drafts(DraftListRequest(None,0)).reason=='invalid_request'
 assert service.list_drafts(DraftListRequest(None,101)).reason=='invalid_request'
 assert pending

def test_safe_detail_masks_references_and_previews_content() -> None:
 repo=FakeOutboundDraftRepository();service=RaipurDraftReviewService(repo);draft_id=draft(repo,'one',content='  short\n response  ')
 item=service.get_draft(draft_id).item
 assert item.response_preview=='short response'
 assert item.draft_reference.startswith('draft_') and draft_id not in item.draft_reference
 assert item.customer_reference.startswith('customer_****_') and 'customer-123456' not in item.customer_reference
 assert '123456' not in str(item)
 long_id=draft(repo,'two',content='word '*40)
 assert service.get_draft(long_id).item.response_preview.endswith('…')
 assert len(service.get_draft(long_id).item.response_preview)==120

def test_review_rules_and_reviewer_note_safety() -> None:
 repo=FakeOutboundDraftRepository();service=RaipurDraftReviewService(repo)
 pending=draft(repo,'one');result=service.approve_draft(DraftReviewRequest(pending,'approve','  ok\x00\n now  '))
 assert result.performed and result.new_status=='approved'
 assert repo.get_draft_by_id(pending)['reviewer_note']=='ok now'
 assert service.reject_draft(DraftReviewRequest(pending,'reject','x'*600)).performed
 assert len(repo.get_draft_by_id(pending)['reviewer_note'])==500
 assert not service.approve_draft(DraftReviewRequest(pending,'approve')).performed
 invalid=draft(repo,'two',valid=False)
 assert not service.approve_draft(DraftReviewRequest(invalid,'approve')).performed
 assert service.reject_draft(DraftReviewRequest(invalid,'reject','\x00\t')).performed
 assert repo.get_draft_by_id(invalid)['reviewer_note'] is None
 sent=draft(repo,'three');repo.approve_draft(sent);repo.mark_sent(sent)
 failed=draft(repo,'four');repo.approve_draft(failed);repo.mark_failed(failed)
 assert not service.reject_draft(DraftReviewRequest(sent,'reject')).performed
 assert not service.approve_draft(DraftReviewRequest(failed,'approve')).performed
 assert not service.reject_draft(DraftReviewRequest(failed,'reject')).performed
 assert service.get_draft('missing') is None
 assert service.approve_draft(DraftReviewRequest('missing','approve')).reason=='draft_not_found'

def test_reviews_are_non_sending_and_use_only_fake_state() -> None:
 repo=FakeOutboundDraftRepository();service=RaipurDraftReviewService(repo);identifier=draft(repo,'one')
 assert service.reject_draft(DraftReviewRequest(identifier,'reject')).performed
 assert repo.exotel_called is False and repo.whatsapp_sent is False and repo.openai_called is False
 assert repo.network_calls==0 and repo.database_writes==0
 assert repo.reservations_created==0 and repo.capacity_changes==0 and repo.payment_actions==0 and repo.final_bookings_confirmed==0
