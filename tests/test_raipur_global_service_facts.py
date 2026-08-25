"""Generic contextual service-fact regressions across canonical Raipur services."""

from pathlib import Path

import pytest

from app.rag.customer_ready_knowledge import build_customer_ready_service_answer
from app.rag.raipur_ingestion import build_plan
from app.services.raipur_langgraph import RaipurLangGraphWorkflow
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, knowledge_service_code


ROOT = Path(__file__).resolve().parents[1]


def _sections(code: str) -> list[tuple[str, str]]:
    plan, errors = build_plan(ROOT)
    assert not errors
    document = next(row.document for row in plan if row.document and row.document.metadata.get("service_code") == code)
    return [(section.heading, section.text) for section in document.sections]


@pytest.mark.parametrize(
    ("code", "name", "topic", "expected"),
    [
        ("daycation_package", "Daycation Package", "duration", ("4 hours", "2:00 PM", "6:00 PM")),
        ("daycation_package", "Daycation Package", "operating_hours", ("2:00 PM", "6:00 PM")),
        ("staycation_combo", "Staycation Combo", "duration", ("2:00 PM", "12:00 PM", "next day")),
        ("staycation_combo", "Staycation Combo", "operating_hours", ("2:00 PM", "12:00 PM", "next day")),
        ("staycation_combo", "Staycation Combo", "inclusions", ("club room", "breakfast")),
        ("daycation_package", "Daycation Package", "inclusions", ("club room", "h2o play park")),
        ("party_boat_celebration", "Party Boat Celebration", "duration", ("2 hours",)),
        ("houseboat_celebration", "Houseboat Celebration", "duration", ("30 minutes",)),
        ("jetty_gazebo", "Jetty Gazebo", "duration", ("2 hours",)),
        ("floating_gazebo", "Floating Gazebo", "duration", ("2 hours",)),
        ("pontoon_celebration", "Pontoon Celebration", "duration", ("30 minutes",)),
        ("zorbing_ball", "Zorbing Ball", "capacity", ("1 person",)),
        ("aqua_roller", "Aqua Roller", "capacity", ("4–5 persons",)),
        ("aqua_roller", "Aqua Roller", "eligibility", ("10–12 years",)),
        ("aqua_roller", "Aqua Roller", "operating_hours", ("10:00 AM", "6:30 PM")),
        ("jet_ski_ride", "Jet Ski Ride", "duration", ("5 to 10 minutes",)),
    ],
)
def test_customer_ready_projection_returns_approved_service_fact(code, name, topic, expected):
    answer = build_customer_ready_service_answer(_sections(code), service_name=name, service_code=code, detail_mode=topic)
    assert answer.text is not None
    assert all(value.casefold() in answer.text.casefold() for value in expected)


@pytest.mark.parametrize("followup", ["duration", "timings", "capacity", "age", "included", "how does it work", "safety", "swimming required", "suitable for", "tell me more", "highlights"])
def test_short_topic_followup_preserves_selected_service(followup):
    workflow = RaipurLangGraphWorkflow()
    plan = workflow._deterministic_plan(followup.casefold(), "staycation_combo", "overview")
    assert plan is not None
    assert plan.service_code == "staycation_combo"
    assert plan.use_previous_service is True


def test_new_explicit_service_overrides_stored_service_and_highlights_are_deferred():
    workflow = RaipurLangGraphWorkflow()
    switched = workflow._deterministic_plan("aqua roller capacity", "staycation_combo", "overview")
    assert switched is not None and switched.service_code == "aqua_roller" and not switched.use_previous_service
    highlights = workflow._deterministic_plan("highlights", "aqua_roller", "overview")
    assert highlights is not None and highlights.topic == "highlights" and highlights.service_code == "aqua_roller"


def test_every_canonical_service_has_one_manifest_document_for_fact_audit():
    plan, errors = build_plan(ROOT)
    assert not errors
    codes = [row.document.metadata.get("service_code") for row in plan if row.document and row.document.metadata.get("knowledge_type") in {"service", "celebration"}]
    expected = [knowledge_service_code(service) for service in APPROVED_RAIPUR_SERVICES]
    assert sorted(codes) == sorted(expected)
