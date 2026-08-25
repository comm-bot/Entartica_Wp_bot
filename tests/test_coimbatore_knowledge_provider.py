from types import SimpleNamespace

import pytest

from app.rag import coimbatore_knowledge_provider as module
from app.rag.coimbatore_knowledge_provider import CoimbatoreKnowledgeProvider, compose_approved_answer


def provider(monkeypatch, headings):
    monkeypatch.setattr(module, "embed_query", lambda *_a, **_k: [1.0, 0.0])
    monkeypatch.setattr(module, "retrieve_candidates_for_location", lambda *_a, **_k: [
        {"confidence": 0.99 - index / 100, "metadata": {"location_code":"coimbatore", "section_heading":heading}, "content":"approved"}
        for index, heading in enumerate(headings)
    ])
    return CoimbatoreKnowledgeProvider(object(), SimpleNamespace())


@pytest.mark.parametrize("guests", [2, 5, 8, 11])
def test_guest_count_alone_does_not_resurrect_superseded_package_prices(monkeypatch, guests):
    result = provider(monkeypatch, ["Pontoon Package Data — Pending Business Input", "Pontoon Celebration — Approved Package Master"]).answer("how much", guest_count=guests)
    assert "₹3,999" in result.text and "₹5,999" in result.text and "₹4,999" not in result.text
    assert result.package_id is None
    assert all(old not in result.text for old in ("₹6,000", "₹7,500", "₹9,000"))
    assert "Pending" not in result.source_heading


def test_more_than_twelve_requires_handoff(monkeypatch):
    result = provider(monkeypatch, ["Guest & Capacity Rules"]).answer("price", guest_count=13)
    assert result.handoff_required


@pytest.mark.parametrize("question,expected", [
    ("is cake included?", "500 g"), ("how long is it?", "30 minutes"),
    ("can pregnant woman come?", "not allowed"), ("can I bring my own cake?", "may bring"),
    ("is food included?", "not included"), ("singer price", "₹8,000"),
    ("photoshoot price", "₹10,000"), ("drone price", "₹5,000"),
    ("do you have parking?", "parking is available"), ("washroom hai?", "washrooms are available"),
])
def test_approved_topic_answers(monkeypatch, question, expected):
    result = provider(monkeypatch, ["Pontoon Operational Rules V2", "Customer Question Bank — 100 Questions for Sales Team"]).answer(question, guest_count=8, package_id="family_friends")
    assert expected.casefold() in result.text.casefold()
    assert "Question Bank" not in result.source_heading


def test_location_authority_outranks_nearby_places(monkeypatch):
    result = provider(monkeypatch, ["2. Nearby Famous Locations", "Official Location"]).answer("where is Entartica Coimbatore?")
    assert "Periyakulam Lake Boat House" in result.text
    assert result.source_heading == "Official Location"


def test_live_boundaries_and_conflicting_hours(monkeypatch):
    p = provider(monkeypatch, ["Pontoon Operational Rules V2"])
    availability = p.answer("is tomorrow 7pm available?")
    assert availability.requires_live_data and "must be checked" in availability.text
    assert "available." not in availability.text.casefold()
    payment = p.answer("I paid, what is payment status?")
    assert payment.requires_live_data and "can’t verify" in payment.text
    hours = p.answer("what are park operating hours?")
    assert "different closing times" in hours.text


def test_couple_context_changes_cake_and_duration():
    assert "250 g" in compose_approved_answer("cake", guest_count=2, package_id="couple_romance").text
    assert "20 minutes" in compose_approved_answer("duration", guest_count=2, package_id="couple_romance").text


def test_active_standard_package_authority_outranks_higher_similarity_history(monkeypatch):
    p = provider(monkeypatch, ["How much is the couple package?", "Standard Package Commercial Terms"])
    evidence = p.retrieve_evidence("how much is this package?", topic="price", package_id="coimbatore_pontoon_standard")
    assert evidence.chunks[0]["section_heading"] == "Standard Package Commercial Terms"
