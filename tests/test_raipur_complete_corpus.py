"""Offline coverage for the complete canonical Raipur corpus."""
from pathlib import Path

from app.rag.raipur_ingestion import build_plan
from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.rag.customer_ready_knowledge import build_customer_ready_service_answer, contains_governance_language, is_customer_ready_section
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
    assert result.text and "Pontoon Boat Ride" in result.text
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
        if service.category == "floating_celebration":
            rows[1]["metadata"]["section_heading"] = "Experience Overview"
        provider = RaipurKnowledgeProvider(object(), settings, embed_query_fn=lambda *_:[1], retrieve_candidates_fn=lambda *_args, **_kwargs: rows, answer_generator=lambda row, low_confidence: type("Answer", (), {"answer":row["content"]})())
        result = provider.answer_service_details(f"Tell me about {service.name}", service.name)
        assert result.text and service.name in result.text
        assert "Unrelated content" not in result.text


def test_every_active_service_projects_customer_ready_answers_across_supported_topics():
    plan, errors = build_plan(ROOT)
    assert not errors
    documents = [row.document for row in plan if row.document and row.document.metadata.get("knowledge_type") in {"service", "celebration"}]
    assert len(documents) == len(APPROVED_RAIPUR_SERVICES)
    evaluated = 0
    for document in documents:
        code = document.metadata["service_code"]
        name = document.metadata["service_name"]
        sections = [(section.heading, section.text) for section in document.sections]
        for mode in ("overview", "more_details", "duration", "operating_hours", "inclusions", "suitable_for", "key_characteristics"):
            selected = [(heading, text) for heading, text in sections if is_customer_ready_section(code, heading, mode)]
            if not selected:
                continue
            ready = build_customer_ready_service_answer(selected, service_name=name, service_code=code, detail_mode=mode)
            if ready.text:
                evaluated += 1
                assert not contains_governance_language(ready.text)
                assert len(ready.text) <= 900
                assert "facts to verify" not in ready.text.casefold()
                assert "production value" not in ready.text.casefold()
    assert evaluated >= len(documents) * 4
