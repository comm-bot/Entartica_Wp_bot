"""Fake-only unified Raipur corpus and exact-service retrieval coverage."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.rag.raipur_ingestion import build_plan
from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from scripts import ingest_raipur_knowledge as ingestion


ROOT = Path(__file__).resolve().parents[1]


def test_governance_manifest_is_the_only_production_manifest_and_covers_active_markdown():
    manifest = ROOT / "documents/raipur/governance/manifests/raipur_knowledge_manifest.csv"
    legacy = ROOT / "documents/raipur/reference_archive/legacy_manifests/celebration_ingestion_manifest_legacy.csv"
    plan, errors = build_plan(ROOT)
    active = {
        path.relative_to(ROOT / "documents/raipur").as_posix()
        for path in (ROOT / "documents/raipur/active").rglob("*.md")
    }
    sources = {row.source_file for row in plan}

    assert manifest.is_file() and legacy.is_file()
    assert not (ROOT / "documents/raipur/ingestion/raipur_knowledge_manifest.csv").exists()
    assert not errors and active == sources
    assert all(source.startswith("active/") for source in sources)
    assert all(row.document is not None for row in plan)


def test_active_service_files_use_canonical_snake_case_manifest_codes():
    plan, errors = build_plan(ROOT)
    services = [row.document for row in plan if row.document and row.document.metadata["knowledge_type"] in {"service", "celebration"}]

    assert not errors and len(services) == 19
    assert all(document.source_file == f"active/services/{document.metadata['service_code']}.md" for document in services)


def _settings(): return SimpleNamespace(raipur_knowledge_min_confidence=.65)
def _candidate(content, code, priority="service_specific", confidence=.8):
    return {"content": content, "source_filename": f"{code}.md", "confidence": confidence, "metadata": {"location_code":"raipur", "service_code":code, "customer_facing":True, "is_active":True, "approval_status":"approved", "retrieval_priority":priority}}
def _provider(rows):
    return RaipurKnowledgeProvider(object(), _settings(), embed_query_fn=lambda *_:[1], retrieve_candidates_fn=lambda *_args, **_kwargs: rows, answer_generator=lambda row, low_confidence: SimpleNamespace(answer=row["content"]))


def test_daycation_is_unified_service_document_and_has_exact_chunk_metadata():
    plan, errors = build_plan(ROOT)
    document = next(row.document for row in plan if row.document and row.document.source_file == "active/services/daycation_package.md")
    assert not errors and document is not None
    assert not (ROOT / "documents/raipur/active/celebrations/services/daycation_package.md").exists()
    assert document.metadata["knowledge_type"] == "service"
    assert document.metadata["service_category"] == "package"
    assert document.metadata["service_code"] == "daycation_package"
    assert document.metadata["retrieval_priority"] == "service_specific"
    assert all(chunk["metadata"]["service_code"] == "daycation_package" and chunk["metadata"]["active"] is True for chunk in ingestion._chunks(document))


def test_exact_daycation_retrieval_excludes_staycation_and_celebrations():
    provider = _provider([
        _candidate("Staycation Combo content", "staycation_combo", confidence=.99),
        _candidate("Party Boat Celebration content", "party_boat_celebration", confidence=.98),
        _candidate("Daycation generally means a same-day leisure experience without an overnight stay.", "daycation_package", confidence=.70),
    ])
    result = provider.answer_service_details("Tell me about Daycation", "Daycation Package", "daycation_package")
    assert result.text.startswith("Daycation generally means")
    assert "Staycation" not in result.text and "Party Boat" not in result.text


def test_unified_dry_run_is_manifest_only_and_never_constructs_clients(monkeypatch, capsys):
    monkeypatch.setattr(ingestion, "get_supabase_client", lambda: (_ for _ in ()).throw(AssertionError("database")))
    monkeypatch.setattr(ingestion.sys, "argv", ["ingest_raipur_knowledge.py", "--dry-run"])
    assert ingestion.main() == 0
    output = capsys.readouterr().out
    assert "eligible_rows=23" in output and "writes=0" in output and "embedding_calls=0" in output


def test_replacement_deactivates_only_matching_service_or_legacy_location_rows():
    query = MagicMock(); query.select.return_value = query; query.eq.return_value = query; query.update.return_value = query
    query.execute.return_value = MagicMock(data=[
        {"id":"old-daycation", "source_file":"services/daycation_package.md", "metadata":{"service_code":"daycation_package"}},
        {"id":"staycation", "source_file":"services/staycation.md", "metadata":{"service_code":"staycation_combo"}},
    ])
    client = MagicMock(); client.table.return_value = query
    document = SimpleNamespace(source_file="active/services/daycation_package.md", metadata={"service_code":"daycation_package", "knowledge_type":"service"})
    assert ingestion.deactivate_obsolete_active_documents(client, document) == 1
    query.update.assert_called_once_with({"is_active": False})


class _IngestionResponse:
    def __init__(self, data):
        self.data = data


class _IngestionQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.operation = ""
        self.columns = ""

    def select(self, columns):
        self.operation = "select"; self.columns = columns; return self

    def upsert(self, payload, **_kwargs):
        self.operation = "upsert"
        if self.table_name == "knowledge_chunks":
            self.client.chunk_payload = payload
        return self

    def update(self, _payload):
        self.operation = "update"; return self

    def eq(self, *_args): return self
    def neq(self, *_args): return self

    def execute(self):
        if self.table_name == "knowledge_documents" and self.operation == "select":
            return _IngestionResponse(self.client.existing_documents)
        if self.table_name == "knowledge_documents" and self.operation == "upsert":
            return _IngestionResponse([{"id": "document-id"}])
        if self.table_name == "knowledge_chunks" and self.operation == "select":
            return _IngestionResponse([{"id": str(index)} for index in range(len(self.client.chunk_payload))])
        return _IngestionResponse([])


class _IngestionClient:
    def __init__(self, existing_documents=None):
        self.existing_documents = existing_documents or []
        self.chunk_payload = []

    def table(self, table_name):
        return _IngestionQuery(self, table_name)


def _ingestion_document(*texts):
    return SimpleNamespace(
        source_file="active/services/example.md",
        checksum="example-checksum",
        metadata={"location_code": "raipur"},
        sections=tuple(SimpleNamespace(text=text, heading=f"Heading {index}") for index, text in enumerate(texts)),
    )


def test_chunk_deduplication_keeps_first_occurrence_and_safe_diagnostics(capsys):
    chunks = [
        {"index": 0, "content": "first", "metadata": {}},
        {"index": 1, "content": "second", "metadata": {}},
        {"index": 2, "content": "first", "metadata": {}},
    ]
    retained, duplicate_groups = ingestion._deduplicate_chunks(chunks)

    assert [chunk["index"] for chunk in retained] == [0, 1]
    assert [chunk["content"] for chunk in retained] == ["first", "second"]
    assert duplicate_groups == [[0, 2]]
    ingestion._print_chunk_deduplication("example.md", len(chunks), len(retained), duplicate_groups)
    output = capsys.readouterr().out
    assert "original_chunks=3" in output and "unique_chunks=2" in output and "duplicates_removed=1" in output
    assert "first" not in output and "second" not in output


def test_ingestion_embeds_and_upserts_only_unique_chunks():
    client = _IngestionClient()
    embedded_inputs = []

    def embedder(texts, _settings):
        embedded_inputs.append(texts)
        return [[float(index)] for index, _text in enumerate(texts)]

    status, count = ingestion.ingest_document(client, _ingestion_document("first", "second", "first"), _settings(), embedder=embedder)

    assert (status, count) == ("created", 2)
    assert embedded_inputs == [["first", "second"]]
    assert [row["chunk_index"] for row in client.chunk_payload] == [0, 1]
    assert len({(row["knowledge_document_id"], row["content_hash"]) for row in client.chunk_payload}) == 2


def test_unchanged_document_skips_embedding_and_chunk_upsert():
    document = _ingestion_document("unique")
    version = f"{document.checksum}:raipur_unified_v1"
    client = _IngestionClient([{"id": "document-id", "document_version": version, "is_active": True}])

    status, count = ingestion.ingest_document(
        client,
        document,
        _settings(),
        embedder=lambda *_args: (_ for _ in ()).throw(AssertionError("embedding")),
    )

    assert (status, count) == ("unchanged", 0)
    assert client.chunk_payload == []
