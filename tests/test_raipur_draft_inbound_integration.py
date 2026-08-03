from __future__ import annotations
from types import SimpleNamespace
import pytest
from app.services.raipur_draft_integration import create_draft_after_orchestration
from tests.support.fake_outbound_drafts import FakeOutboundDraftRepository

def settings(**values):
 base=dict(raipur_draft_creation_enabled=True,raipur_draft_review_migration_ready=True,raipur_inbound_orchestrator_enabled=True,exotel_outbound_enabled=False);base.update(values);return SimpleNamespace(**base)
def orchestration(**values):
 base=dict(response_valid=True,human_handover_required=False,draft_text='safe suggested response',response_language='en',detected_intent='knowledge',template_key='information',safe_metadata={});base.update(values);return SimpleNamespace(**base)
def call(repo,**kwargs):
 return create_draft_after_orchestration(settings=kwargs.pop('settings',settings()),inbound_message=kwargs.pop('inbound',{'id':'inbound-1'}),customer={'id':'customer-1'},conversation={'id':'conversation-1'},orchestration=kwargs.pop('result',orchestration()),repository_factory=lambda:repo)

@pytest.mark.parametrize('override,reason',[({'raipur_inbound_orchestrator_enabled':False},'draft_feature_disabled'),({'raipur_draft_creation_enabled':False},'draft_feature_disabled'),({'raipur_draft_review_migration_ready':False},'migration_008_required')])
def test_gates_do_not_construct_repository(override,reason):
 repo=FakeOutboundDraftRepository();created=call(repo,settings=settings(**override));assert created.draft_saved is False and created.reason_code==reason and repo.create_attempts==0
def test_valid_inbound_creates_exactly_one_pending_draft_and_is_idempotent():
 repo=FakeOutboundDraftRepository();first=call(repo);second=call(repo)
 assert first.draft_saved and first.response_sent is False and first.draft_status=='pending_review'
 assert second.draft_saved is False and second.reason_code=='existing_draft' and repo.count_drafts_for_inbound_message('inbound-1')==1
def test_invalid_empty_and_missing_context_create_nothing():
 repo=FakeOutboundDraftRepository()
 assert call(repo,result=orchestration(response_valid=False)).reason_code=='invalid_response'
 assert call(repo,result=orchestration(draft_text=' ')).reason_code=='empty_response'
 assert call(repo,inbound=None).draft_saved is False
 assert repo.drafts_created==0
def test_repository_failure_is_safe_and_external_services_untouched():
 repo=FakeOutboundDraftRepository();repo.raise_next_create=True;result=call(repo)
 assert result.reason_code=='draft_repository_unavailable' and not result.draft_saved
 assert repo.exotel_called is False and repo.whatsapp_sent is False and repo.openai_called is False
 assert repo.network_calls==0 and repo.database_writes==0 and repo.reservations_created==0 and repo.capacity_changes==0 and repo.payment_actions==0 and repo.final_bookings_confirmed==0
