"""Read-only verification for the ingested Coimbatore master knowledge."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.rag.retrieval import clear_retrieval_corpus_cache, embed_texts, retrieve_candidates_for_location

SOURCE = "documents/coimbatore/active/COIMBATORE_KNOWLEDGE_BASE.md"
QUERIES = (
    "What is Pontoon Celebration?", "active exact coimbatore_pontoon_standard customer package presentation",
    "active exact coimbatore_pontoon_couple_romance customer package presentation", "Is cake included?",
    "Can pregnant guests join?", "Where is Entartica Coimbatore?",
)

def main() -> int:
    client, settings = get_supabase_client(), Settings()
    docs = client.table("knowledge_documents").select("id,source_file,document_version,is_active,metadata").eq("source_file", SOURCE).execute().data or []
    active = [row for row in docs if row.get("is_active") is True and (row.get("metadata") or {}).get("location_code") == "coimbatore"]
    if len(active) != 1: raise RuntimeError("active_coimbatore_document_count_invalid")
    document = active[0]
    chunks = client.table("knowledge_chunks").select("content,embedding,metadata").eq("knowledge_document_id", document["id"]).execute().data or []
    vectors = [json.loads(row["embedding"]) if isinstance(row.get("embedding"), str) else row.get("embedding") for row in chunks]
    dimensions = {len(vector) for vector in vectors if isinstance(vector, list)}
    empty = sum(not isinstance(row.get("content"), str) or not row["content"].strip() for row in chunks)
    corpus = "\n".join(str(row.get("content", "")) for row in chunks)
    standard_block = "coimbatore_pontoon_standard" in corpus and "30 Minutes Premium Boat Ride" in corpus
    couple_block = "coimbatore_pontoon_couple_romance" in corpus and "20 Minutes Private Pontoon Boat Ride" in corpus
    print(f"document_id={document['id']} active_documents={len(active)} chunks={len(chunks)} embeddings={len(vectors)} dimensions={sorted(dimensions)} empty_chunks={empty}")
    print(f"standard_package_block={str(standard_block).lower()} couple_romance_package_block={str(couple_block).lower()}")
    if empty or dimensions != {1536} or not standard_block or not couple_block:
        raise RuntimeError("coimbatore_canonical_package_verification_failed")
    query_vectors = embed_texts(list(QUERIES), settings)
    clear_retrieval_corpus_cache()
    raipur = 0
    for query, vector in zip(QUERIES, query_vectors, strict=True):
        rows = retrieve_candidates_for_location(client, vector, location_code="coimbatore", limit=3)
        raipur += sum((row.get("metadata") or {}).get("location_code") == "raipur" for row in rows)
        top = rows[0] if rows else {}
        print(f"query={query!r} results={len(rows)} source={top.get('source_filename','none')} heading={(top.get('metadata') or {}).get('section_heading','none')}")
        expected_id = next((value for value in ("coimbatore_pontoon_standard", "coimbatore_pontoon_couple_romance") if value in query), None)
        if expected_id is not None:
            hit = any(expected_id in str(row.get("content", "")) for row in rows)
            print(f"canonical_query_package_id={expected_id} hit={str(hit).lower()}")
            if not hit: raise RuntimeError("canonical_package_retrieval_failed")
    print(f"raipur_chunks_returned={raipur}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
