"""Validation plan for the single externally-metadata-scoped Coimbatore master KB."""
from __future__ import annotations

from pathlib import Path

from app.rag.raipur_ingestion import UnifiedDocument, _sections, normalized_checksum


def build_coimbatore_master(root: Path) -> UnifiedDocument:
    active = root / "documents" / "coimbatore" / "active"
    files = tuple(active.glob("*.md")) if active.is_dir() else ()
    if len(files) != 1:
        raise ValueError("coimbatore_active_requires_exactly_one_markdown")
    source = files[0]
    text = source.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("empty_markdown_body")
    sections = _sections(text)
    if not sections or not any(line.startswith("#") for line in text.splitlines()):
        raise ValueError("markdown_headings_required")
    relative = source.relative_to(root).as_posix()
    checksum = normalized_checksum(text)
    metadata = {
        "document_path": relative,
        "source_filename": source.name,
        "location_code": "coimbatore",
        "knowledge_type": "general",
        "service_category": "master_knowledge",
        "customer_facing": True,
        "catalogue_status": "active",
        "approval_status": "approved",
        "ready_for_ingestion": True,
        "review_required": False,
        "retrieval_priority": "high",
        "document_checksum": checksum,
        "active": True,
        "is_active": True,
    }
    return UnifiedDocument(relative, metadata, text.strip(), checksum, sections)
