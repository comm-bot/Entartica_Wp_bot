from datetime import UTC, date, datetime, time
from pathlib import Path
from unittest.mock import MagicMock

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService

class Knowledge:
    def answer(self, question): return KnowledgeDraft("Approved answer.","safe.docx",.8,False) if "activities" in question.casefold() else KnowledgeDraft(None)
class Provider:
    def __init__(self,status): self.status=status; self.calls=0
    def check(self,request): self.calls+=1; return AvailabilityResult(self.status,datetime(2026,7,21,tzinfo=UTC))
class Bookings:
    def __init__(self):self.rows={}
    def create_idempotent(self,row):
        if row['source_message_id'] in self.rows:return self.rows[row['source_message_id']],False
        self.rows[row['source_message_id']]=dict(row);return dict(row),True
class Drafts:
    def __init__(self):self.rows={}
    def create_outbound_draft(self,**kwargs):
        key=kwargs['related_inbound_message_id']
        if key in self.rows:return self.rows[key],False
        self.rows[key]=kwargs;return kwargs,True
def message(text,id='m1'):
    return NormalizedInboundMessage(external_message_id=id,customer_whatsapp_number='+910000000000',business_whatsapp_number='+911111111111',message_type='text',content=text,received_at=datetime(2026,7,21,tzinfo=UTC))
def service(status='verification_required'):
    drafts=Drafts(); provider=Provider(status); return RaipurConversationService(knowledge=Knowledge(),bookings=BookingEnquiryService(Bookings(),provider),drafts=drafts),drafts,provider
def ctx(): return {'customer':{'id':'c','name':'Mandip'},'conversation':{'id':'v','location_id':'raipur'}}

def test_priority_unsupported_pricing_handover_and_information():
    s,_,_=service()
    assert s.process(message('What activities are available in Indore?'),source_message_id='1',**ctx()).action=='unsupported_location_handover'
    assert s.process(message('What is the price for activities?'),source_message_id='2',**ctx()).action=='pricing_sales_handover'
    assert s.process(message('What activities are available?'),source_message_id='3',**ctx()).action=='answer_information'
def test_availability_uses_provider_only_and_stale_is_not_available_claim():
    s,_,provider=service('available')
    result=s.process(message('Is Jet Ski available tomorrow?'),source_message_id='a',**ctx())
    assert result.action=='check_availability' and provider.calls==0
    assert result.availability_status=='verification_required'
    unrelated=s.process(message('What flights are available tomorrow?','flight'),source_message_id='flight',**ctx())
    assert unrelated.reason_code=='clarification_required'
def test_explicit_booking_uses_sales_handover_without_creating_an_enquiry():
    s,_,provider=service()
    result=s.process(message('I want to make a booking'),source_message_id='booking',**ctx())
    assert result.reason_code=='booking_sales_handover';assert result.human_handover_required
    assert result.context.pending_field is None and provider.calls==0


def test_explicit_booking_does_not_start_pending_name_collection():
    s, _, _ = service()
    customer, conversation = {"id":"c","name":None}, {"id":"v","location_id":"raipur"}
    first = s.process(message("I want to book Aqua Cycle", "book"), customer=customer, conversation=conversation, source_message_id="book")
    assert first.next_required_field is None
    assert first.context.pending_field is None
    assert first.reason_code == "booking_sales_handover"


def test_pricing_requires_consent_before_collecting_enquiry_and_twin_seater_is_ambiguous():
    s, _, _ = service()
    priced = s.process(message("What is the price for Aqua Cycle", "price"), source_message_id="price", **ctx())
    assert priced.context.pending_field is None and priced.context.pending_action == "start_booking_enquiry"
    ambiguous = s.process(message("What is the price for twin seater", "twin"), source_message_id="twin", **ctx())
    assert ambiguous.detected_intent == "clarification" and ambiguous.context.last_service_name is None
def test_ambiguous_time_and_past_date_need_clarification_for_legacy_pending_state():
    from app.services.booking_enquiries import BookingDetails
    from app.services.raipur_conversation import ConversationContext
    s,_,_=service();state=ConversationContext(BookingDetails('Mandeep','boating',None,None,None,None,None),pending_field='preferred_date')
    state=s.process(message('25 July 2020'),source_message_id='z',current_state=state,now=datetime(2026,7,21,tzinfo=UTC),**ctx()).context
    assert state.pending_field=='preferred_date'
    assert s.process(message('4'),source_message_id='t',current_state=state,**ctx()).next_required_field=='preferred_date'
def test_draft_idempotency_language_and_no_outbound_dependencies():
    s,drafts,_=service(); hindi=s.process(message('Raipur mein kya activities hain?'),source_message_id='same',**ctx()); duplicate=s.process(message('Raipur mein kya activities hain?'),source_message_id='same',**ctx())
    devanagari=s.process(message('Raipur में activities क्या हैं?','hindi'),source_message_id='hindi',**ctx())
    assert hindi.response_language=='hinglish';assert devanagari.response_language=='hi';assert hindi.draft_saved;assert not duplicate.draft_saved;assert len(drafts.rows)==2
    source=(Path(__file__).resolve().parents[1]/'app/services/raipur_conversation.py').read_text(encoding='utf-8').casefold()
    assert 'app.integrations.exotel' not in source and 'send_whatsapp' not in source and 'chat.completions' not in source
