"""Read-only Raipur knowledge inventory with an optional read-only database comparison."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import sys
from datetime import datetime, timezone
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rag.raipur_ingestion import PlanRow, build_plan
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, knowledge_service_code


INVENTORY_HEADERS = (
    "file_path", "file_name", "file_type", "location_code", "service_code",
    "document_category", "customer_facing", "catalogue_status", "manifest_referenced",
    "ready_for_ingestion", "currently_ingested", "currently_active_in_database",
    "duplicate_of", "contains_unverified_facts", "contains_conflicts", "final_action", "notes",
)
COVERAGE_HEADERS = (
    "service_code", "service_name", "document_found", "manifest_eligible", "database_active",
    "retrieval_working", "missing_information", "recommended_action",
)
GENERATED_SUFFIXES = (".backup", ".repair-backup", ".path-backup")


@dataclass(frozen=True)
class DatabaseState:
    source_files: frozenset[str] = frozenset()
    active_source_files: frozenset[str] = frozenset()
    document_versions: dict[str, tuple[tuple[str, bool], ...]] | None = None
    error: str | None = None


def _front_matter(path: Path) -> dict[str, str]:
    if path.suffix.casefold() != ".md":
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        return {}
    end = raw.find("\n---", 4)
    if end < 0:
        return {}
    fields: dict[str, str] = {}
    for line in raw[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def _plan_by_source(plan: list[PlanRow]) -> dict[str, PlanRow]:
    return {row.source_file: row for row in plan if row.source_file}


def build_inventory(project_root: Path, database: DatabaseState | None = None) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    """Classify every Raipur repository document without treating folder names as approval."""

    raipur_root = project_root / "documents" / "raipur"
    plan, errors = build_plan(project_root)
    by_source = _plan_by_source(plan)
    database_checked = database is not None
    database = database or DatabaseState()
    rows: list[dict[str, str]] = []
    canonical_service_sources: dict[str, str] = {}
    eligible_sources = {row.source_file for row in plan if row.document is not None}

    for path in sorted(item for item in raipur_root.rglob("*") if item.is_file()):
        relative = path.relative_to(raipur_root).as_posix()
        metadata = _front_matter(path)
        source_relative = relative
        plan_row = by_source.get(source_relative)
        is_generated = path.name.endswith(GENERATED_SUFFIXES)
        is_archive = "reference_archive" in path.parts
        is_internal = any(part in {"governance", "internal", "sources", "structured_data", "ingestion"} for part in path.parts)
        eligible = source_relative in eligible_sources
        document = plan_row.document if plan_row and plan_row.document is not None else None
        expected_version = f"{document.checksum}:raipur_unified_v1" if document is not None else None
        versions = (database.document_versions or {}).get(source_relative, ())
        exact_ingested = (source_relative in database.source_files) if database.document_versions is None else (any(version == expected_version for version, _active in versions) if expected_version else False)
        exact_active = (source_relative in database.active_source_files) if database.document_versions is None else (any(version == expected_version and active for version, active in versions) if expected_version else False)
        service_code = metadata.get("service_code", "")
        if path.name in {"raipur_knowledge_inventory.csv", "raipur_service_coverage.csv"}:
            action, notes = "keep_internal", "Generated governance report; never embedded."
        elif is_generated:
            action, notes = "delete_generated_duplicate", "Generated backup; not a knowledge source."
        elif is_archive:
            action, notes = "archive_obsolete", "Archive evidence; never eligible for retrieval."
        elif is_internal:
            action, notes = "keep_internal", "Internal governance or source material; never embedded."
        elif eligible:
            action, notes = "activate_and_ingest", "Manifest-approved customer-facing Markdown."
            if service_code:
                canonical_service_sources[service_code] = source_relative
        else:
            action, notes = "pending_management_confirmation", f"Not eligible: {plan_row.reason if plan_row else 'unmanifested_active_file'}."
        rows.append({
            "file_path": relative, "file_name": path.name, "file_type": path.suffix.lstrip(".").casefold() or "none",
            "location_code": metadata.get("location_code", "raipur" if "active" in path.parts else ""),
            "service_code": service_code, "document_category": metadata.get("document_type", "internal" if is_internal else "archive" if is_archive else "unknown"),
            "customer_facing": metadata.get("customer_facing", "false").casefold(), "catalogue_status": metadata.get("catalogue_status", "archived" if is_archive else "internal" if is_internal else "unknown"),
            "manifest_referenced": str(plan_row is not None).lower(), "ready_for_ingestion": str(eligible).lower(),
            "currently_ingested": str(exact_ingested).lower() if database_checked else "unverified",
            "currently_active_in_database": str(exact_active).lower() if database_checked else "unverified",
            "duplicate_of": "", "contains_unverified_facts": "false" if eligible or is_internal or is_archive or path.name.startswith("raipur_") else "true",
            "contains_conflicts": "false", "final_action": action,
            "notes": notes if not (eligible and source_relative in database.source_files and not exact_ingested) else f"{notes} Database checksum mismatch; re-ingest required.",
        })

    coverage: list[dict[str, str]] = []
    for service in APPROVED_RAIPUR_SERVICES:
        source = canonical_service_sources.get(knowledge_service_code(service))
        coverage.append({
            "service_code": knowledge_service_code(service), "service_name": service.name, "document_found": str(source is not None).lower(),
            "manifest_eligible": str(source in eligible_sources if source else False).lower(),
            "database_active": str(any(row["file_path"] == source and row["currently_active_in_database"] == "true" for row in rows) if source else False).lower() if database_checked else "unverified",
            "retrieval_working": "not_run", "missing_information": "" if source else "No approved canonical customer-facing document.",
            "recommended_action": "keep_active" if source else "pending_management_confirmation",
        })
    return rows, coverage, errors


def read_database_state() -> DatabaseState:
    """Read only source-file/activity fields; provider errors remain private."""

    try:
        from app.integrations.supabase import get_supabase_client

        response = get_supabase_client().table("knowledge_documents").select("source_file,document_version,is_active,metadata").execute()
        data = getattr(response, "data", None)
        records = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        source_files: set[str] = set()
        active_source_files: set[str] = set()
        versions: dict[str, list[tuple[str, bool]]] = {}
        for row in records:
            if not isinstance(row, dict):
                continue
            source = row.get("source_file")
            metadata = row.get("metadata")
            if isinstance(source, str) and isinstance(metadata, dict) and metadata.get("location_code") == "raipur":
                source_files.add(source)
                version = row.get("document_version")
                if isinstance(version, str):
                    versions.setdefault(source, []).append((version, row.get("is_active") is True))
                if row.get("is_active") is True:
                    active_source_files.add(source)
        return DatabaseState(frozenset(source_files), frozenset(active_source_files), {key: tuple(value) for key, value in versions.items()})
    except Exception:
        return DatabaseState(error="database_comparison_unavailable")


def _write_csv(path: Path, headers: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", action="store_true", help="Perform the read-only Supabase comparison.")
    args = parser.parse_args()
    database = read_database_state() if args.database else DatabaseState()
    inventory, coverage, errors = build_inventory(ROOT, database)
    report_root = ROOT / "documents" / "raipur" / "governance" / "reports"
    report_root.mkdir(parents=True, exist_ok=True)
    _write_csv(report_root / "raipur_knowledge_inventory.csv", INVENTORY_HEADERS, inventory)
    _write_csv(report_root / "raipur_service_coverage.csv", COVERAGE_HEADERS, coverage)
    eligible = sum(row["ready_for_ingestion"] == "true" for row in inventory)
    generated = sum(row["final_action"] == "delete_generated_duplicate" for row in inventory)
    comparison = database.error or ("completed" if args.database else "not_requested")
    print(f"mode=raipur_inventory generated_at={datetime.now(timezone.utc).isoformat()} files={len(inventory)} eligible_documents={eligible} generated_duplicates={generated} validation_errors={len(errors)} database_comparison={comparison}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
