"""Dry-run-first unified Raipur Markdown ingestion; no legacy DOCX corpus is read."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.rag.knowledge import chunk_hash
from app.rag.raipur_ingestion import build_plan, manifest_path
from app.rag.retrieval import embed_texts
from app.services.raipur_answers import clean_customer_evidence, is_internal_example_section


class IngestionStageError(RuntimeError):
    """Retain the safe operation name while preserving the provider error."""

    def __init__(self, stage: str, error: BaseException) -> None:
        self.stage = stage
        self.error = error
        super().__init__(stage)


def _at_stage(stage: str, operation: Any) -> Any:
    try:
        return operation()
    except IngestionStageError:
        raise
    except Exception as error:
        raise IngestionStageError(stage, error) from error


def _error_field(error: BaseException, field: str) -> object:
    return getattr(error, field, None)


def _print_ingestion_failure(filename: str, stage: str, error: BaseException) -> None:
    """Print PostgREST diagnostics without request payloads or credentials."""

    def value(field: str) -> object:
        result = _error_field(error, field)
        return result if result is not None else "none"

    status = _error_field(error, "status")
    if status is None:
        status = _error_field(error, "status_code")
    print("ingestion_failed")
    print(f"filename={filename}")
    print(f"stage={stage}")
    print(f"error_class={type(error).__name__}")
    print(f"error_code={value('code')}")
    print(f"error_message={value('message')}")
    print(f"error_details={value('details')}")
    print(f"error_hint={value('hint')}")
    print(f"http_status={status if status is not None else 'none'}")
    print(f"error_str={str(error)}")
    print(f"error_repr={error!r}")


def _rows(response: object) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else [data] if isinstance(data, dict) else []


def _chunks(document: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, section in enumerate(document.sections):
        internal_example = is_internal_example_section(section.heading)
        content = clean_customer_evidence(section.text) if internal_example else section.text
        # Example-response sections are authoring guidance, not customer-facing
        # retrieval evidence.  Retain the cleaned content for auditability, but
        # ensure the runtime retriever excludes it.
        allowed = bool(content.strip()) and not internal_example
        chunks.append({
            "index": index,
            "content": content,
            "metadata": document.metadata | {
                "chunk_index": index,
                "section_heading": section.heading,
                "section_type": "example_response" if internal_example else "customer_information",
                "customer_output_allowed": allowed,
            },
        })
    return [chunk for chunk in chunks if chunk["content"].strip()]


def _deduplicate_chunks(chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[list[int]]]:
    """Keep the first identical chunk in stable document order."""

    retained: list[dict[str, Any]] = []
    indexes_by_hash: dict[str, list[int]] = {}
    for chunk in chunks:
        content_hash = chunk_hash(chunk["content"])
        indexes_by_hash.setdefault(content_hash, []).append(chunk["index"])
        if len(indexes_by_hash[content_hash]) == 1:
            retained.append(chunk)
    duplicate_groups = [indexes for indexes in indexes_by_hash.values() if len(indexes) > 1]
    return retained, duplicate_groups


def _print_chunk_deduplication(filename: str, original_count: int, unique_count: int, duplicate_groups: list[list[int]]) -> None:
    duplicate_count = original_count - unique_count
    duplicate_indexes = [index for group in duplicate_groups for index in group]
    print("chunk_deduplication")
    print(f"filename={filename}")
    print(f"original_chunks={original_count}")
    print(f"unique_chunks={unique_count}")
    print(f"duplicates_removed={duplicate_count}")
    print(f"duplicate_indexes={duplicate_indexes}")


def ingest_document(client: Any, document: Any, settings: Settings, *, embedder=embed_texts, version_tag: str = "unified_v1") -> tuple[str, int]:
    location_code = str(document.metadata.get("location_code", "raipur")).strip().casefold()
    version = f"{document.checksum}:{location_code}_{version_tag}"
    existing = _at_stage(
        "fetch_existing_document",
        lambda: _rows(client.table("knowledge_documents").select("id,document_version,is_active").eq("source_file", document.source_file).execute()),
    )
    if any(row.get("document_version") == version and row.get("is_active") is True for row in existing):
        return "unchanged", 0
    document_stage = "update_document" if existing else "insert_document"
    staged = _at_stage(
        document_stage,
        lambda: _rows(client.table("knowledge_documents").upsert({"source_file": document.source_file, "document_version": version, "approved_by": f"{location_code}_knowledge_ingestion", "is_active": False, "metadata": document.metadata | {"ingestion_status": "staging"}}, on_conflict="source_file,document_version").execute()),
    )
    if not staged or not isinstance(staged[0].get("id"), str):
        raise IngestionStageError(document_stage, RuntimeError("document_upsert_failed"))
    identifier = staged[0]["id"]
    original_chunks = _chunks(document)
    chunks, duplicate_groups = _deduplicate_chunks(original_chunks)
    _print_chunk_deduplication(Path(document.source_file).name, len(original_chunks), len(chunks), duplicate_groups)
    vectors = _at_stage("generate_embeddings", lambda: embedder([chunk["content"] for chunk in chunks], settings))
    if len(vectors) != len(chunks):
        raise IngestionStageError("generate_embeddings", RuntimeError("embedding_count_mismatch"))
    payload = [{"knowledge_document_id": identifier, "chunk_index": chunk["index"], "content": chunk["content"], "content_hash": chunk_hash(chunk["content"]), "embedding": "[" + ",".join(format(value, ".17g") for value in vector) + "]", "metadata": chunk["metadata"]} for chunk, vector in zip(chunks, vectors, strict=True)]
    _at_stage("insert_chunks", lambda: client.table("knowledge_chunks").upsert(payload, on_conflict="knowledge_document_id,content_hash").execute())
    stored_chunks = _at_stage("insert_chunks", lambda: _rows(client.table("knowledge_chunks").select("id").eq("knowledge_document_id", identifier).execute()))
    if len(stored_chunks) < len(chunks):
        raise IngestionStageError("insert_chunks", RuntimeError("staged_chunks_incomplete"))
    _at_stage("activate_document", lambda: client.table("knowledge_documents").update({"is_active": True, "metadata": document.metadata | {"ingestion_status": "ready"}}).eq("id", identifier).execute())
    _at_stage("deactivate_legacy_document", lambda: client.table("knowledge_documents").update({"is_active": False}).eq("source_file", document.source_file).neq("id", identifier).eq("is_active", True).execute())
    return ("updated" if existing else "created"), len(chunks)


def deactivate_obsolete_active_documents(client: Any, document: Any) -> int:
    """Deactivate only same-service or legacy-location records after a verified replacement."""

    rows = _at_stage("deactivate_legacy_document", lambda: _rows(client.table("knowledge_documents").select("id,source_file,metadata").eq("is_active", True).execute()))
    target_code = document.metadata.get("service_code")
    target_location = document.metadata.get("knowledge_type") == "location"
    changed = 0
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        same_service = isinstance(target_code, str) and target_code and metadata.get("service_code") == target_code
        legacy_location = target_location and metadata.get("document_category") == "location_information"
        if row.get("source_file") == document.source_file or not (same_service or legacy_location):
            continue
        if isinstance(row.get("id"), str):
            _at_stage("deactivate_legacy_document", lambda: client.table("knowledge_documents").update({"is_active": False}).eq("id", row["id"]).execute())
            changed += 1
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--dry-run", action="store_true"); args = parser.parse_args()
    plan, errors = build_plan(ROOT); eligible = [row.document for row in plan if row.document]
    print(f"mode={'dry_run' if args.dry_run else 'live'} manifest_path={manifest_path(ROOT).name} manifest_rows={len(plan)} eligible_rows={len(eligible)}")
    for row in plan: print(f"document filename={Path(row.source_file).name if row.source_file else 'unknown'} status={row.status} reason={row.reason}")
    if args.dry_run:
        active_root = ROOT / "documents" / "raipur" / "active"
        active_files = {path.relative_to(ROOT / "documents" / "raipur").as_posix() for path in active_root.rglob("*.md")}
        manifest_files = {row.source_file for row in plan if row.source_file}
        missing = sum(row.reason == "missing_markdown" for row in plan)
        unmanifested = len(active_files - manifest_files)
        front_matter_mismatches = sum(row.reason == "front_matter_manifest_mismatch" for row in plan)
        codes = [document.metadata.get("service_code") for document in eligible if document.metadata.get("service_code")]
        duplicate_service_codes = len(codes) - len(set(codes))
        print(f"dry_run_complete missing_files={missing} unmanifested_active_files={unmanifested} frontmatter_mismatches={front_matter_mismatches} duplicate_service_codes={duplicate_service_codes} errors={len(errors)} writes=0 embedding_calls=0"); return 1 if errors else 0
    if errors: print("ingestion_refused validation_errors=true"); return 1
    settings = Settings()
    if not settings.embedding_configuration_is_valid(): print("ingestion_refused embedding_configuration_incomplete=true"); return 1
    filename = "none"
    stage = "initialize_client"
    try:
        client = _at_stage(stage, get_supabase_client); total = 0
        for document in eligible:
            filename = Path(document.source_file).name
            print(f"ingestion_start filename={filename}")
            stage = "fetch_existing_document"
            status, count = ingest_document(client, document, settings); total += count
            deactivate_obsolete_active_documents(client, document)
            print(f"ingestion_result filename={filename} status={status} chunks={count}")
    except IngestionStageError as failure:
        _print_ingestion_failure(filename, failure.stage, failure.error); return 1
    except Exception as error:
        _print_ingestion_failure(filename, stage, error); return 1
    print(f"ingestion_complete documents={len(eligible)} chunks_created={total}"); return 0


if __name__ == "__main__": raise SystemExit(main())
