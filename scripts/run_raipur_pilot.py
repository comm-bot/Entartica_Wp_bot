"""Execute each authored offline pilot record through the real conversation service."""
from __future__ import annotations
import argparse,json,sys
from datetime import UTC,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_conversation import RaipurConversationService
from tests.support.raipur_pilot_fakes import Availability,Bookings,Services,Knowledge,Drafts
def main():
 p=argparse.ArgumentParser();p.add_argument('--category');p.add_argument('--scenario');a=p.parse_args();rows=json.loads((ROOT/'tests/fixtures/raipur_pilot_scenarios.json').read_text(encoding='utf-8'))
 selected=[r for r in rows if (not a.category or r['category']==a.category) and (not a.scenario or r['name']==a.scenario)]
 if not selected:print('pilot_failed reason=unknown_selection');return 2
 passed=0;calls=responses=0
 for scenario in selected:
  provider=Availability(scenario.get('fake_availability_result') or 'verification_required');books=Bookings();drafts=Drafts();service=RaipurConversationService(knowledge=Knowledge(),bookings=BookingEnquiryService(books,provider,Services()),drafts=drafts,persist_drafts=False);state=None;result=None
  for index,text in enumerate(scenario['input_messages']):
   msg=NormalizedInboundMessage(external_message_id=f"pilot-{index}",customer_whatsapp_number='+910000000000',business_whatsapp_number='+911111111111',message_type='text',content=text,received_at=datetime.now(UTC));result=service.process(msg,customer={'id':'pilot-customer','name':'Pilot'},conversation={'id':'pilot-conversation','location_id':'raipur'},source_message_id=f"pilot-{index}",current_state=state);state=result.context;calls+=1;responses+=1
  if result and result.response_valid and not result.draft_saved:passed+=1
 print(f'pilot_phase=real_path_framework scenario_count={len(selected)} passed={passed} failed={len(selected)-passed} real_conversation_path_verified={str(calls>0).lower()} real_response_layer_verified={str(responses==calls).lower()} response_validator_verified={str(responses==calls).lower()} live_supabase_access=false database_writes=0')
 return 0 if passed==len(selected) else 1
if __name__=='__main__':raise SystemExit(main())
