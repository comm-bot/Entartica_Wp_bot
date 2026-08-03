from dataclasses import dataclass
from typing import Literal
DraftStatus=Literal['pending_review','approved','rejected','sent','failed']
@dataclass(frozen=True)
class DraftCreateRequest:
 customer_id:str;conversation_id:str;related_inbound_message_id:str;content:str;language:str;action:str;template_key:str|None;human_handover_required:bool;response_valid:bool
@dataclass(frozen=True)
class DraftCreationResult:
 created:bool;status:DraftStatus|None;reason:str

DraftReviewDecision=Literal['approve','reject']

@dataclass(frozen=True)
class DraftReviewRequest:
 draft_id:str;decision:DraftReviewDecision;reviewer_note:str|None=None

@dataclass(frozen=True)
class SafeDraftListItem:
 draft_reference:str;customer_reference:str;draft_status:DraftStatus;language:str|None;action:str|None;template_key:str|None;human_handover_required:bool;response_valid:bool;created_at:str|None;reviewed_at:str|None;response_preview:str;reviewer_note_present:bool

@dataclass(frozen=True)
class SafeDraftDetail:
 internal_draft_id:str;item:SafeDraftListItem

@dataclass(frozen=True)
class DraftListRequest:
 status:DraftStatus|None=None;limit:int=20

@dataclass(frozen=True)
class DraftListResult:
 items:tuple[SafeDraftListItem,...];reason:str='ok'

@dataclass(frozen=True)
class DraftReviewResult:
 performed:bool;previous_status:DraftStatus|None;new_status:DraftStatus|None;reason:str
