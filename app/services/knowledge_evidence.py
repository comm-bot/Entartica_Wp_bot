"""Deterministic concept-coverage evidence for Raipur knowledge retrieval."""
from __future__ import annotations
from dataclasses import dataclass
import re
from app.services.knowledge_intent import KnowledgeIntentResult

STOP={"what","where","how","is","are","the","at","in","available","tell","please","a","an","of","for","to","me","information","details","raipur"}
GROUPS={
"location":{"location","located","address","venue","site","map","directions","timing","hours","opening","closing"},
"services":{"activity","service","ride","boating","water activity","watersports","adventure","attraction","daycation","staycation","celebration","package","experience"},
"booking":{"booking","reservation","enquiry","confirmation","availability","advance","pricing","quotation","payment","cancellation","refund","reschedule"},
"safety":{"safety","rule","guideline","restriction","child","age","jacket","medical","pregnancy","alcohol","weather","supervision"}}
ALIASES={"activities":"activity","services":"service","timings":"timing","operating":"hours","children":"child","kids":"child","prices":"pricing","rates":"pricing","price":"pricing","quote":"quotation","book":"booking","inquiry":"enquiry","confirmed":"confirmation","rides":"activity","watersport":"watersports","suspension":"weather","rescheduling":"reschedule"}

@dataclass(frozen=True)
class EvidenceResult:
 matched_query_terms:tuple[str,...]; matched_document_terms:tuple[str,...]; matched_phrase_count:int; matched_keyword_count:int; evidence_score:float; has_sufficient_evidence:bool; reason_code:str
 query_concept_count:int=0; matched_concept_count:int=0; synonym_match_count:int=0; metadata_only_match:bool=False

def lexical_evidence(question:str,content:str,intent:KnowledgeIntentResult,minimum:float)->EvidenceResult:
 if intent.human_handover_required:return EvidenceResult((),(),0,0,0,False,"unsupported_location")
 group=GROUPS.get(intent.intent,set()); qt,qsyn=_concepts(question,group); dt,dsyn=_concepts(content,group)
 matched=qt&dt; phrases=sum(1 for p in ("operating hours","advance booking","bad weather","life jacket","water activity") if p in _norm(question) and p in _norm(content))
 coverage=len(matched)/max(len(qt),1); score=min(1.0,coverage*.7+phrases*.3)
 sufficient=bool(matched) and (phrases>0 or coverage>=.3)
 if sufficient:reason="sufficient_phrase_match" if phrases else "sufficient_keyword_match"
 elif not qt:reason="category_only_match"
 else:reason="weak_lexical_match" if dt else "no_lexical_match"
 return EvidenceResult(tuple(sorted(qt)),tuple(sorted(matched)),phrases,len(matched),score,score>=minimum and sufficient,reason,len(qt),len(matched),qsyn+dsyn,False)
def _norm(v:str)->str:return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9 ]"," ",v.casefold())).strip()
def _concepts(v:str,group:set[str])->tuple[set[str],int]:
 raw=_norm(v).split(); result=set(); syn=0
 for word in raw:
  if word in STOP:continue
  canon=ALIASES.get(word,word); syn+=canon!=word
  if canon in group:result.add(canon)
 return result,syn
