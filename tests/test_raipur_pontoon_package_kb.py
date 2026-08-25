from pathlib import Path
from types import SimpleNamespace

from app.rag.raipur_ingestion import build_plan
from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.services.raipur.pontoon_package import PONTOON_PACKAGE_SOURCE_FILE, render_pontoon_package


ROOT = Path(__file__).resolve().parents[1]


def _canonical_package():
    plan, errors = build_plan(ROOT)
    assert not errors
    document = next(row.document for row in plan if row.document and row.document.source_file == PONTOON_PACKAGE_SOURCE_FILE)
    package = render_pontoon_package(
        {section.heading: section.text for section in document.sections}, source_file=document.source_file,
    )
    assert package is not None
    return document, package


def test_canonical_pontoon_kb_contains_complete_approved_package_and_media():
    document, package = _canonical_package()
    assert document.source_file == "active/services/pontoon_celebration.md"
    for expected in (
        "Red Carpet Welcome", "02 Cold pyro entry", "Rack Rate: ₹9,500",
        "Offer/Discounted Rate: ₹7,499", "₹1,000 token payment",
        "Full refund if cancelled before 24 hours of the event date.",
    ):
        assert expected in package.content
    assert package.image_url.startswith("https://apsjacfeiaiwcklnjmaj.supabase.co/storage/v1/object/sign/")


def test_provider_reconstructs_package_only_from_exact_active_pontoon_chunks():
    document, expected = _canonical_package()
    rows = [
        {
            "knowledge_document_id": "pontoon-doc",
            "content": section.text,
            "metadata": {"section_heading": section.heading},
        }
        for section in document.sections
    ]
    provider = object.__new__(RaipurKnowledgeProvider)
    provider._service_snapshot = lambda code: (({
        "id": "pontoon-doc", "source_file": PONTOON_PACKAGE_SOURCE_FILE,
        "metadata": {"approval_status": "approved", "customer_facing": True},
    },), tuple(rows))
    actual = provider.approved_pontoon_package()
    assert actual == expected

    provider._service_snapshot = lambda code: (({
        "id": "wrong-doc", "source_file": "active/services/party_boat_celebration.md",
        "metadata": {"approval_status": "approved", "customer_facing": True},
    },), tuple(rows))
    assert provider.approved_pontoon_package() is None
