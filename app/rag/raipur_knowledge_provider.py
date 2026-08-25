"""Fail-closed approved Raipur retrieval adapter."""
from app.rag.retrieval import embed_query,retrieve_candidates,KnowledgeRetrievalError
from app.services.raipur_answers import compose_customer_response,compose_venue_overview,generate_raipur_answer
from app.services.raipur.response_models import KnowledgeDraft
from app.services.raipur_services import approved_service_from_message, knowledge_service_code
from app.services.latency import latency_attribute, latency_counter, latency_stage
from app.rag.customer_ready_knowledge import (
 build_customer_ready_service_answer,is_celebration_service_code,is_customer_ready_section,
)
from app.rag.experience_media import ExperienceMedia, extract_approved_media
from app.services.raipur.pontoon_package import ApprovedPontoonPackage, PONTOON_PACKAGE_SOURCE_FILE, render_pontoon_package
import logging
from time import monotonic
logger=logging.getLogger("uvicorn.error")
class RaipurKnowledgeProvider:
 _exact_section_cache={}
 _service_chunks_cache={}
 _exact_section_cache_ttl_seconds=300
 def __init__(self,client,settings,*,embed_query_fn=embed_query,retrieve_candidates_fn=retrieve_candidates,answer_generator=generate_raipur_answer,min_confidence=None):self.client,self.settings,self.embed,self.retrieve,self.generate=client,settings,embed_query_fn,retrieve_candidates_fn,answer_generator;self.minimum=min_confidence if min_confidence is not None else settings.raipur_knowledge_min_confidence;self.last_cache_hit=False
 def answer(self,question): return self._answer(question)
 def answer_venue_overview(self,question): return self._venue_overview(question)
 def answer_service_details(self,question,service_name,service_code=None,*,full_overview=False,detail_mode='overview'): return self._answer(question,service_name=service_name,service_code=service_code,full_overview=full_overview,detail_mode=detail_mode)
 def _service_snapshot(self,code):
  """Return one TTL-bounded, service-isolated approved document snapshot."""
  service_key=(self.client,'raipur',code);cached=self._service_chunks_cache.get(service_key)
  if cached is not None and cached[0]>monotonic():
   latency_attribute('knowledge_cache_hit',True);return cached[1],cached[2]
  latency_attribute('knowledge_cache_hit',False);latency_counter('supabase_reads',2)
  docs=getattr(self.client.table('knowledge_documents').select('id,source_file,metadata,is_active').eq('is_active',True).eq('metadata->>location_code','raipur').eq('metadata->>service_code',code).execute(),'data',[]) or []
  eligible_ids=[doc.get('id') for doc in docs if isinstance(doc,dict) and isinstance(doc.get('id'),str)]
  if eligible_ids:
   query=self.client.table('knowledge_chunks').select('knowledge_document_id,content,metadata')
   query=query.eq('knowledge_document_id',eligible_ids[0]) if len(eligible_ids)==1 else query.in_('knowledge_document_id',eligible_ids)
   rows=getattr(query.execute(),'data',[]) or []
  else:rows=[]
  snapshot=(tuple(docs),tuple(rows));self._service_chunks_cache[service_key]=(monotonic()+self._exact_section_cache_ttl_seconds,*snapshot)
  return snapshot
 def experience_media(self, *, scope, service_code=None, category=None):
  """Return exact approved media, preferring service-specific evidence."""
  try:
   docs=getattr(self.client.table('knowledge_documents').select('id,source_file,metadata,is_active').eq('is_active',True).execute(),'data',[]) or []
   def media_for(doc, requested_scope):
    rows=getattr(self.client.table('knowledge_chunks').select('chunk_index,content,metadata').eq('knowledge_document_id',doc.get('id')).execute(),'data',[]) or []
    return extract_approved_media(rows,scope=requested_scope,source_document=str(doc.get('source_file','')),service_code=service_code,category=category)
   if service_code:
    exact=next((d for d in docs if isinstance(d.get('metadata'),dict) and d['metadata'].get('location_code')=='raipur' and d['metadata'].get('service_code')==service_code and d['metadata'].get('approval_status')=='approved' and d['metadata'].get('customer_facing') is True),None)
    if exact:
     media=media_for(exact,'service')
     if media.urls:return media
   source={'activity':'active/general/raipur_general_information.md','celebration':'active/faq/raipur_celebration_faq.md','venue':'active/general/raipur_general_information.md'}.get(category or scope)
   fallback=next((d for d in docs if d.get('source_file')==source and isinstance(d.get('metadata'),dict) and d['metadata'].get('approval_status')=='approved' and d['metadata'].get('customer_facing') is True),None)
   return media_for(fallback,category or scope) if fallback else ExperienceMedia(scope=scope,service_code=service_code,category=category)
  except Exception:return ExperienceMedia(scope=scope,service_code=service_code,category=category)
 def recommendation_evidence(self,service_code):
  """Return only exact approved sections for one canonical service."""
  allowed={'experience overview','what makes this experience special','best for','experience highlights','capacity','celebration inclusions','customisation options','duration'}
  try:
   docs,service_rows=self._service_snapshot(service_code)
   evidence=[]
   for doc in docs:
    metadata=doc.get('metadata',{}) if isinstance(doc,dict) else {}
    if not (isinstance(metadata,dict) and metadata.get('location_code')=='raipur' and metadata.get('service_code')==service_code and metadata.get('approval_status')=='approved' and metadata.get('customer_facing') is True):continue
    rows=[row for row in service_rows if isinstance(row,dict) and row.get('knowledge_document_id')==doc.get('id')]
    for row in rows:
     row_metadata=row.get('metadata',{}) if isinstance(row,dict) else {}
     heading=str(row_metadata.get('section_heading','')) if isinstance(row_metadata,dict) else ''
     normalized=__import__('re').sub(r'[^a-z0-9]+',' ',heading.casefold()).strip()
     if normalized not in allowed or row_metadata.get('service_code',service_code)!=service_code:continue
     content=row.get('content') if isinstance(row,dict) else None
     if isinstance(content,str) and content.strip():evidence.append({'service_code':service_code,'section':heading,'text':content.strip(),'source_document_id':doc.get('id')})
   return evidence
  except Exception:return []
 def approved_pontoon_package(self) -> ApprovedPontoonPackage | None:
  """Read the trusted package only from the active canonical Pontoon document."""
  try:
   docs,rows=self._service_snapshot('pontoon_celebration')
   doc=next((item for item in docs if isinstance(item,dict) and item.get('source_file')==PONTOON_PACKAGE_SOURCE_FILE and isinstance(item.get('metadata'),dict) and item['metadata'].get('approval_status')=='approved' and item['metadata'].get('customer_facing') is True),None)
   if doc is None:return None
   sections={}
   for row in rows:
    if not isinstance(row,dict) or row.get('knowledge_document_id')!=doc.get('id'):continue
    metadata=row.get('metadata') if isinstance(row.get('metadata'),dict) else {}
    heading=metadata.get('section_heading');content=row.get('content')
    if isinstance(heading,str) and isinstance(content,str):sections[heading]=content
   return render_pontoon_package(sections,source_file=PONTOON_PACKAGE_SOURCE_FILE)
  except Exception:return None
 def fallback_context(self,question):
  """Return bounded excerpts from active, approved Raipur rows only."""
  try:
   vector=self.embed(question,self.settings);rows=self.retrieve(self.client,vector,limit=3)
   return tuple(row['content'][:800] for row in rows if isinstance(row,dict) and isinstance(row.get('content'),str) and row['content'].strip() and isinstance(row.get('source_filename'),str) and row.get('metadata',{}).get('location_code','raipur')=='raipur')
  except Exception:return ()
 def _answer(self,question,service_name=None,service_code=None,full_overview=False,detail_mode='overview'):
  # A resolved service and an explicit approved section are deterministic
  # evidence.  Do this before embedding/vector work: it is faster and avoids
  # treating a temporary vector-provider failure as missing knowledge.
  with latency_stage('exact_section_lookup'): exact=self._exact_topic_fallback(question,service_name,service_code,detail_mode)
  if exact is not None:return exact
  stage='query_embedding'
  try:
   # Exact-service questions retain their full normalized wording.  A larger
   # candidate pool prevents another service's globally higher score from
   # excluding the requested service before local isolation is applied.
   with latency_stage('query_embedding'):vector=self.embed(question,self.settings)
   stage='Supabase_vector_search';
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
     rows=[row for row in rows if is_customer_ready_section(canonical_code,(row.get('metadata') or {}).get('section_heading'),detail_mode)]
   else:
    with latency_stage('knowledge_reranking'):rows=[r for r in rows if _is_approved_raipur_row(r,minimum)]
   if not rows:return KnowledgeDraft(None,None,None,True)
   best=rows[0] if service_name else max(rows,key=lambda r:float(r['confidence']))
   if service_name:
    ready=build_customer_ready_service_answer(
     [(str((row.get('metadata') or {}).get('section_heading','')),str(row.get('content',''))) for row in rows],
     service_name=service_name,service_code=canonical_code,detail_mode=detail_mode,
    )
    if ready.text:
     document_id=best.get('knowledge_document_id')
     return KnowledgeDraft(ready.text,best['source_filename'],float(best['confidence']),False,ready.section_headings[0] if ready.section_headings else None,len(rows),document_id if isinstance(document_id,str) and document_id.strip() else None,ready.section_headings)
    return KnowledgeDraft(None,None,None,True)
   evidence=_service_overview_evidence(rows,question,full_overview=full_overview,detail_mode=detail_mode) if service_name else best['content']
   stage='answer_composition';
   with latency_stage('OpenAI_answer_generation'):answer=self.generate({'content':evidence,'source_filename':best['source_filename'],'score':best['confidence'],'question':question},low_confidence=False)
   # The production generator is the single customer-response composition
   # boundary.  Injectable test generators may deliberately return raw
   # evidence, which still needs the normal safety composition path.
   with latency_stage('answer_validation'):customer_answer=(answer.answer.strip() if self.generate is generate_raipur_answer and isinstance(answer.answer,str) and answer.answer.strip() else compose_customer_response(answer.answer,question=question) if isinstance(answer.answer,str) else None)
   heading=best.get('metadata',{}).get('section_heading') if isinstance(best.get('metadata',{}),dict) else None
   document_id=best.get('knowledge_document_id')
   headings=tuple(dict.fromkeys(str((row.get('metadata') or {}).get('section_heading')).strip() for row in rows if isinstance((row.get('metadata') or {}).get('section_heading'),str) and str((row.get('metadata') or {}).get('section_heading')).strip()))
   return KnowledgeDraft(customer_answer,best['source_filename'],float(best['confidence']),not bool(customer_answer),heading if isinstance(heading,str) else None,len(rows),document_id if isinstance(document_id,str) and document_id.strip() else None,headings)
  except Exception:
   with latency_stage('exact_section_lookup'): fallback=self._exact_topic_fallback(question,service_name,service_code,detail_mode)
   if fallback is not None:return fallback
   logger.warning('raipur_knowledge_provider_failed stage=%s service_code=%s detail_mode=%s error_category=provider_failure',stage,service_code or 'none',detail_mode)
   return KnowledgeDraft(None,None,None,True)

 def _exact_topic_fallback(self,question,service_name,service_code,detail_mode):
  """Read one exact approved section only when vector retrieval cannot run."""
  if not service_name or detail_mode not in {'overview','more_details','suitable_for','inclusions','key_characteristics','duration','swimming','swimming_requirement','capacity','how_it_works','safety','eligibility','operating_hours','conduct_rules','onboard_environment'}:return None
  approved=approved_service_from_message(service_name)
  code=service_code or (knowledge_service_code(approved) if approved is not None else None)
  if not code:return None
  cache_key=('raipur',code,detail_mode)
  cached=self._exact_section_cache.get(cache_key)
  if cached is not None and cached[0] > monotonic():
   self.last_cache_hit=True
   latency_attribute('knowledge_cache_hit',True)
   return cached[1]
  self.last_cache_hit=False
  try:
   docs,chunk_rows=self._service_snapshot(code)
   for doc in docs:
    metadata=doc.get('metadata',{}) if isinstance(doc,dict) else {}
    if not (isinstance(metadata,dict) and metadata.get('location_code')=='raipur' and metadata.get('service_code')==code and metadata.get('approval_status')=='approved' and metadata.get('customer_facing') is True):continue
    rows=[row for row in chunk_rows if isinstance(row,dict) and row.get('knowledge_document_id')==doc.get('id')]
    matches=[]
    for row in rows:
     row_metadata=row.get('metadata',{}) if isinstance(row,dict) else {}
     heading=str(row_metadata.get('section_heading','')) if isinstance(row_metadata,dict) else ''
     if _matches_exact_topic_heading(detail_mode,heading) and is_customer_ready_section(code,heading,detail_mode):matches.append((row,heading))
    if not matches:continue
    # The approved celebration documents use three stored subsection chunks
    # when a parent ``Celebration Inclusions`` chunk is absent.  Combine only
    # those exact subsection rows so confirmed facts remain distinct from
    # optional, confirmation-required add-ons.
    if detail_mode=='inclusions':
     ranks=[_inclusion_heading_rank(heading) for _row,heading in matches]
     best_rank=min(ranks)
     matches=[match for match,rank in zip(matches,ranks) if rank==best_rank]
    sections=[(heading,str(row.get('content',''))) for row,heading in matches if isinstance(row,dict) and isinstance(row.get('content'),str)]
    content='\n'.join(value for _heading,value in sections)
    ready=build_customer_ready_service_answer(sections,service_name=service_name,service_code=code,detail_mode=detail_mode)
    answer=ready.text
    if isinstance(answer,str) and answer.strip():
     source=metadata.get('source_filename',doc.get('source_file'))
     headings=ready.section_headings
     selected_heading='Celebration Inclusions' if detail_mode=='inclusions' and any(_is_celebration_inclusion_subheading(heading) for heading in headings) else headings[0]
     draft=KnowledgeDraft(answer,source if isinstance(source,str) else None,None,False,selected_heading,len(matches),doc.get('id') if isinstance(doc.get('id'),str) else None,headings)
     # Cache only after all active/approved/customer-facing checks above.
     self._exact_section_cache[cache_key]=(monotonic()+self._exact_section_cache_ttl_seconds,draft)
     return draft
  except Exception:return None
  return None

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
  'suitable_for':('suitable for','ideal for','recommended for','suitable guests','suitable occasions'),
  'inclusions':('celebration inclusions','inclusions','package inclusions','what is included','what is typically included','typically included','included','inclusion'),
  'key_characteristics':('key characteristics','key features','features'),
  'eligibility':('participation','suitable for','safety','restriction'),
  'operating_hours':('operating hours','timing','hours'),
  'conduct_rules':('conduct rules','restrictions','not permitted'),
  'onboard_environment':('onboard environment','onboard facilities','environment'),
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


def _matches_exact_topic_heading(detail_mode,heading):
 normalized=__import__('re').sub(r'[^a-z0-9]+',' ',heading.casefold()).strip()
 if detail_mode=='duration':return normalized in {'duration','package duration','session duration','ride duration','experience duration','activity duration','access period'}
 if detail_mode=='overview':return normalized in {'definition','overview','experience overview','service summary','general experience','experience type','ride experience'}
 if detail_mode=='more_details':return normalized in {'what makes this experience special','what guests can expect','best for','suitable for','customisation options','how it works','how it generally works','key characteristics'}
 if detail_mode=='inclusions':return _inclusion_heading_rank(heading)>=0
 if detail_mode=='suitable_for':return normalized in {'best for','suitable for','ideal for','recommended for','who it is suitable for','suitable guests','suitable occasions'}
 if detail_mode=='key_characteristics':return normalized in {'what makes this experience special','experience highlights','key characteristics','key features','features'}
 if detail_mode in {'swimming','swimming_requirement'}:return 'swimming' in normalized
 if detail_mode=='capacity':return normalized in {'capacity','guest capacity','guest limit','guest configuration','seating capacity','group size','number of guests','participants'}
 if detail_mode=='how_it_works':return normalized in {'how it works','how it generally works','ride experience','general experience'}
 if detail_mode=='safety':return 'safety' in normalized
 if detail_mode=='operating_hours':return normalized in {'operating hours','opening hours','timings','schedule','staycation package'} or 'hours' in normalized
 if detail_mode=='conduct_rules':return normalized in {'conduct rules','restrictions','not permitted'}
 if detail_mode=='onboard_environment':return normalized in {'onboard environment','onboard facilities','environment'}
 if detail_mode=='eligibility':return any(term in normalized for term in ('participation','suitable for','eligibility','age requirement'))
 return False

def _is_celebration_inclusion_subheading(heading):
 normalized=__import__('re').sub(r'[^a-z0-9]+',' ',heading.casefold()).strip()
 return normalized=='confirmed from source documents' or normalized.startswith('optional add ons') or normalized=='requires confirmation'

def _inclusion_heading_rank(heading):
 normalized=__import__('re').sub(r'[^a-z0-9]+',' ',heading.casefold()).strip()
 if normalized in {'celebration inclusions','inclusions','package inclusions','what is included','included'}:return 0
 if normalized in {'club room day access','accommodation','breakfast','unlimited h2o play park access','one time boat house access','food voucher','aqua roller activity under h2o play park access'}:return 1
 if _is_celebration_inclusion_subheading(heading):return 1
 # FAQs are an approved fallback only when no dedicated inclusion section is
 # present; they must never outrank the factual section/subsections.
 if 'inclusion' in normalized or 'included' in normalized:return 2
 return -1


def _service_overview_evidence(rows,question,*,full_overview=False,detail_mode='overview'):
 """Combine a bounded set of ranked approved sections, preserving source facts."""
 if not rows:return ''
 value=question.casefold()
 if any(term in value for term in ('compare','comparison','difference','versus',' vs ')):
  return rows[0]['content']
 if detail_mode in {'capacity','duration','suitable_for','inclusions','key_characteristics','swimming','swimming_requirement','safety','operating_hours','conduct_rules','onboard_environment','eligibility','how_it_works'}:
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
 return any(term in value for term in ('comparison','confirmation required','cancellation','pricing','availability','human handover','medical restriction','suggested chatbot response','internal notes','prompt instructions','source register','sources','clarifications required','approval notes','management notes'))


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
   and not _is_deprioritized_service_section(str(metadata.get('section_heading','')))
   and metadata.get('approval_status')=='approved'
   and row.get('confidence') is not None and float(row['confidence'])>=minimum
  )
 except (TypeError,ValueError):return False
