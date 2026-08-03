from __future__ import annotations
import re
from types import SimpleNamespace
import scripts.prepare_controlled_raipur_send_draft as script
from scripts.prepare_controlled_raipur_send_draft import marker, prepare, synthetic_phone, run_confirmed, PreparationResult

class Flow:
 def __init__(self, marker_value, phone, fail=False):self.marker,self.phone,self.fail=marker_value,phone,fail;self.calls=[]
 def prepare(self, question):
  self.calls.append(question)
  if self.fail:raise RuntimeError('private failure')
  return {'id':'draft-1','draft_reference':'draft_masked','draft_status':'approved','response_valid':True}

def test_marker_and_synthetic_identity_are_safe_and_unique():
 assert marker()!=marker()
 assert re.fullmatch(r'\+[1-9][0-9]{7,14}',synthetic_phone())

def test_preparation_uses_controlled_question_and_returns_safe_ready_result():
 captured=[]
 def factory(value,phone):
  flow=Flow(value,phone);captured.append(flow);return flow
 result=prepare(factory=factory,marker_value='marker-1')
 assert result.marker=='marker-1' and result.draft_id=='draft-1' and result.response_valid and result.reason=='ready'
 assert captured[0].calls==['Where is the Raipur location?']
 assert 'phone' not in str(result).lower() and 'private' not in str(result)

def test_live_workflow_passes_normalized_message_to_orchestrator(monkeypatch):
    class Inbound:
        def process(self, message):
            self.message = message
            return SimpleNamespace(duplicate=False, customer={'id':'customer'}, conversation={'id':'conversation'}, inbound_message={'id':'inbound'})
    class Orchestrator:
        def process(self, message, **kwargs):
            self.message = message
            return SimpleNamespace(draft_text='grounded', response_valid=True)
    inbound, orchestrator = Inbound(), Orchestrator()
    drafts = SimpleNamespace(find_draft_for_inbound_message=lambda inbound_id: {'id':'draft'}, get_draft_by_id=lambda draft_id: {'id':'draft','draft_status':'approved','sent_at':None,'external_message_id':None})
    review = SimpleNamespace(approve_draft=lambda request: SimpleNamespace(performed=True))
    monkeypatch.setattr('app.services.raipur_draft_integration.create_draft_after_orchestration', lambda **_: SimpleNamespace(draft_saved=True))
    workflow = script.LivePreparationWorkflow(object(), inbound, orchestrator, drafts, review, 'marker', '+911234567890')
    result = workflow.prepare('Where is the Raipur location?')
    assert result['response_valid'] and orchestrator.message is inbound.message
    assert hasattr(orchestrator.message, 'content') and isinstance(orchestrator.message.content, str)

def test_failure_keeps_marker_and_hides_exception_details():
 result=prepare(factory=lambda marker_value,phone:Flow(marker_value,phone,True),marker_value='recoverable-marker')
 assert result.marker=='recoverable-marker' and result.reason=='preparation_failed_cleanup_required'
 assert 'private' not in str(result)

def test_confirmed_runner_calls_builder_once_and_keeps_safe_failure():
 calls=[]
 result=run_confirmed(builder=lambda: calls.append('builder') or object(),workflow_factory=lambda deps, value, phone: Flow(value,phone))
 assert calls==['builder'] and result.reason=='ready'
 failed=run_confirmed(builder=lambda: (_ for _ in ()).throw(RuntimeError('secret')))
 assert failed.reason=='preparation_failed_cleanup_required' and 'secret' not in str(failed)

def test_cli_confirmed_branch_uses_runner_once(monkeypatch,capsys):
 calls=[]
 def fake_runner(*,builder,workflow_factory):
  calls.append((builder,workflow_factory));return PreparationResult('marker','draft-1','draft_masked',True,'ready')
 monkeypatch.setattr(script,'run_confirmed',fake_runner)
 assert script.main(['--confirm-live-persistence'])==0
 assert calls==[(script.build_live_preparation_dependencies,script.build_live_preparation_workflow)] and 'draft_id=draft-1' in capsys.readouterr().out

def test_confirmed_runs_generate_fresh_markers():
 markers=[]
 def factory(deps,value,phone):
  markers.append(value);return Flow(value,phone)
 assert run_confirmed(builder=lambda: object(),workflow_factory=factory).reason=='ready'
 assert run_confirmed(builder=lambda: object(),workflow_factory=factory).reason=='ready'
 assert markers[0]!=markers[1] and all(value.startswith('controlled-raipur-send-') for value in markers)

def test_cleanup_cli_is_lazy_and_safe(monkeypatch,capsys):
 calls=[]
 monkeypatch.setattr(script,'build_live_cleanup_dependencies',lambda: calls.append('builder') or object())
 monkeypatch.setattr(script,'cleanup_marker',lambda marker,builder: calls.append(('cleanup',marker)) or (True,'completed','none'))
 assert script.main([])==0 and calls==[]
 assert script.main(['--cleanup-marker','marker'])==1 and calls==[]
 assert script.main(['--cleanup-marker','marker','--confirm-cleanup'])==0
 assert calls==['builder',('cleanup','marker')]
 out=capsys.readouterr().out
 assert 'cleanup_completed=true' in out and 'controlled_drafts_remaining=0' in out

def test_cleanup_cli_unknown_and_combined_modes_are_safe(monkeypatch,capsys):
 monkeypatch.setattr(script,'cleanup_marker',lambda marker,builder: (False,'marker_not_found','marker_lookup'))
 monkeypatch.setattr(script,'build_live_cleanup_dependencies',lambda: object())
 assert script.main(['--cleanup-marker','unknown','--confirm-cleanup'])==1
 output=capsys.readouterr().out
 assert 'records_deleted=false' in output and 'cleanup_failed_stage=marker_lookup' in output
 assert script.main(['--cleanup-marker','x','--confirm-cleanup','--confirm-live-persistence'])==1
 assert 'reason=invalid_mode' in capsys.readouterr().out

def test_preparation_stage_is_preserved():
 for stage in ('inbound_message_create','orchestration','response_validation','draft_create','draft_approval','final_verification'):
  result=script.prepare(factory=lambda *_: (_ for _ in ()).throw(script.PreparationStageError(stage)),marker_value='marker')
  assert result.failed_stage==stage

def test_run_confirmed_preserves_preparation_stages_and_safe_unknown():
 for stage in ('inbound_message_create','orchestration','response_validation','draft_create','draft_approval','final_verification'):
  class StageFlow:
   def prepare(self, question): raise script.PreparationStageError(stage)
  result=run_confirmed(builder=lambda: object(),workflow_factory=lambda *_: StageFlow())
  assert result.failed_stage==stage
 unexpected=run_confirmed(builder=lambda: object(),workflow_factory=lambda *_: (_ for _ in ()).throw(RuntimeError('private failure')))
 assert unexpected.failed_stage=='unknown' and 'private' not in str(unexpected)
 dependency_failure=run_confirmed(builder=lambda: (_ for _ in ()).throw(RuntimeError('private failure')),workflow_factory=lambda *_: Flow('m','+911234567890'))
 assert dependency_failure.failed_stage=='dependency_build' and 'private' not in str(dependency_failure)

def test_cleanup_marker_reports_each_safe_failure_stage():
 class Response:
  def __init__(self, data): self.data=data
 class Query:
  def __init__(self, client, table): self.client,self.name,self.action,self.filters=client,table,'select',[]
  def select(self, columns): return self
  def delete(self): self.action='delete'; return self
  def eq(self, key, value): self.filters.append((key,value)); return self
  def limit(self, value): return self
  def execute(self):
   filters=dict(self.filters)
   stage=(
    'marker_lookup' if self.name=='messages' and self.action=='select' and filters.get('external_provider')=='exotel' else
    'draft_delete' if self.action=='delete' and self.name=='messages' and 'related_inbound_message_id' in filters else
    'enquiry_delete' if self.action=='delete' and self.name=='booking_enquiries' else
    'message_delete' if self.action=='delete' and self.name=='messages' else
    'conversation_delete' if self.name=='conversations' and self.action=='delete' else
    'customer_delete' if self.name=='customers' and self.action=='delete' else 'lookup')
   self.client.calls.append((self.name,self.action,tuple(self.filters)))
   if self.client.fail_at==stage: raise RuntimeError('private database failure')
   if stage=='marker_lookup': return Response(self.client.lookup_rows)
   if self.name=='conversations' and self.action=='select' and filters.get('id')=='conversation-id':
    return Response([{'id':'conversation-id','customer_id':'customer-id'}])
   if self.action=='select': return Response([])
   return Response([])
 class Client:
  def __init__(self, fail_at=None, lookup_rows=None): self.fail_at,self.lookup_rows,self.calls=fail_at,lookup_rows if lookup_rows is not None else [{'id':'message-id','conversation_id':'conversation-id'}],[]
  def table(self, name): return Query(self,name)
 for stage in ('dependency_build','marker_lookup','draft_delete','enquiry_delete','message_delete','conversation_delete','customer_delete'):
  builder=(lambda: (_ for _ in ()).throw(RuntimeError('private database failure'))) if stage=='dependency_build' else lambda stage=stage: Client(stage)
  success, reason, failed_stage=script.cleanup_marker('marker',builder=builder)
  assert (success,reason,failed_stage)==(False,'cleanup_failed_safe',stage)

def test_cleanup_marker_uses_exact_supabase_lookup_and_response_data():
 class Response:
  def __init__(self, data): self.data=data
 class Query:
  def __init__(self, client, table): self.client,self.name,self.action,self.filters=client,table,'select',[]
  def select(self, columns): return self
  def delete(self): self.action='delete'; return self
  def eq(self, key, value): self.filters.append((key,value)); return self
  def limit(self, value): return self
  def execute(self):
   self.client.calls.append((self.name,self.action,tuple(self.filters)))
   filters=dict(self.filters)
   if self.name=='messages' and filters.get('external_provider')=='exotel': return Response([{'id':'message-id','conversation_id':'conversation-id'}])
   if self.name=='conversations' and self.action=='select' and filters.get('id')=='conversation-id': return Response([{'customer_id':'customer-id'}])
   return Response([])
 class Client:
  def __init__(self): self.calls=[]
  def table(self, name): return Query(self,name)
 client=Client()
 assert script.cleanup_marker('exact-marker',builder=lambda: client)==(True,'completed','none')
 assert client.calls[0]==('messages','select',(('external_provider','exotel'),('external_message_id','exact-marker')))
 assert ('messages','delete',(('related_inbound_message_id','message-id'),)) in client.calls
 assert ('booking_enquiries','delete',(('source_message_id','exact-marker'),)) in client.calls

def test_cleanup_marker_distinguishes_empty_and_lookup_error():
 class Response:
  def __init__(self, data): self.data=data
 class EmptyQuery:
  def select(self, columns): return self
  def eq(self, key, value): return self
  def limit(self, value): return self
  def execute(self): return Response([])
 class EmptyClient:
  def table(self, name): return EmptyQuery()
 assert script.cleanup_marker('marker',builder=EmptyClient)==(False,'marker_not_found','marker_lookup')
 class FailingQuery(EmptyQuery):
  def execute(self): raise RuntimeError('private supabase error')
 class FailingClient:
  def table(self, name): return FailingQuery()
 assert script.cleanup_marker('marker',builder=FailingClient)==(False,'cleanup_failed_safe','marker_lookup')

def test_cleanup_cli_prints_safe_stage_on_failure(monkeypatch,capsys):
 for stage in ('dependency_build','marker_lookup','draft_delete','enquiry_delete','message_delete','conversation_delete','customer_delete','final_verification','unknown'):
  monkeypatch.setattr(script,'build_live_cleanup_dependencies',lambda: object())
  monkeypatch.setattr(script,'cleanup_marker',lambda marker,builder,stage=stage: (False,'cleanup_failed_safe',stage))
  assert script.main(['--cleanup-marker','marker','--confirm-cleanup'])==1
  output=capsys.readouterr().out
  assert f'cleanup_failed_stage={stage}' in output
  assert 'private' not in output and 'message-id' not in output
