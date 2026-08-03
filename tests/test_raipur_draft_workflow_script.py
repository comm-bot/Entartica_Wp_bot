from __future__ import annotations
from types import SimpleNamespace
from scripts.test_live_raipur_draft_workflow import run
def flags(**values):
 base=dict(raipur_inbound_orchestrator_enabled=True,raipur_draft_creation_enabled=True,raipur_draft_review_migration_ready=True,exotel_outbound_enabled=False);base.update(values);return SimpleNamespace(**base)
def test_dry_run_never_persists():
 code,lines=run(False,flags());assert code==0 and 'mode=dry_run' in lines and 'live_persistence=false' in lines and 'exotel_called=false' in lines
def test_live_confirmation_requires_all_gates_and_disabled_exotel():
 for key,value in [('raipur_inbound_orchestrator_enabled',False),('raipur_draft_creation_enabled',False),('raipur_draft_review_migration_ready',False),('exotel_outbound_enabled',True)]:
  code,lines=run(True,flags(**{key:value}));assert code==1 and 'configuration_ready=false' in lines
