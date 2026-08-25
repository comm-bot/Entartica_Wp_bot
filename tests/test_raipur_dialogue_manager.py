"""Fake-only dialogue-manager regressions for contextual Raipur messages."""
from __future__ import annotations
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingEnquiryService
from app.services.booking_enquiries import BookingDetails
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft, RaipurConversationService
from app.services.raipur_dialogue_planner import RaipurDialoguePlanner
from app.services.raipur_inbound_orchestrator import _context_to_record, _context_from_record, _is_stale_greeting

class K:
 def answer(self,_):return KnowledgeDraft(None)
 def answer_service_details(self,_,name):return KnowledgeDraft(f"{name} approved details.","approved.md",.8,False)
class S:
 def list_active_for_location(self,_):return [{"name":"Kayak","slug":"kayak","is_active":True},{"name":"Pontoon Boat","slug":"pontoon-boat","is_active":True},{"name":"Bumper Boat","slug":"bumper-boat","is_active":True},{"name":"Staycation Combo","slug":"staycation-combo","is_active":True}]
 def find_active_by_customer_text(self,*_):return None
class B:
 def create_idempotent(self,x):return x,True
class A:
 def check(self,_):return AvailabilityResult("verification_required",safe_reason_code="availability_unverified")
class D:
 def create_outbound_draft(self,**_):return {},False
def service():
 s=S();return RaipurConversationService(knowledge=K(),bookings=BookingEnquiryService(B(),A(),s),drafts=D(),services=s,location={"id":"raipur"},persist_drafts=False)
def msg(text):return NormalizedInboundMessage(external_message_id="id",customer_whatsapp_number="+910000000000",business_whatsapp_number="+911111111111",message_type="text",content=text,received_at=datetime.now(UTC))
def go(s,text,state=None):return s.process(msg(text),customer={"id":"c"},conversation={"id":"v","location_id":"raipur"},source_message_id="id",current_state=state)

def test_definition_list_language_and_service_correction_are_structured():
 s=service();kayak=go(s,"Kayak kya hai?")
 assert kayak.detected_intent=="service_overview" and "kayak approved details" in kayak.draft_text.casefold()
 hindi=go(s,"Hindi mein bolo",kayak.context);assert hindi.response_language=="hi"
 listing=go(s,"Konsi services available hain?",hindi.context);assert listing.detected_intent=="service_catalogue" and listing.action=="answer_information"
 pontoon=go(s,"Actually main Pontoon Boat ke baare mein jaanna chahta hoon",listing.context)
 assert pontoon.context.last_service_code=="pontoon_boat" and pontoon.detected_intent=="generic_service_definition"

def test_yes_binds_to_immediately_pending_service_not_old_context():
 s=service();pending=ConversationContext(BookingDetails(None,"Pontoon Boat",None,None,None,None,None),last_service_name="Pontoon Boat",last_service_code="pontoon_boat",pending_question_type="yes_no",pending_action="provide_service_details",pending_service_code="pontoon_boat")
 yes=go(s,"Haan",pending)
 assert yes.detected_intent=="service_detail" and "Pontoon Boat" in yes.draft_text and "Kayak" not in yes.draft_text

def test_restricted_and_live_availability_routes_remain_first():
 s=service()
 assert go(s,"Pontoon Boat ka price kya hai?").detected_intent=="pricing"
 assert go(s,"I want to book Pontoon Boat").detected_intent=="booking"
 assert go(s,"Kal Pontoon Boat available hai?").detected_intent=="availability"

def test_context_round_trip_preserves_pending_question_and_language():
 s=service();state=ConversationContext(BookingDetails(None,"Pontoon Boat",None,None,None,None,None),last_service_name="Pontoon Boat",last_service_code="pontoon_boat",pending_question_type="yes_no",pending_action="provide_service_details",pending_service_code="pontoon_boat")
 state=go(s,"Hindi mein bolo",state).context
 record=_context_to_record(state);restored,expired=_context_from_record(record,120)
 assert not expired and restored.pending_action=="provide_service_details" and restored.preferred_language=="hi"

def test_planner_rejects_unvalidated_llm_action_names():
 planner=RaipurDialoguePlanner(lambda _:{"intent":"send_money","answer_mode":"anything","language":"en"})
 plan=planner.plan("hello",ConversationContext(BookingEnquiryService.__annotations__ and None),language="en")
 assert plan.intent=="greeting"

def test_planner_routes_contact_request_without_llm_or_stale_service():
 calls=[]
 planner=RaipurDialoguePlanner(lambda request: calls.append(request) or None)
 context=SimpleNamespace(last_service_code="houseboat_celebration",pending_action=None)
 plan=planner.plan("Can you send me their number?",context,language="en")
 assert plan.intent=="contact_information" and plan.service_code is None

def test_stale_greeting_resets_session_and_pending_ampm_keeps_date():
 record={"updated_at":(datetime.now(UTC)-timedelta(minutes=31)).isoformat(),"service_name":"Kayak","service_code":"kayak"}
 assert _is_stale_greeting(record,"Hi",30)
 s=service();state=ConversationContext(BookingDetails(None,"Pontoon Boat",date(2026,8,13),None,None,None,None),pending_field="preferred_time",availability_requested=True,pending_question_type="am_pm",pending_action="verify_live_availability",pending_service_code="pontoon_boat",pending_slots={"date":"2026-08-13","time":"09:00","meridiem":None})
 result=go(s,"9 PM",state)
 assert result.context.details.preferred_date==date(2026,8,13) and result.context.details.preferred_time.hour==21

def test_explicit_booking_uses_sales_handover_without_collecting_details():
 s=service()
 first=go(s,"I want to book Jet Ski Ride")
 assert first.reason_code=="booking_sales_handover"
 assert first.context.pending_field is None
 assert "+91 94296 91418" in first.draft_text
 assert "what date" not in first.draft_text.casefold()
