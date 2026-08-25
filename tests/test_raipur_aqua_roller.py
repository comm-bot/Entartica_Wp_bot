"""Aqua Roller canonical registration, facts, and service-isolation coverage."""

from pathlib import Path

from app.rag.raipur_ingestion import build_plan
from app.rag.raipur_knowledge_provider import _matches_exact_topic_heading
from app.services.raipur.h2o_handler import is_h2o_service_code
from app.services.raipur.service_resolver import resolve_service
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, knowledge_service_code


ROOT = Path(__file__).resolve().parents[1]


def _document(code: str):
    plan, errors = build_plan(ROOT)
    assert not errors
    return next(row.document for row in plan if row.document and row.document.metadata.get("service_code") == code)


def test_aqua_roller_is_one_canonical_service_with_approved_aliases() -> None:
    matches = [service for service in APPROVED_RAIPUR_SERVICES if knowledge_service_code(service) == "aqua_roller"]
    assert [(service.name, service.slug) for service in matches] == [("Aqua Roller", "aqua-roller")]
    for phrase in ("aqua roller", "aqua roler", "aqua rollar", "water roller"):
        result = resolve_service(f"Tell me about {phrase}")
        assert (result.service_code, result.service_name) == ("aqua_roller", "Aqua Roller")


def test_aqua_roller_document_preserves_approved_h2o_facts() -> None:
    document = _document("aqua_roller")
    assert document is not None
    assert document.metadata["service_name"] == "Aqua Roller"
    assert is_h2o_service_code("aqua_roller")
    assert "4–5 persons" in document.text
    assert "10–12 years" in document.text
    assert "10:00 AM to 6:30 PM" in document.text
    assert "individual Aqua Roller turn/session duration is not separately confirmed" in document.text
    assert _matches_exact_topic_heading("eligibility", "Age Requirement")


def test_zorbing_capacity_and_aqua_cycle_isolation() -> None:
    zorbing = _document("zorbing_ball")
    aqua_cycle = _document("aqua_cycle")
    assert zorbing is not None and "Approved participant capacity: **1 person**" in zorbing.text
    assert aqua_cycle is not None
    assert "4–5 persons" not in aqua_cycle.text
    assert "10–12 years" not in aqua_cycle.text
