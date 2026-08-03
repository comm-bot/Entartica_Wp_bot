"""No-network dependencies for the real Raipur conversation pilot."""
from datetime import UTC, datetime
from app.services.availability import AvailabilityResult
from app.services.raipur_conversation import KnowledgeDraft
class Availability:
 def __init__(self,status="verification_required"):self.status=status;self.calls=0
 def check(self,_):self.calls+=1;return AvailabilityResult(self.status,datetime(2026,7,21,tzinfo=UTC))
class Bookings:
 def __init__(self):self.rows={}
 def create_idempotent(self,row):
  if row["source_message_id"] in self.rows:return self.rows[row["source_message_id"]],False
  self.rows[row["source_message_id"]]=dict(row);return self.rows[row["source_message_id"]],True
class Services:
 def find_active_by_customer_text(self,_location,text):
  value=(text or "").casefold()
  return {"id":"service-jet","name":"Jet Ski"} if "jet ski" in value else None
class Knowledge:
 def answer(self,_):return KnowledgeDraft("Approved Raipur information is available.","controlled",.8,False)
class Drafts:
 def __init__(self):self.calls=0
 def create_outbound_draft(self,**_):self.calls+=1;return {},False
