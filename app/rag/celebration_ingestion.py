"""Safe manifest validation for Raipur celebration Markdown ingestion."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from app.rag.knowledge import KnowledgeSection

EXCLUDED_PARTS = {"archive", "sources", "ingestion", "structured_data"}
CSV_HEADERS = {
    "celebration_service_catalogue.csv": {"location_code", "service_code", "service_name", "catalogue_status"},
    "celebration_operational_information.csv": {"location_code", "service_code", "service_name", "information_type", "value", "verification_status"},
    "celebration_service_aliases.csv": {"location_code", "service_code", "canonical_service_name", "language", "alias"},
    "celebration_language_variations.csv": {"location_code", "service_code", "service_name", "language", "customer_question", "normalized_intent"},
    "celebration_source_verification_register.csv": {"location_code", "service_code", "service_name", "verification_status", "customer_content_action"},
    "celebration_ingestion_manifest.csv": {"file_path", "location_code", "ready_for_ingestion"},
}

def truthy(value: object) -> bool: return isinstance(value, str) and value.strip().casefold() in {"true", "yes", "1"}
def normalized_checksum(value: str) -> str: return sha256("\n".join(line.rstrip() for line in value.replace("\r\n", "\n").splitlines()).strip().encode()).hexdigest()
def celebration_root(project_root: Path) -> Path: return project_root / "documents" / "raipur" / "reference_archive" / "legacy_manifests"

@dataclass(frozen=True)
class CelebrationDocument:
    source_file: str; metadata: dict[str, Any]; text: str; checksum: str; sections: tuple[KnowledgeSection, ...]
    @property
    def category(self) -> str: return str(self.metadata.get("document_type", "celebration"))
@dataclass(frozen=True)
class PlanRow:
    source_file: str; document: CelebrationDocument | None; status: str; reason: str

def parse_markdown(path: Path, root: Path, manifest: dict[str, str]) -> CelebrationDocument:
    raw = path.read_text(encoding="utf-8"); metadata, body = _front_matter(raw)
    if not body.strip(): raise ValueError("empty_markdown_body")
    if metadata.get("location_code", "").casefold() != "raipur": raise ValueError("yaml_location_not_raipur")
    if not truthy(metadata.get("customer_facing", "")) or metadata.get("catalogue_status", "").casefold() != "active": raise ValueError("yaml_not_customer_facing_active")
    document_type = metadata.get("document_type", manifest.get("document_type", "")).strip()
    if not document_type: raise ValueError("yaml_document_type_missing")
    if document_type == "service" and (not metadata.get("service_code", "").strip() or not metadata.get("service_name", "").strip()): raise ValueError("yaml_service_identity_missing")
    if metadata.get("water_body") and metadata["water_body"].strip() != "Jhanjh Lake": raise ValueError("yaml_water_body_invalid")
    sections = tuple(_sections(body))
    if not sections: raise ValueError("empty_markdown_body")
    source = path.resolve().relative_to(root.resolve()).as_posix(); checksum = normalized_checksum(body)
    stored = {"location_code":"raipur", "knowledge_category":"celebration", "service_code":metadata.get("service_code") or manifest.get("service_code") or None, "service_name":metadata.get("service_name") or None, "document_type":document_type, "language":metadata.get("language") or manifest.get("language") or "en", "customer_facing":True, "catalogue_status":"active", "source_file":source, "content_checksum":checksum, "approval_status":"approved", "is_active":True}
    return CelebrationDocument(source, stored, body.strip(), checksum, sections)

def build_plan(root: Path) -> tuple[list[PlanRow], dict[str, int], list[str]]:
    errors: list[str] = []; counts: dict[str, int] = {}
    for filename, required in CSV_HEADERS.items():
        folder = "ingestion" if filename.endswith("manifest.csv") else "sources" if "source_verification" in filename else "structured_data"; path = root / folder / filename
        if not path.is_file(): errors.append(f"missing_csv:{filename}"); continue
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not required.issubset(set(reader.fieldnames or [])): errors.append(f"invalid_csv_headers:{filename}")
            else: counts[filename] = sum(1 for _ in reader)
    manifest = root / "ingestion" / "celebration_ingestion_manifest.csv"
    if not manifest.is_file(): return [], counts, errors
    with manifest.open(encoding="utf-8-sig", newline="") as stream: rows = list(csv.DictReader(stream))
    plan: list[PlanRow] = []; seen: set[str] = set()
    for row in rows:
        value = str(row.get("file_path", "")).strip().replace("\\", "/"); parts = set(Path(value).parts)
        if value in seen: plan.append(PlanRow(value,None,"skipped","duplicate_path")); continue
        seen.add(value)
        if not value or Path(value).suffix.casefold() != ".md": reason="not_markdown"
        elif Path(value).is_absolute(): reason="absolute_path"
        elif ".." in Path(value).parts or {part.casefold() for part in parts}&EXCLUDED_PARTS: reason="unsafe_or_excluded_path"
        elif not truthy(row.get("ready_for_ingestion", "")): reason="not_ready"
        elif not truthy(row.get("customer_facing", "")): reason="not_customer_facing"
        elif str(row.get("catalogue_status", "")).casefold() != "active": reason="catalogue_inactive"
        elif str(row.get("location_code", "")).casefold() != "raipur": reason="manifest_location_not_raipur"
        elif any(truthy(row.get(key, "")) for key in ("review_required","contains_conflicts","contains_pending_facts")): reason="review_or_pending"
        else:
            target = (root / value).resolve()
            try: target.relative_to(root.resolve())
            except ValueError: reason="path_traversal"
            else:
                if not target.is_file(): reason="missing_markdown"
                else:
                    try: plan.append(PlanRow(value,parse_markdown(target,root,row),"eligible","ready")); continue
                    except ValueError as error: reason=str(error)
        plan.append(PlanRow(value,None,"skipped",reason))
    return plan, counts, errors

def _front_matter(raw: str) -> tuple[dict[str,str],str]:
    if not raw.startswith("---\n"): raise ValueError("invalid_yaml_front_matter")
    end=raw.find("\n---",4)
    if end<0: raise ValueError("invalid_yaml_front_matter")
    data={}
    for line in raw[4:end].splitlines():
        if ":" not in line: raise ValueError("invalid_yaml_front_matter")
        key,value=line.split(":",1); key=key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",key): raise ValueError("invalid_yaml_front_matter")
        data[key]=value.strip().strip('"\'')
    return data,raw[end+4:]
def _sections(body: str) -> list[KnowledgeSection]:
    heading="General"; buffer=[]; result=[]
    for line in body.splitlines():
        match=re.match(r"^#{1,3}\s+(.+?)\s*$",line)
        if match:
            if buffer: result.append(KnowledgeSection(heading,None,"\n".join(buffer).strip()))
            heading,buffer=match.group(1),[]
        elif line.strip(): buffer.append(line.strip())
    if buffer: result.append(KnowledgeSection(heading,None,"\n".join(buffer).strip()))
    return result
