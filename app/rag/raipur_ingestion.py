"""Validated, manifest-only ingestion plan for the unified Raipur corpus."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.rag.knowledge import KnowledgeSection

MANIFEST_HEADERS = {
    "document_path", "location_code", "knowledge_type", "service_category", "service_code", "service_name",
    "customer_facing", "catalogue_status", "approval_status", "ready_for_ingestion", "review_required",
    "contains_pending_facts", "contains_conflicts", "retrieval_priority",
}
KNOWLEDGE_TYPES = {"service", "celebration", "general", "faq", "policy", "location"}
EXCLUDED_PARTS = {"archive", "internal", "ingestion", "sources", "structured_data", "governance", "reference_archive"}


def truthy(value: object) -> bool:
    return isinstance(value, str) and value.strip().casefold() in {"true", "yes", "1"}


def normalized_checksum(value: str) -> str:
    return sha256("\n".join(line.rstrip() for line in value.replace("\r\n", "\n").splitlines()).strip().encode()).hexdigest()


@dataclass(frozen=True)
class UnifiedDocument:
    source_file: str
    metadata: dict[str, Any]
    text: str
    checksum: str
    sections: tuple[KnowledgeSection, ...]

    @property
    def category(self) -> str:
        return str(self.metadata["knowledge_type"])


@dataclass(frozen=True)
class PlanRow:
    source_file: str
    document: UnifiedDocument | None
    status: str
    reason: str


def manifest_path(project_root: Path) -> Path:
    return project_root / "documents" / "raipur" / "governance" / "manifests" / "raipur_knowledge_manifest.csv"


def _front_matter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        raise ValueError("invalid_yaml_front_matter")
    end = raw.find("\n---", 4)
    if end < 0:
        raise ValueError("invalid_yaml_front_matter")
    result: dict[str, str] = {}
    for line in raw[4:end].splitlines():
        if ":" not in line:
            raise ValueError("invalid_yaml_front_matter")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or key in result:
            raise ValueError("invalid_yaml_front_matter")
        result[key] = value.strip().strip("\"'")
    return result, raw[end + 4:]


def _sections(body: str) -> tuple[KnowledgeSection, ...]:
    heading = "General"; buffer: list[str] = []; output: list[KnowledgeSection] = []
    for line in body.splitlines():
        if line.startswith("#") and line.lstrip("#").startswith(" "):
            if buffer:
                output.append(KnowledgeSection(heading, None, "\n".join(buffer).strip()))
            heading, buffer = line.lstrip("#").strip(), []
        elif line.strip():
            buffer.append(line.strip())
    if buffer:
        output.append(KnowledgeSection(heading, None, "\n".join(buffer).strip()))
    return tuple(output)


def build_plan(project_root: Path) -> tuple[list[PlanRow], list[str]]:
    root = project_root / "documents" / "raipur"
    path = manifest_path(project_root)
    if not path.is_file():
        return [], ["missing_manifest"]
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not MANIFEST_HEADERS.issubset(set(reader.fieldnames or [])):
            return [], ["invalid_manifest_headers"]
        manifest_rows = list(reader)
    plan: list[PlanRow] = []; errors: list[str] = []; seen: set[str] = set()
    for row in manifest_rows:
        source = str(row.get("document_path", "")).strip().replace("\\", "/")
        parts = Path(source).parts
        if source in seen:
            plan.append(PlanRow(source, None, "skipped", "duplicate_path")); continue
        seen.add(source)
        if not source or Path(source).is_absolute() or ".." in parts or any(part.casefold() in EXCLUDED_PARTS for part in parts):
            plan.append(PlanRow(source, None, "skipped", "unsafe_path")); continue
        if Path(source).suffix.casefold() != ".md":
            plan.append(PlanRow(source, None, "skipped", "not_markdown")); continue
        if row.get("knowledge_type", "").strip() not in KNOWLEDGE_TYPES:
            plan.append(PlanRow(source, None, "skipped", "invalid_knowledge_type")); continue
        if not (row.get("location_code", "").strip() == "raipur" and truthy(row.get("customer_facing")) and row.get("catalogue_status", "").strip() == "active" and row.get("approval_status", "").strip() == "approved" and truthy(row.get("ready_for_ingestion"))):
            plan.append(PlanRow(source, None, "skipped", "manifest_not_approved_active")); continue
        if any(truthy(row.get(name)) for name in ("review_required", "contains_pending_facts", "contains_conflicts")):
            plan.append(PlanRow(source, None, "skipped", "review_or_pending")); continue
        target = (root / source).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            plan.append(PlanRow(source, None, "skipped", "unsafe_path")); continue
        if not target.is_file():
            plan.append(PlanRow(source, None, "skipped", "missing_markdown")); continue
        try:
            metadata, body = _front_matter(target.read_text(encoding="utf-8"))
            if not body.strip():
                raise ValueError("empty_markdown_body")
            for key in ("location_code", "service_code", "service_name", "customer_facing", "catalogue_status", "approval_status", "knowledge_type", "service_category", "retrieval_priority"):
                if row.get(key, "").strip() and metadata.get(key, "").strip() != row[key].strip():
                    raise ValueError("front_matter_manifest_mismatch")
            if row.get("knowledge_type") in {"service", "celebration"} and (not metadata.get("service_code") or not metadata.get("service_name")):
                raise ValueError("service_identity_missing")
            sections = _sections(body)
            if not sections:
                raise ValueError("empty_markdown_body")
            stored = {key: row[key].strip() for key in MANIFEST_HEADERS if key in row}
            stored["customer_facing"] = True
            stored["ready_for_ingestion"] = True
            stored["review_required"] = False
            stored["contains_pending_facts"] = False
            stored["contains_conflicts"] = False
            stored.update({"document_path": source, "document_checksum": normalized_checksum(body), "active": True, "is_active": True})
            plan.append(PlanRow(source, UnifiedDocument(source, stored, body.strip(), normalized_checksum(body), sections), "eligible", "ready"))
        except ValueError as error:
            plan.append(PlanRow(source, None, "skipped", str(error)))
    return plan, errors
