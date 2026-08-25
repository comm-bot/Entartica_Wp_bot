"""Local-only inventory coverage for the canonical Raipur knowledge tree."""

from pathlib import Path

from scripts.audit_raipur_knowledge_inventory import DatabaseState, build_inventory


ROOT = Path(__file__).resolve().parents[1]


def test_inventory_classifies_every_raipur_file_and_only_manifest_rows_are_eligible() -> None:
    inventory, coverage, errors = build_inventory(ROOT)

    assert not errors
    assert inventory
    assert all(row["final_action"] for row in inventory)
    assert all(row["final_action"] != "pending_management_confirmation" for row in inventory)
    active = [row for row in inventory if row["ready_for_ingestion"] == "true"]
    assert len(active) == 23
    assert all(row["final_action"] == "activate_and_ingest" for row in active)
    assert all(row["final_action"] == "keep_internal" for row in inventory if "structured_data/" in row["file_path"])
    assert all(row["final_action"] == "archive_obsolete" for row in inventory if row["file_path"].startswith("archive/"))
    assert len(coverage) == 19


def test_inventory_marks_only_matching_database_source_files_as_active() -> None:
    state = DatabaseState(frozenset({"active/services/daycation_package.md"}), frozenset({"active/services/daycation_package.md"}))
    inventory, coverage, _errors = build_inventory(ROOT, state)

    daycation = next(row for row in inventory if row["file_path"].endswith("daycation_package.md"))
    assert daycation["currently_ingested"] == "true"
    assert daycation["currently_active_in_database"] == "true"
    coverage_row = next(row for row in coverage if row["service_code"] == "daycation_package")
    assert coverage_row["document_found"] == "true"
    assert coverage_row["database_active"] == "true"
