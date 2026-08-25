from pathlib import Path
from types import SimpleNamespace

from app.rag.coimbatore_ingestion import build_coimbatore_master
from app.rag.retrieval import clear_retrieval_corpus_cache, retrieve_candidates_for_location
from scripts.ingest_raipur_knowledge import _chunks


ROOT = Path(__file__).resolve().parents[1]


def test_single_master_file_builds_many_coimbatore_chunks():
    document = build_coimbatore_master(ROOT)
    assert document.source_file == "documents/coimbatore/active/COIMBATORE_KNOWLEDGE_BASE.md"
    assert document.metadata["location_code"] == "coimbatore"
    assert document.metadata["approval_status"] == "approved"
    chunks = _chunks(document)
    assert len(chunks) > 20
    assert all(chunk["content"].strip() for chunk in chunks)
    assert all(chunk["metadata"]["location_code"] == "coimbatore" for chunk in chunks)


class Query:
    def __init__(self, rows): self.rows = rows
    def select(self, *_a): return self
    def eq(self, *_a): return self
    def in_(self, *_a): return self
    def execute(self): return SimpleNamespace(data=self.rows)


class Client:
    def __init__(self):
        self.docs = [
            {"id":"c","source_file":"COIMBATORE_KNOWLEDGE_BASE.md","metadata":{"location_code":"coimbatore","approval_status":"approved"}},
            {"id":"r","source_file":"raipur.md","metadata":{"location_code":"raipur","approval_status":"approved"}},
        ]
        self.chunks = [
            {"knowledge_document_id":"c","content":"Pontoon cake Coimbatore","embedding":[1.0,0.0],"metadata":{"location_code":"coimbatore","section_heading":"Cake"}},
            {"knowledge_document_id":"r","content":"Raipur content","embedding":[1.0,0.0],"metadata":{"location_code":"raipur"}},
        ]
    def table(self, name): return Query(self.docs if name == "knowledge_documents" else self.chunks)


def test_location_filtered_retrieval_returns_zero_raipur_chunks():
    client = Client(); clear_retrieval_corpus_cache()
    rows = retrieve_candidates_for_location(client, [1.0, 0.0], location_code="coimbatore")
    assert [row["content"] for row in rows] == ["Pontoon cake Coimbatore"]
    assert all(row["metadata"]["location_code"] == "coimbatore" for row in rows)
