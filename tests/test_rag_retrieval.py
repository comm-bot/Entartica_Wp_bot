import pytest
from types import SimpleNamespace
from app.rag.retrieval import KnowledgeRetrievalError,embed_query,embed_texts,inspect_raipur_corpus,retrieve_candidates
from scripts.ingest_raipur_knowledge import embed_texts as ingestion_embed_texts
class R:
 def __init__(self,data):self.data=data
class Q:
 def __init__(self,data):self.data=data
 def select(self,*_):return self
 def eq(self,*_):return self
 def in_(self,*_):return self
 def execute(self):return R(self.data)
class C:
 def __init__(self,docs,chunks,fail=False):self.docs,self.chunks,self.fail=docs,chunks,fail
 def table(self,name):
  if self.fail:raise RuntimeError('private db url')
  return Q(self.docs if name=='knowledge_documents' else self.chunks)

def test_vector_corpus_is_loaded_once_per_process_cache_generation():
 class CountingClient(C):
  def __init__(self,docs,chunks):super().__init__(docs,chunks);self.calls=[]
  def table(self,name):self.calls.append(name);return super().table(name)
 docs=[{'id':'r','source_file':'r.md','metadata':{'location_code':'raipur','approval_status':'approved'}}]
 chunks=[{'knowledge_document_id':'r','content':'grounded','embedding':[1,0],'metadata':{}}]
 client=CountingClient(docs,chunks)
 from app.rag.retrieval import clear_retrieval_corpus_cache
 clear_retrieval_corpus_cache()
 assert retrieve_candidates(client,[1,0]) and retrieve_candidates(client,[0,1])
 assert client.calls==['knowledge_documents','knowledge_chunks']
 clear_retrieval_corpus_cache()
def test_embed_query_validates_results():
 calls=[]
 assert embed_query('question',object(),embed_texts_fn=lambda q,s:calls.append(q) or [[1,2]])==[1.0,2.0]
 assert calls==[['question']]
 for value in (' ',):
  with pytest.raises(KnowledgeRetrievalError,match='invalid_question'):embed_query(value,object(),embed_texts_fn=lambda *_:[[1]])
 for result in ([],[[]],[[1],[2]],[['x']]):
  with pytest.raises(KnowledgeRetrievalError,match='invalid_embedding'):embed_query('q',object(),embed_texts_fn=lambda *_:result)
 with pytest.raises(KnowledgeRetrievalError,match='embedding_request_failed'):embed_query('q',object(),embed_texts_fn=lambda *_:(_ for _ in ()).throw(RuntimeError('secret')))

class Secret:
 def __init__(self,value):self.value=value
 def get_secret_value(self):return self.value
class Response:
 def __init__(self,payload):self.payload=payload
 def raise_for_status(self):pass
 def json(self):return self.payload
class Client:
 def __init__(self,payload=None,fail=False):self.payload,self.fail=payload,fail
 def post(self,*args,**kwargs):
  if self.fail:raise RuntimeError('private provider failure')
  return Response(self.payload)
 def close(self):pass
def _settings(*,key='key',model='text-embedding-3-small',dimensions=2):
 return SimpleNamespace(openai_api_key=Secret(key) if key is not None else None,openai_embedding_model=model,openai_embedding_dimensions=dimensions)

def test_shared_embedding_helper_validates_config_and_provider_response():
 assert ingestion_embed_texts is embed_texts
 with pytest.raises(KnowledgeRetrievalError,match='missing_api_key'):embed_texts(['q'],_settings(key=None))
 with pytest.raises(KnowledgeRetrievalError,match='missing_embedding_model'):embed_texts(['q'],_settings(model=''))
 with pytest.raises(KnowledgeRetrievalError,match='embedding_request_failed'):embed_texts(['q'],_settings(),http_client_factory=lambda **_:(_ for _ in ()).throw(RuntimeError('private')))
 for payload,code in (({'data':[]},'malformed_embedding_response'),({'data':[{}]},'invalid_embedding'),({'data':[{'embedding':['x',2]}]},'invalid_embedding')):
  with pytest.raises(KnowledgeRetrievalError,match=code):embed_texts(['q'],_settings(),http_client_factory=lambda **_:Client(payload))
 with pytest.raises(KnowledgeRetrievalError,match='dimension_mismatch'):embed_texts(['q'],_settings(dimensions=3),http_client_factory=lambda **_:Client({'data':[{'embedding':[1,2]}]}))
 facts={};assert embed_texts(['q'],_settings(),http_client_factory=lambda **_:Client({'data':[{'embedding':[1,2]}]}),diagnostics=facts)==[[1.0,2.0]]
 assert facts['embedding_client_created'] and facts['embedding_response_received'] and facts['embedding_vector_valid'] and facts['embedding_dimension']==2
def test_retrieval_normalizes_raipur_candidates():
 docs=[{'id':'r','source_file':'r.docx','metadata':{'location_code':'raipur','approval_status':'approved'}},{'id':'o','metadata':{'location_code':'indore','approval_status':'approved'}}]
 chunks=[{'knowledge_document_id':'r','content':'grounded','embedding':'[1,0]','metadata':{}},{'knowledge_document_id':'o','content':'other','embedding':[1,0]}]
 got=retrieve_candidates(C(docs,chunks),[1,0])
 assert got==[{'knowledge_document_id':'r','content':'grounded','metadata':{},'source_filename':'r.docx','confidence':1.0}]
 for limit in (0,-1):
  with pytest.raises(KnowledgeRetrievalError,match='invalid_limit'):retrieve_candidates(C(docs,chunks),[1,0],limit=limit)
 with pytest.raises(KnowledgeRetrievalError,match='retrieval_failed'):retrieve_candidates(C([],[],True),[1])

def test_pgvector_strings_are_counted_and_dimension_mismatches_fail_closed():
 docs=[{'id':'r','source_file':'r.docx','is_active':True,'metadata':{'location_code':'raipur','approval_status':'approved'}}]
 chunks=[{'knowledge_document_id':'r','content':'grounded','embedding':'[1,0]','metadata':{}}]
 inspection=inspect_raipur_corpus(C(docs,chunks),[1,0])
 assert inspection['knowledge_documents_eligible']==1 and inspection['chunks_with_embedding']==1
 assert inspection['stored_dimension']==2 and inspection['raw_candidate_count']==1
 with pytest.raises(KnowledgeRetrievalError,match='dimension_mismatch'):retrieve_candidates(C(docs,chunks),[1,0,0])
