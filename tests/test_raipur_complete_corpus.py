"""Offline coverage for the complete canonical Raipur corpus."""
from pathlib import Path

from app.rag.raipur_ingestion import build_plan
from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, knowledge_service_code


ROOT = Path(__file__).resolve().parents[1]


def _candidate(code: str, content: str, score: float):
    return {"content": content, "source_filename": f"{code}.md", "confidence": score, "metadata": {"location_code":"raipur", "service_code":code, "customer_facing":True, "catalogue_status":"active", "approval_status":"approved", "is_active":True, "active":True, "retrieval_priority":"service_specific"}}


def test_every_active_application_service_has_one_canonical_manifest_document():
    plan, errors = build_plan(ROOT)
    documents = [row.document for row in plan if row.document]
    codes = [document.metadata.get("service_code") for document in documents if document.metadata.get("knowledge_type") in {"service", "celebration"}]
    expected = [knowledge_service_code(service) for service in APPROVED_RAIPUR_SERVICES]
    assert not errors
    assert sorted(codes) == sorted(expected)
    assert len(codes) == len(set(codes)) == len(expected)
    assert all(
        document.metadata.get("retrieval_priority") == "service_specific"
        for document in documents
        if document.metadata.get("knowledge_type") in {"service", "celebration"}
    )
    general = next(document for document in documents if document.metadata.get("service_code") == "raipur_general")
    assert general.metadata.get("knowledge_type") == "general"
    assert general.metadata.get("retrieval_priority") == "high"


def test_exact_service_filter_runs_before_similarity_and_prevents_cross_service_leakage():
    rows = [_candidate("pontoon_celebration", "Pontoon Celebration", .99), _candidate("pontoon_boat_ride", "Pontoon Boat Ride", .70)]
    provider = RaipurKnowledgeProvider(object(), type("Settings", (), {"raipur_knowledge_min_confidence": .65})(), embed_query_fn=lambda *_:[1], retrieve_candidates_fn=lambda *_args, **_kwargs: rows, answer_generator=lambda row, low_confidence: type("Answer", (), {"answer":row["content"]})())
    result = provider.answer_service_details("What is Pontoon Boat?", "Pontoon Boat")
    assert result.text == "Pontoon Boat Ride"
    assert "Celebration" not in result.text


def test_location_document_has_only_the_approved_address_and_map():
    plan, errors = build_plan(ROOT)
    document = next(row.document for row in plan if row.document and row.document.metadata.get("knowledge_type") == "location")
    assert not errors
    assert "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh" in document.text
    assert "https://maps.app.goo.gl/VtxPyANfMC3rztex8" in document.text
    assert "Mayfair Lake Resort" not in document.text


def test_offline_retrieval_smoke_covers_every_active_service_without_cross_service_leakage():
    settings = type("Settings", (), {"raipur_knowledge_min_confidence": .65})()
    for service in APPROVED_RAIPUR_SERVICES:
        code = knowledge_service_code(service)
        rows = [_candidate("unrelated_service", "Unrelated content", .99), _candidate(code, f"{service.name} definition", .70)]
        provider = RaipurKnowledgeProvider(object(), settings, embed_query_fn=lambda *_:[1], retrieve_candidates_fn=lambda *_args, **_kwargs: rows, answer_generator=lambda row, low_confidence: type("Answer", (), {"answer":row["content"]})())
        result = provider.answer_service_details(f"Tell me about {service.name}", service.name)
        assert result.text == f"{service.name} definition"
