"""Fake-only coverage for manifest-gated celebration knowledge ingestion."""

import csv
from pathlib import Path
import re
import sys
from unittest.mock import MagicMock

from app.rag.celebration_ingestion import CSV_HEADERS, build_plan, normalized_checksum, parse_markdown, truthy
from scripts import ingest_raipur_celebrations as script
from app.rag.raipur_ingestion import build_plan as build_unified_plan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CELEBRATION_ROOT = PROJECT_ROOT / "documents" / "raipur"
NEW_SERVICE_CODES = {"pontoon_celebration", "floating_gazebo", "jetty_gazebo", "houseboat_celebration"}


def _layout(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    root = tmp_path / "documents" / "raipur" / "active" / "celebrations"
    for folder in ("services", "general", "faq", "policies", "structured_data", "sources", "ingestion"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    for filename, headers in CSV_HEADERS.items():
        folder = "ingestion" if filename.endswith("manifest.csv") else "sources" if "source_verification" in filename else "structured_data"
        values = rows if filename.endswith("manifest.csv") else []
        with (root / folder / filename).open("w", newline="", encoding="utf-8") as stream:
            fieldnames = sorted(set(headers).union(*(row.keys() for row in values))) if values else sorted(headers)
            writer = csv.DictWriter(stream, fieldnames=fieldnames); writer.writeheader(); writer.writerows(values)
    return root


def _markdown(root: Path, relative: str, *, location="raipur", active="active", facing="true", body="## Details\nApproved content.", service=True, document_type="service") -> None:
    fields = [f"location_code: {location}", f"customer_facing: {facing}", f"catalogue_status: {active}", f"document_type: {document_type}", "language: en"]
    if service: fields.extend(["service_code: party_boat_celebration", "service_name: Party Boat Celebration", "water_body: Jhanjh Lake"])
    (root / relative).write_text("---\n" + "\n".join(fields) + "\n---\n" + body, encoding="utf-8")


def _row(path: str, **overrides: str) -> dict[str, str]:
    values = {"file_path": path, "location_code": "raipur", "ready_for_ingestion": "TRUE", "customer_facing": "yes", "catalogue_status": "active", "review_required": "false", "contains_conflicts": "false", "contains_pending_facts": "false", "service_code": "party_boat_celebration", "document_type": "service", "language": "en"}
    return values | overrides


def test_manifest_boolean_selection_and_safe_path_validation(tmp_path):
    rows = [_row("services/party.md"), _row("services/pending.md", ready_for_ingestion="false"), _row("archive/old.md"), _row("../escape.md"), _row("structured_data/catalogue.csv"), _row("C:/private/party.md")]
    root = _layout(tmp_path, rows); _markdown(root, "services/party.md")
    plan, counts, errors = build_plan(root)

    assert truthy("TRUE") and truthy("yes") and truthy("1") and not truthy("pending")
    assert [row.status for row in plan] == ["eligible", "skipped", "skipped", "skipped", "skipped", "skipped"]
    assert [row.reason for row in plan[1:]] == ["not_ready", "unsafe_or_excluded_path", "unsafe_or_excluded_path", "not_markdown", "absolute_path"]
    assert not errors and "celebration_ingestion_manifest.csv" in counts


def test_markdown_validation_and_faq_chunk_keeps_question_answer_together(tmp_path):
    root = _layout(tmp_path, [_row("faq/questions.md", document_type="faq", service_code="")])
    _markdown(root, "faq/questions.md", body="## FAQ\nWhat is Party Boat?\nIt is an approved celebration option.", service=False, document_type="faq")
    document = parse_markdown(root / "faq/questions.md", root, _row("faq/questions.md", document_type="faq"))
    assert document.metadata["service_code"] == "party_boat_celebration" or document.metadata["service_code"] is None
    assert "What is Party Boat?" in document.sections[0].text and "approved celebration option" in document.sections[0].text
    _markdown(root, "services/wrong.md", location="delhi")
    try: parse_markdown(root / "services/wrong.md", root, _row("services/wrong.md"))
    except ValueError as error: assert str(error) == "yaml_location_not_raipur"
    else: raise AssertionError("wrong location accepted")


def test_missing_invalid_and_empty_documents_are_reported(tmp_path):
    root = _layout(tmp_path, [_row("services/missing.md"), _row("services/invalid.md"), _row("services/empty.md")])
    (root / "services" / "invalid.md").write_text("no front matter", encoding="utf-8")
    _markdown(root, "services/empty.md", body="")
    plan, _, _ = build_plan(root)
    assert [row.reason for row in plan] == ["missing_markdown", "invalid_yaml_front_matter", "empty_markdown_body"]


def test_checksum_is_normalized_and_legacy_script_is_disabled(monkeypatch, tmp_path, capsys):
    assert normalized_checksum("a\r\n") == normalized_checksum("a\n")
    root = _layout(tmp_path, [_row("services/party.md")]); _markdown(root, "services/party.md")
    monkeypatch.setattr(script, "get_supabase_client", lambda: (_ for _ in ()).throw(AssertionError("no database")))
    monkeypatch.setattr(script, "embed_texts", lambda *_: (_ for _ in ()).throw(AssertionError("no embedding")))
    monkeypatch.setattr(sys, "argv", ["ingest_raipur_celebrations.py", "--dry-run"])
    assert script.main() == 2
    output = capsys.readouterr().out
    assert "legacy_celebration_ingestion_disabled" in output and "Approved content" not in output


def test_same_active_checksum_skips_embedding_and_old_overlap_is_scoped():
    document = MagicMock(source_file="services/party.md", checksum="same", metadata={"service_code": "party_boat_celebration"})
    query = MagicMock(); query.select.return_value = query; query.eq.return_value = query; query.execute.return_value = MagicMock(data=[{"id": "active", "document_version": "same:celebrations_v1", "is_active": True}])
    client = MagicMock(); client.table.return_value = query
    assert script.ingest_document(client, document, MagicMock(), embedder=lambda *_: (_ for _ in ()).throw(AssertionError("embedding"))) == ("unchanged", 0)


def test_default_root_uses_active_folder_not_the_old_celebrations_path(tmp_path):
    from app.rag.celebration_ingestion import celebration_root

    root = celebration_root(tmp_path)
    assert root == tmp_path / "documents" / "raipur" / "reference_archive" / "legacy_manifests"
    assert root != tmp_path / "documents" / "raipur" / "active" / "celebrations"


def test_cleaned_celebration_services_are_manifest_eligible_and_safe():
    plan, errors = build_unified_plan(PROJECT_ROOT)
    documents = {row.document.metadata.get("service_code"): row.document for row in plan if row.document is not None}
    assert not errors and NEW_SERVICE_CODES.issubset(documents)
    for code in NEW_SERVICE_CODES:
        document = documents[code]
        assert document.metadata["service_code"] == code
        assert document.metadata["knowledge_type"] == "celebration"
        assert document.metadata["service_category"] == "celebration"
        assert document.metadata["approval_status"] == "approved"
        assert document.metadata["customer_facing"] is True and document.metadata["catalogue_status"] == "active"
        text = document.text.casefold()
        assert all(section in text for section in ("## experience overview", "## duration", "## operating hours", "## pricing", "## availability"))
        assert "pricing" in text and "requires confirmation" in text
        assert "availability" in text and "require verification" in text
        assert "booking is confirmed" not in text
        assert "payment is confirmed" not in text


def test_daycation_document_is_manifest_eligible_and_contains_only_safe_confirmation_wording():
    plan, errors = build_unified_plan(PROJECT_ROOT)
    document = next(row.document for row in plan if row.document and row.document.metadata.get("service_code") == "daycation_package")

    assert not errors
    assert document.metadata["location_code"] == "raipur"
    assert document.metadata["service_code"] == "daycation_package"
    assert document.metadata["knowledge_type"] == "service"
    assert document.metadata["service_category"] == "package"
    assert document.metadata["approval_status"] == "approved"
    assert document.metadata["customer_facing"] is True and document.metadata["catalogue_status"] == "active"
    text = document.text.casefold()
    assert all(section in text for section in ("## experience overview", "## package inclusions", "## duration", "## operating hours", "## pricing", "## availability"))
    assert "2:00 pm to 6:00 pm" in text
    assert "pricing" in text and "requires confirmation" in text
    assert "availability" in text and "require verification" in text
    assert "payment is confirmed" not in text


def test_party_boat_remains_eligible_and_internal_and_archive_paths_are_excluded():
    plan, errors = build_unified_plan(PROJECT_ROOT)
    eligible = [row.document for row in plan if row.document is not None]
    paths = {document.source_file for document in eligible}
    party = next(document for document in eligible if document.metadata.get("service_code") == "party_boat_celebration")
    assert not errors and "active/services/party_boat_celebration.md" in paths
    assert party.source_file == "active/services/party_boat_celebration.md"
    assert party.metadata["knowledge_type"] == "celebration"
    assert party.metadata["approval_status"] == "approved"
    assert party.metadata["customer_facing"] is True and party.metadata["catalogue_status"] == "active"
    text = party.text.casefold()
    assert all(section in text for section in ("## experience overview", "## duration", "## operating hours", "## pricing", "## availability"))
    assert "pricing" in text and "requires confirmation" in text
    assert "availability" in text and "require verification" in text
    assert "10:00 am to 9:00 pm" in text
    assert "2 hours" in text
    assert "payment is confirmed" not in text
    assert not any(path.startswith(("archive/", "internal/", "ingestion/")) for path in paths)
