"""Reusable, source-safe Raipur retrieval primitives."""
from __future__ import annotations
import json
from math import sqrt
from typing import Any, Callable
import httpx
from functools import lru_cache
from app.rag.location_filter import is_document_available_for_location

class KnowledgeRetrievalError(RuntimeError): pass
@lru_cache(maxsize=1)
def _embedding_http_client() -> httpx.Client:
 return httpx.Client(timeout=30.0)
def _secret_present(value: Any) -> bool:
 try: return bool(value and value.get_secret_value())
 except AttributeError: return bool(value)
def embedding_configuration_error(settings: Any) -> str | None:
 if not _secret_present(getattr(settings,'openai_api_key',None)): return 'missing_api_key'
 if not isinstance(getattr(settings,'openai_embedding_model',None),str) or not settings.openai_embedding_model.strip(): return 'missing_embedding_model'
 if not isinstance(getattr(settings,'openai_embedding_dimensions',None),int) or settings.openai_embedding_dimensions < 1: return 'invalid_embedding'
 return None
def embed_texts(texts:list[str],settings:Any,*,http_client_factory:Callable|None=None,diagnostics:dict[str,Any]|None=None)->list[list[float]]:
 """Shared OpenAI embedding request/response parser for ingestion and runtime."""
 if not isinstance(texts,list) or not texts or not all(isinstance(text,str) and text.strip() for text in texts):raise KnowledgeRetrievalError('invalid_question')
 error=embedding_configuration_error(settings)
 if error:raise KnowledgeRetrievalError(error)
 facts=diagnostics if diagnostics is not None else {}
 facts.update(api_key_present=True,embedding_model_present=True,embedding_client_created=False,embedding_response_received=False,embedding_vector_valid=False,embedding_dimension=None)
 factory=http_client_factory
 try:
  client=factory(timeout=30.0) if factory is not None else _embedding_http_client();facts['embedding_client_created']=True
  response=client.post('https://api.openai.com/v1/embeddings',headers={'Authorization':f"Bearer {settings.openai_api_key.get_secret_value()}",'Content-Type':'application/json'},json={'model':settings.openai_embedding_model,'input':texts})
  response.raise_for_status();payload=response.json();facts['embedding_response_received']=True
 except Exception:
  raise KnowledgeRetrievalError('embedding_request_failed') from None
 data=payload.get('data') if isinstance(payload,dict) else None
 if not isinstance(data,list) or len(data)!=len(texts):raise KnowledgeRetrievalError('malformed_embedding_response')
 vectors=[]
 for item in data:
  vector=item.get('embedding') if isinstance(item,dict) else None
  if not isinstance(vector,list) or not vector or not all(isinstance(value,(int,float)) for value in vector):raise KnowledgeRetrievalError('invalid_embedding')
  facts['embedding_dimension']=len(vector)
  if len(vector)!=settings.openai_embedding_dimensions:raise KnowledgeRetrievalError('dimension_mismatch')
  vectors.append([float(value) for value in vector])
 facts['embedding_vector_valid']=True
 return vectors
def embed_query(question:str,settings:Any,*,embed_texts_fn:Callable|None=None)->list[float]:
 if not isinstance(question,str) or not question.strip():raise KnowledgeRetrievalError('invalid_question')
 if embed_texts_fn is None:embed_texts_fn=embed_texts
 try:result=embed_texts_fn([question],settings)
 except KnowledgeRetrievalError:raise
 except Exception:raise KnowledgeRetrievalError('embedding_request_failed') from None
 if not isinstance(result,list) or len(result)!=1 or not isinstance(result[0],list) or not result[0] or not all(isinstance(x,(int,float)) for x in result[0]):raise KnowledgeRetrievalError('invalid_embedding')
 return [float(x) for x in result[0]]
def _rows(response):
 data=getattr(response,'data',None)
 if isinstance(data,list):return [row for row in data if isinstance(row,dict)]
 if isinstance(data,dict):return [data]
 return []
def _vector(value:Any)->list[float]|None:
 if isinstance(value,str):
  try:value=json.loads(value)
  except json.JSONDecodeError:return None
 if isinstance(value,list) and value and all(isinstance(item,(int,float)) for item in value):return [float(item) for item in value]
 return None
def _score(a,b):
 if len(a)!=len(b):return None
 d=sqrt(sum(x*x for x in a))*sqrt(sum(x*x for x in b));return sum(x*y for x,y in zip(a,b))/d if d else None
def retrieve_candidates(client:Any,question_embedding:list[float],*,limit:int=20)->list[dict]:
 if limit<1:raise KnowledgeRetrievalError('invalid_limit')
 try:
  docs=_rows(client.table('knowledge_documents').select('id,source_file,metadata').eq('is_active',True).execute()); ids={d['id']:d for d in docs if isinstance(d.get('id'),str) and isinstance(d.get('metadata'),dict) and is_document_available_for_location(d['metadata'],'raipur') and d['metadata'].get('approval_status')=='approved'}
  chunks=_rows(client.table('knowledge_chunks').select('knowledge_document_id,content,embedding,metadata').in_('knowledge_document_id',list(ids)).execute())
 except Exception:raise KnowledgeRetrievalError('retrieval_failed') from None
 out=[]
 mismatched=False
 for c in chunks:
  vec=_vector(c.get('embedding'))
  if vec is not None and len(vec)!=len(question_embedding):mismatched=True
  score=_score(question_embedding,vec) if vec is not None else None
  metadata=c.get('metadata',{})
  if c.get('knowledge_document_id') in ids and isinstance(c.get('content'),str) and c['content'].strip() and score is not None and (not isinstance(metadata,dict) or metadata.get('customer_output_allowed') is not False):
   d=ids[c['knowledge_document_id']];out.append({'knowledge_document_id':c['knowledge_document_id'],'content':c['content'],'metadata':c.get('metadata',{}),'source_filename':d['metadata'].get('source_filename',d.get('source_file')),'confidence':score})
 if not out and mismatched:raise KnowledgeRetrievalError('dimension_mismatch')
 return sorted(out,key=lambda x:x['confidence'],reverse=True)[:limit]

def inspect_raipur_corpus(client:Any,query_embedding:list[float])->dict[str,int|float|None|bool]:
 """Read-only counts for the same eligible-document and vector rules as runtime retrieval."""
 try:
  docs=_rows(client.table('knowledge_documents').select('id,source_file,metadata,is_active').execute())
  chunks=_rows(client.table('knowledge_chunks').select('knowledge_document_id,content,embedding,metadata').execute())
 except Exception:raise KnowledgeRetrievalError('retrieval_failed') from None
 raipur=[row for row in docs if isinstance(row.get('metadata'),dict) and row['metadata'].get('location_code')=='raipur']
 approved=[row for row in docs if isinstance(row.get('metadata'),dict) and row['metadata'].get('approval_status')=='approved']
 active=[row for row in docs if row.get('is_active') is True]
 eligible={row['id']:row for row in docs if isinstance(row.get('id'),str) and row.get('is_active') is True and isinstance(row.get('metadata'),dict) and row['metadata'].get('approval_status')=='approved' and is_document_available_for_location(row['metadata'],'raipur')}
 linked=[row for row in chunks if row.get('knowledge_document_id') in eligible]
 vectors=[_vector(row.get('embedding')) for row in linked]
 vectors=[vector for vector in vectors if vector is not None]
 stored_dimension=len(vectors[0]) if vectors else None
 raw=[]
 for row in linked:
  vector=_vector(row.get('embedding'));score=_score(query_embedding,vector) if vector is not None else None
  if score is not None and isinstance(row.get('content'),str) and row['content'].strip():raw.append(score)
 return {'knowledge_documents_total':len(docs),'knowledge_documents_raipur':len(raipur),'knowledge_documents_approved':len(approved),'knowledge_documents_active':len(active),'knowledge_documents_eligible':len(eligible),'knowledge_chunks_total':len(chunks),'eligible_document_chunks':len(linked),'chunks_with_embedding':len(vectors),'chunks_without_embedding':len(linked)-len(vectors),'stored_dimension':stored_dimension,'dimension_match':stored_dimension==len(query_embedding) if stored_dimension is not None else False,'raw_candidate_count':len(raw),'best_raw_confidence':max(raw) if raw else None,'filtered_candidate_count':len(raw)}
