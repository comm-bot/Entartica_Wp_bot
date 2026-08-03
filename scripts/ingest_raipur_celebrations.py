"""Legacy celebration-only ingestion entry point; unified ingestion supersedes it."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.rag.knowledge import chunk_hash, section_chunks
from app.rag.retrieval import embed_texts
from app.config import Settings
from app.integrations.supabase import get_supabase_client

def _rows(response):
    data=getattr(response,"data",None)
    return [item for item in data if isinstance(item,dict)] if isinstance(data,list) else [data] if isinstance(data,dict) else []

def ingest_document(client, document, settings, *, embedder=embed_texts):
    """Stage changed chunks before activating them; same checksum is a no-op."""
    existing=_rows(client.table("knowledge_documents").select("id,document_version,is_active").eq("source_file",document.source_file).execute())
    version=f"{document.checksum}:celebrations_v1"
    if any(row.get("document_version")==version and row.get("is_active") is True for row in existing): return "unchanged",0
    row=_rows(client.table("knowledge_documents").upsert({"source_file":document.source_file,"document_version":version,"approved_by":"celebration_ingestion_manifest","is_active":False,"metadata":document.metadata|{"ingestion_status":"staging"}},on_conflict="source_file,document_version").execute())
    if not row or not isinstance(row[0].get("id"),str): raise RuntimeError("document_upsert_failed")
    identifier=row[0]["id"]; chunks=section_chunks(document)
    if not chunks: raise RuntimeError("empty_chunks")
    vectors=embedder([chunk.embedding_input(document.category) for chunk in chunks],settings)
    if len(vectors)!=len(chunks): raise RuntimeError("embedding_count_mismatch")
    payload=[{"knowledge_document_id":identifier,"chunk_index":chunk.index,"content":chunk.text,"content_hash":chunk_hash(chunk.text),"embedding":"["+",".join(format(value,".17g") for value in vector)+"]","metadata":document.metadata|{"chunk_index":chunk.index,"section_heading":chunk.section_heading,"subsection_heading":chunk.subsection_heading}} for chunk,vector in zip(chunks,vectors,strict=True)]
    client.table("knowledge_chunks").upsert(payload,on_conflict="knowledge_document_id,content_hash").execute()
    complete=_rows(client.table("knowledge_chunks").select("id").eq("knowledge_document_id",identifier).execute())
    if len(complete)<len(chunks): raise RuntimeError("staged_chunks_incomplete")
    client.table("knowledge_documents").update({"is_active":True,"metadata":document.metadata|{"ingestion_status":"ready"}}).eq("id",identifier).execute()
    client.table("knowledge_documents").update({"is_active":False}).eq("source_file",document.source_file).neq("id",identifier).eq("is_active",True).execute()
    return ("updated" if existing else "created"),len(chunks)

def deactivate_old_overlaps(client, documents):
    """Deactivate only superseded active Raipur celebration records by service code."""
    codes={document.metadata.get("service_code") for document in documents if document.metadata.get("service_code")}; protected={document.source_file for document in documents}; affected=[]
    if not codes: return affected
    for row in _rows(client.table("knowledge_documents").select("id,source_file,metadata").eq("is_active",True).execute()):
        metadata=row.get("metadata") if isinstance(row.get("metadata"),dict) else {}
        if row.get("source_file") in protected or metadata.get("location_code")!="raipur" or metadata.get("knowledge_category")!="celebration" or metadata.get("service_code") not in codes: continue
        if isinstance(row.get("id"),str):
            client.table("knowledge_documents").update({"is_active":False}).eq("id",row["id"]).execute(); affected.append(str(row.get("source_file","unknown")))
    return affected

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--dry-run",action="store_true"); parser.add_argument("--deactivate-old-overlaps",action="store_true"); args=parser.parse_args()
    print("ingestion_refused reason=legacy_celebration_ingestion_disabled use=ingest_raipur_knowledge.py")
    return 2
    # Legacy implementation retained below only for historical reference; the
    # early return above makes the unified manifest the only production path.
    for name,count in sorted(counts.items()): print(f"csv_excluded filename={name} rows={count}")
    for row in plan: print(f"document filename={Path(row.source_file).name if row.source_file else 'unknown'} status={row.status} reason={row.reason}")
    for error in errors: print(f"validation_error reason={error}")
    if args.dry_run:
        print(f"dry_run_complete errors={len(errors)} writes=0 embedding_calls=0 old_overlaps={'possible' if args.deactivate_old_overlaps else 'not_requested'}")
        return 1 if errors else 0
    if errors: print("ingestion_refused validation_errors=true"); return 1
    settings=Settings()
    if not settings.embedding_configuration_is_valid(): print("ingestion_refused embedding_configuration_incomplete=true"); return 1
    try:
        client=get_supabase_client(); total=0
        for row in eligible:
            status,chunks=ingest_document(client,row.document,settings); total+=chunks
            print(f"ingestion_result filename={Path(row.source_file).name} status={status} chunks={chunks}")
        if args.deactivate_old_overlaps:
            for source in deactivate_old_overlaps(client,[row.document for row in eligible]): print(f"old_overlap_deactivated filename={Path(source).name}")
    except Exception as error: print(f"ingestion_failed error_class={type(error).__name__}"); return 1
    print(f"ingestion_complete documents={len(eligible)} chunks_created={total}")
    return 0
if __name__ == "__main__": raise SystemExit(main())
