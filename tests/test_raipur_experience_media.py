"""Approved Raipur experience-media placement and isolation checks."""

from pathlib import Path

from app.rag.raipur_ingestion import build_plan


ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "documents" / "raipur" / "active"
WATER_INSTAGRAM = "https://www.instagram.com/reel/DbLHbqUIFLA/?igsh=MW85eGRraHY1b2d0Mg==&igsi=MW85eGRraHY1b2d0Mg=="
WATER_YOUTUBE = "https://youtube.com/shorts/B8zgeznoPf8?si=Igub9aZ67w-6K-9o"
RAIPUR_INSTAGRAM = "https://www.instagram.com/reel/DaXsQJUqTQD/?igsh=b295ZnV2dHJ0aWJ0&igsi=b295ZnV2dHJ0aWJ0"
CELEBRATION_INSTAGRAM = "https://www.instagram.com/reel/DYw4n-ToPBy/?igsh=MTFscmMwaWZ2eDUwYQ==&igsi=MTFscmMwaWZ2eDUwYQ=="
PONTOON_YOUTUBE = "https://youtu.be/V--yiHZ7oiM?si=CYFyzoJsIpZDZdHS"
STAYCATION_INSTAGRAM = "https://www.instagram.com/reel/DYzUySLIoSV/?igsh=em5nZ2hvbjgxYmlz&igsi=em5nZ2hvbjgxYmlz"
HELD_DAYCATION = "https://youtube.com/shorts/4pDAMd6yCfk?si=gZw8Z8E3AxW54JCu"


def _active_texts() -> dict[str, str]:
    return {path.relative_to(ACTIVE).as_posix(): path.read_text(encoding="utf-8") for path in ACTIVE.rglob("*.md")}


def test_media_urls_are_exact_unique_and_in_the_approved_documents() -> None:
    texts = _active_texts()
    expected = {
        WATER_INSTAGRAM: "general/raipur_general_information.md",
        WATER_YOUTUBE: "general/raipur_general_information.md",
        RAIPUR_INSTAGRAM: "general/raipur_general_information.md",
        CELEBRATION_INSTAGRAM: "faq/raipur_celebration_faq.md",
        PONTOON_YOUTUBE: "services/pontoon_celebration.md",
        STAYCATION_INSTAGRAM: "services/staycation_combo.md",
    }
    for url, source in expected.items():
        matches = [path for path, text in texts.items() if url in text]
        assert matches == [source]
        assert texts[source].count(url) == 1
        assert "## Experience Media" in texts[source]
    assert not any(HELD_DAYCATION in text for text in texts.values())


def test_media_sections_do_not_change_canonical_service_identity_or_corpus_validity() -> None:
    plan, errors = build_plan(ROOT)
    assert not errors and len(plan) == 23
    assert all(row.document is not None for row in plan)
    codes = [row.document.metadata.get("service_code") for row in plan if row.document and row.document.metadata.get("knowledge_type") in {"service", "celebration"}]
    assert len(codes) == len(set(codes)) == 19


def test_service_specific_media_is_isolated_from_other_services() -> None:
    texts = _active_texts()
    assert PONTOON_YOUTUBE not in texts["services/party_boat_celebration.md"]
    assert PONTOON_YOUTUBE not in texts["services/houseboat_celebration.md"]
    assert STAYCATION_INSTAGRAM not in texts["services/daycation_package.md"]
