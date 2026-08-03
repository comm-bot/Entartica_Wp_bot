"""Fail-closed approved Raipur retrieval adapter."""
from app.rag.retrieval import embed_query,retrieve_candidates,KnowledgeRetrievalError
from app.services.raipur_answers import compose_customer_response,compose_venue_overview,generate_raipur_answer
from app.services.raipur_conversation import KnowledgeDraft
from app.services.raipur_services import approved_service_from_message, knowledge_service_code
from app.services.latency import latency_stage
class RaipurKnowledgeProvider:
 def __init__(self,client,settings,*,embed_query_fn=embed_query,retrieve_candidates_fn=retrieve_candidates,answer_generator=generate_raipur_answer,min_confidence=None):self.client,self.settings,self.embed,self.retrieve,self.generate=client,settings,embed_query_fn,retrieve_candidates_fn,answer_generator;self.minimum=min_confidence if min_confidence is not None else settings.raipur_knowledge_min_confidence
 def answer(self,question): return self._answer(question)
 def answer_venue_overview(self,question): return self._venue_overview(question)
 def answer_service_details(self,question,service_name,service_code=None,*,full_overview=False,detail_mode='overview'): return self._answer(question,service_name=service_name,service_code=service_code,full_overview=full_overview,detail_mode=detail_mode)
 def fallback_context(self,question):
  """Return bounded excerpts from active, approved Raipur rows only."""
  try:
   vector=self.embed(question,self.settings);rows=self.retrieve(self.client,vector,limit=3)
   return tuple(row['content'][:800] for row in rows if isinstance(row,dict) and isinstance(row.get('content'),str) and row['content'].strip() and isinstance(row.get('source_filename'),str) and row.get('metadata',{}).get('location_code','raipur')=='raipur')
  except Exception:return ()
 def _answer(self,question,service_name=None,service_code=None,full_overview=False,detail_mode='overview'):
  try:
   # Exact-service questions retain their full normalized wording.  A larger
   # candidate pool prevents another service's globally higher score from
   # excluding the requested service before local isolation is applied.
   with latency_stage('query_embedding'):vector=self.embed(question,self.settings)
   with latency_stage('Supabase_vector_search'):rows=self.retrieve(self.client,vector,limit=1000 if service_name else 5)
   minimum=min(self.minimum,.50) if service_name else self.minimum
   if service_name:
    approved=approved_service_from_message(service_name)
    canonical_code=service_code or (knowledge_service_code(approved) if approved is not None else service_name.casefold().replace(' ', '_').replace("'", ''))
    with latency_stage('knowledge_reranking'):
     named=[r for r in rows if _is_approved_raipur_row(r,-1.0) and r.get('metadata',{}).get('service_code') == canonical_code and r.get('metadata',{}).get('retrieval_priority') == 'service_specific']
     semantic=[r for r in named if float(r['confidence'])>=minimum]
     rows=_rank_service_rows(semantic or _exact_service_keyword_fallback(named,question),question,detail_mode=detail_mode)
     if detail_mode=='duration': rows=[row for row in rows if _is_duration_heading(row)]
   else:
    with latency_stage('knowledge_reranking'):rows=[r for r in rows if _is_approved_raipur_row(r,minimum)]
   if not rows:return KnowledgeDraft(None,None,None,True)
   best=rows[0] if service_name else max(rows,key=lambda r:float(r['confidence']))
   evidence=_service_overview_evidence(rows,question,full_overview=full_overview,detail_mode=detail_mode) if service_name else best['content']
   with latency_stage('OpenAI_answer_generation'):answer=self.generate({'content':evidence,'source_filename':best['source_filename'],'score':best['confidence'],'question':question},low_confidence=False)
   # The production generator is the single customer-response composition
   # boundary.  Injectable test generators may deliberately return raw
   # evidence, which still needs the normal safety composition path.
   with latency_stage('answer_validation'):customer_answer=(answer.answer.strip() if self.generate is generate_raipur_answer and isinstance(answer.answer,str) and answer.answer.strip() else compose_customer_response(answer.answer,question=question) if isinstance(answer.answer,str) else None)
   heading=best.get('metadata',{}).get('section_heading') if isinstance(best.get('metadata',{}),dict) else None
   document_id=best.get('knowledge_document_id')
   headings=tuple(dict.fromkeys(str((row.get('metadata') or {}).get('section_heading')).strip() for row in rows if isinstance((row.get('metadata') or {}).get('section_heading'),str) and str((row.get('metadata') or {}).get('section_heading')).strip()))
   return KnowledgeDraft(customer_answer,best['source_filename'],float(best['confidence']),not bool(customer_answer),heading if isinstance(heading,str) else None,len(rows),document_id if isinstance(document_id,str) and document_id.strip() else None,headings)
  except Exception:return KnowledgeDraft(None,None,None,True)

 def _venue_overview(self,question):
  """Retrieve only active, approved, customer-facing Raipur general knowledge."""
  try:
   with latency_stage('query_embedding'): vector=self.embed(question,self.settings)
   with latency_stage('Supabase_vector_search'): rows=self.retrieve(self.client,vector,limit=1000)
   with latency_stage('knowledge_reranking'):
    general=[row for row in rows if _is_approved_raipur_row(row,self.minimum) and _is_raipur_general_row(row)]
    rows=sorted(general,key=lambda row: (_venue_heading_priority(row),-float(row['confidence'])))
   if not rows:return KnowledgeDraft(None,None,None,True)
   best=rows[0]
   evidence='\n'.join(row['content'] for row in rows[:4] if isinstance(row.get('content'),str))
   answer=compose_venue_overview(evidence)
   if not answer:return KnowledgeDraft(None,None,None,True)
   metadata=best.get('metadata',{}) if isinstance(best.get('metadata'),dict) else {}
   heading=metadata.get('section_heading')
   document_id=best.get('knowledge_document_id')
   headings=tuple(dict.fromkeys(str((row.get('metadata') or {}).get('section_heading')).strip() for row in rows if isinstance((row.get('metadata') or {}).get('section_heading'),str) and str((row.get('metadata') or {}).get('section_heading')).strip()))
   return KnowledgeDraft(answer,best['source_filename'],float(best['confidence']),False,heading if isinstance(heading,str) else None,len(rows),document_id if isinstance(document_id,str) and document_id.strip() else None,headings)
  except Exception:return KnowledgeDraft(None,None,None,True)


def _exact_service_keyword_fallback(rows,question):
 """Rank only active, already-isolated service chunks when semantic scoring is weak."""
 aliases={"pregnent":"pregnan","pregnency":"pregnan","pragnant":"pregnan","pregnant":"pregnan","pregnancy":"pregnan","children":"child"}
 ignored={"can","women","woman","ride","riding","during","with","what","which","about","suitable","required","allowed","participate","participation","jet","ski","the","and","for","are","is"}
 terms={aliases.get(token,token) for token in __import__('re').findall(r"[a-z]+",question.casefold()) if len(token)>2}
 terms-=ignored
 scored=[]
 for row in rows:
  metadata=row.get('metadata',{}) if isinstance(row,dict) else {}
  haystack=(str(metadata.get('section_heading',''))+' '+str(row.get('content',''))).casefold()
  score=sum(term in haystack for term in terms)
  if score:scored.append((score,float(row.get('confidence',-1)),row))
 return [max(scored,key=lambda item:(item[0],item[1]))[2]] if scored else []


def _rank_service_rows(rows,question,*,detail_mode='overview'):
 """Prefer approved overview sections over comparison-only evidence."""
 value=question.casefold()
 comparison=any(term in value for term in ('compare','comparison','difference','versus',' vs '))
 inclusion=any(term in value for term in ('include','included','breakfast','children','swimming','how long','timing'))
 topic_headings={
  'capacity':('capacity','group size','number of guests','seating capacity','participants'),
  'duration':('duration','session duration','ride duration','experience duration','activity duration'),
  'swimming_requirement':('swimming requirement','participation','safety'),
  'swimming':('swimming requirement','participation','safety'),
  'inclusions':('what is included','included','inclusion','package','key characteristic','general experience'),
  'eligibility':('participation','suitable for','safety','restriction'),
  'operating_hours':('operating hours','timing','hours'),
  'safety':('safety','life jacket','participation'),
  'how_it_works':('how it works','how it generally works','ride experience','general experience'),
 }
 def priority(row):
  heading=str((row.get('metadata') or {}).get('section_heading','')).casefold()
  if detail_mode=='duration':
   return 0 if _is_duration_heading(row) else 9
  if detail_mode in topic_headings:
   if any(term in heading for term in topic_headings[detail_mode]):return 0
   if any(term in heading for term in ('frequently asked','faq')):return 1
   if _is_deprioritized_service_section(heading):return 9
   return 4
  if detail_mode=='more_details':
   if any(term in heading for term in ('how it generally works','how it works','key characteristic','suitable for','safety','participation','duration','capacity','operating hours')):return 0
   if any(term in heading for term in ('definition','experience type','general experience','ride experience')):return 3
   return 9 if _is_deprioritized_service_section(heading) else 5
  if comparison:return 0 if 'comparison' in heading else 5
  if inclusion:
   if any(term in heading for term in ('included','inclusion','frequently asked','participation','timing')):return 0
   return 9 if _is_deprioritized_service_section(heading) else 3
  if any(term in heading for term in ('definition','service summary','about','overview')):return 0
  if any(term in heading for term in ('experience type','general experience','ride experience','how it works')):return 1
  if any(term in heading for term in ('key characteristic','main feature','suitable for')):return 2
  if any(term in heading for term in ('included','inclusion')):return 3
  if any(term in heading for term in ('frequently asked','faq')):return 4
  if _is_deprioritized_service_section(heading):return 9
  return 5
 return sorted(rows,key=lambda row:(priority(row),-float(row['confidence'])))


def _is_duration_heading(row):
 heading=str((row.get('metadata') or {}).get('section_heading',''))
 normalized=__import__('re').sub(r'[^a-z0-9]+',' ',heading.casefold()).strip()
 return normalized in {'duration','session duration','ride duration','experience duration','activity duration'}


def _service_overview_evidence(rows,question,*,full_overview=False,detail_mode='overview'):
 """Combine a bounded set of ranked approved sections, preserving source facts."""
 if not rows:return ''
 value=question.casefold()
 if any(term in value for term in ('compare','comparison','difference','versus',' vs ')):
  return rows[0]['content']
 if detail_mode in {'capacity','duration','inclusions','swimming','swimming_requirement','safety','operating_hours','eligibility','how_it_works'}:
  # Explicit topics must not be diluted with adjacent overview sections.
  return rows[0]['content']
 eligible=[row for row in rows if not _is_deprioritized_service_section(str((row.get('metadata') or {}).get('section_heading','')))]
 selected=[]
 for row in eligible or rows:
  content=row.get('content') if isinstance(row,dict) else None
  if isinstance(content,str) and content.strip():selected.append(content)
  if len(selected)==(6 if full_overview else 3):break
 return '\n'.join(selected)


def _is_deprioritized_service_section(heading):
 value=heading.casefold()
 return any(term in value for term in ('comparison','confirmation required','cancellation','pricing','availability','human handover','medical restriction'))


def _is_raipur_general_row(row):
 metadata=row.get('metadata',{}) if isinstance(row,dict) else {}
 return metadata.get('knowledge_type')=='general' and metadata.get('service_code')=='raipur_general'


def _venue_heading_priority(row):
 heading=str((row.get('metadata') or {}).get('section_heading','')).casefold()
 preferred=('overview','about entartica raipur','venue overview','experiences','activities','what guests can experience','services and attractions','who it is suitable for')
 lower=('location','address','how to reach','contact')
 if any(term in heading for term in preferred): return 0
 if any(term in heading for term in lower): return 9
 return 4


def _is_approved_raipur_row(row, minimum):
 try:
  metadata=row.get('metadata',{})
  return bool(
   isinstance(row,dict) and isinstance(row.get('content'),str) and row['content'].strip()
   and isinstance(row.get('source_filename'),str) and row['source_filename'].strip()
   and isinstance(metadata,dict) and metadata.get('location_code','raipur')=='raipur'
   # retrieve_candidates already admits chunks only through an active parent
   # document.  A missing chunk-level flag must not become an extra filter.
   and metadata.get('is_active') is not False and metadata.get('customer_facing') is True
   and metadata.get('customer_output_allowed') is not False
   and metadata.get('approval_status')=='approved'
   and row.get('confidence') is not None and float(row['confidence'])>=minimum
  )
 except (TypeError,ValueError):return False
