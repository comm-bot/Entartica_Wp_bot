"""No-network local draft conversation runner; it never sends a WhatsApp message."""
from __future__ import annotations
import argparse
from datetime import UTC, datetime
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.booking_enquiries import BookingEnquiryService
from app.services.raipur_conversation import KnowledgeDraft, RaipurConversationService
from app.services.raipur_availability_provider import build_raipur_availability_provider
from app.repositories.services import ServiceRepository
from app.repositories.locations import LocationRepository
from app.integrations.supabase import get_supabase_client
from app.config import Settings

class DemoKnowledge:
    def answer(self, question: str) -> KnowledgeDraft:
        q=question.casefold()
        if "activit" in q: return KnowledgeDraft("Approved Raipur activities are available in the approved knowledge base.","raipur_faq.docx",.70,False)
        if "where" in q and "raipur" in q: return KnowledgeDraft("Approved Raipur location information is available.","raipur_location_information.docx",.70,False)
        return KnowledgeDraft(None)
class DemoBookingRepository:
    def __init__(self): self.records={}
    def create_idempotent(self, record):
        existing=self.records.get(record["source_message_id"])
        if existing:return existing,False
        self.records[record["source_message_id"]]=dict(record);return dict(record),True
class DemoDrafts:
    def __init__(self): self.records={}
    def create_outbound_draft(self, **kwargs):
        key=kwargs["related_inbound_message_id"]
        if key in self.records:return self.records[key],False
        self.records[key]=kwargs;return kwargs,True
def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--message",action="append",required=True); parser.add_argument("--availability-provider",choices=("unavailable","supabase"),default="unavailable"); args=parser.parse_args()
    settings=Settings(raipur_availability_provider=args.availability_provider); client=None; location_id="raipur-location"; services=None
    if args.availability_provider=="supabase":
        client=get_supabase_client(); location=LocationRepository(client).get_location_by_code("raipur")
        if not isinstance(location,dict) or not isinstance(location.get("id"),str): print("runner_failed reason=raipur_location_missing");return 1
        location_id=location["id"];services=ServiceRepository(client)
    provider=build_raipur_availability_provider(settings,client=client)
    drafts=DemoDrafts(); service=RaipurConversationService(knowledge=DemoKnowledge(),bookings=BookingEnquiryService(DemoBookingRepository(),provider,services),drafts=drafts,persist_drafts=False)
    state=None
    for index,text in enumerate(args.message,1):
        message=NormalizedInboundMessage(external_message_id=f"local-{index}",customer_whatsapp_number="+910000000000",business_whatsapp_number="+911111111111",profile_name="Local Customer",message_type="text",content=text,received_at=datetime.now(UTC))
        result=service.process(message,customer={"id":"local-customer","name":"Local Customer"},conversation={"id":"local-conversation","location_id":location_id},source_message_id=f"local-{index}",current_state=state)
        state=result.context
        safe=re.sub(r"\s+"," ",result.draft_text)[:180]
        print(f"action={result.action} draft={safe} intent={result.detected_intent} language={result.response_language} availability_status={result.availability_status or 'none'} alternatives_count=0 next_required_field={result.next_required_field or 'none'} enquiry_created={str(result.booking_enquiry_created).lower()} enquiry_updated={str(result.booking_enquiry_updated).lower()} human_handover_required={str(result.human_handover_required).lower()} reason_code={result.reason_code} provider_used={args.availability_provider} draft_saved=false")
    return 0
if __name__=="__main__": raise SystemExit(main())
