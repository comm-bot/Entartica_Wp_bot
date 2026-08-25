"""Dry-run-first ingestion for the single Coimbatore master Markdown file."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.rag.coimbatore_ingestion import build_coimbatore_master
from scripts.ingest_raipur_knowledge import _chunks, ingest_document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        document = build_coimbatore_master(ROOT)
        chunks = _chunks(document)
    except ValueError as error:
        print(f"coimbatore_ingestion_refused reason={error}")
        return 1
    print(f"mode={'dry_run' if args.dry_run else 'live'} source_file={document.source_file} physical_files=1 sections={len(document.sections)} chunks={len(chunks)} location_code=coimbatore")
    if not chunks or any(not chunk["content"].strip() for chunk in chunks):
        print("coimbatore_ingestion_refused reason=invalid_chunks")
        return 1
    if args.dry_run:
        print("dry_run_complete errors=0 writes=0 embedding_calls=0")
        return 0
    settings = Settings()
    if not settings.embedding_configuration_is_valid():
        print("coimbatore_ingestion_refused reason=embedding_configuration_incomplete")
        return 1
    # v2 records the canonical customer-package-block chunking contract. This
    # intentionally regenerates embeddings once even when the Markdown checksum
    # was already seen under the older chunking version.
    status, count = ingest_document(
        get_supabase_client(), document, settings, version_tag="canonical_packages_v2"
    )
    print(f"ingestion_complete status={status} documents=1 chunks={count} location_code=coimbatore")
    return 0


if __name__ == "__main__": raise SystemExit(main())
