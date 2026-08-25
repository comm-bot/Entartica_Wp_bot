"""Celebration capacity governance and safe recommendation integration."""
from app.services.raipur.capacity_governance import (
    CapacityStatus,
    assess_capacity,
    celebration_capacity_record,
)
from app.services.raipur.service_recommendation import CelebrationRecommendationPolicy


class _Evidence:
    rows = {
        "houseboat_celebration": "Birthdays and relaxed cozy group gatherings.",
        "party_boat_celebration": "Lively birthday parties and corporate team celebrations.",
        "floating_gazebo": "Private intimate anniversary celebrations and proposals.",
        "jetty_gazebo": "Relaxed corporate gatherings and anniversary celebrations.",
        "pontoon_celebration": "Peaceful intimate birthday and anniversary celebrations.",
    }

    def recommendation_evidence(self, code):
        text = self.rows.get(code)
        return [] if text is None else [{
            "service_code": code,
            "section": "Best For",
            "text": text,
            "source_document_id": f"doc-{code}",
        }]


def _candidate(name):
    return [{"name": name, "is_active": True}]


def test_houseboat_verified_maximum_supports_compatible_and_exceeded_results():
    record = celebration_capacity_record("houseboat_celebration")
    assert record is not None
    assert record.maximum_capacity == 15 and record.capacity_status is CapacityStatus.VERIFIED
    assert assess_capacity("houseboat_celebration", 12).compatible is True
    assert assess_capacity("houseboat_celebration", 16).compatible is False


def test_unresolved_services_never_produce_capacity_conclusions():
    expected = {
        "party_boat_celebration": CapacityStatus.CONFLICT,
        "jetty_gazebo": CapacityStatus.CONFLICT,
        "pontoon_celebration": CapacityStatus.CONFLICT,
        "floating_gazebo": CapacityStatus.UNKNOWN,
    }
    for code, status in expected.items():
        record = celebration_capacity_record(code)
        assert record is not None and record.capacity_status is status
        assert record.maximum_capacity is None
        assert assess_capacity(code, 12).compatible is None


def test_published_configurations_are_not_structural_maxima():
    floating = celebration_capacity_record("floating_gazebo")
    pontoon = celebration_capacity_record("pontoon_celebration")
    assert floating.published_configuration_guests == 2 and floating.maximum_capacity is None
    assert pontoon.published_configuration_guests == 6 and pontoon.maximum_capacity is None
    assert assess_capacity("floating_gazebo", 2).compatible is None
    assert assess_capacity("pontoon_celebration", 6).compatible is None


def test_verified_maximum_filters_only_incompatible_houseboat():
    policy = CelebrationRecommendationPolicy(_Evidence())
    compatible = policy.recommend(
        candidates=_candidate("Houseboat Celebration"), occasion="birthday",
        preference="relaxed", guest_count=12,
    )
    exceeded = policy.recommend(
        candidates=_candidate("Houseboat Celebration"), occasion="birthday",
        preference="relaxed", guest_count=16,
    )
    assert compatible.recommended_service_codes == ("houseboat_celebration",)
    assert compatible.capacity_compatibility[0].compatible is True
    assert exceeded.insufficient_evidence and not exceeded.recommended_service_codes


def test_unknown_capacity_does_not_block_preference_or_occasion_ranking():
    decision = CelebrationRecommendationPolicy(_Evidence()).recommend(
        candidates=_candidate("Party Boat Celebration"), occasion="birthday",
        preference="lively_party", guest_count=12,
    )
    assert decision.recommended_service_codes == ("party_boat_celebration",)
    assert decision.capacity_compatibility[0].compatible is None
    assert decision.evidence


def test_internal_capacity_status_words_are_not_customer_evidence():
    decision = CelebrationRecommendationPolicy(_Evidence()).recommend(
        candidates=_candidate("Jetty Gazebo"), occasion="corporate event",
        preference="relaxed", guest_count=10,
    )
    customer_evidence = " ".join(item.text for item in decision.evidence).casefold()
    assert "conflict" not in customer_evidence
    assert "unknown" not in customer_evidence
    assert "capacity_status" not in customer_evidence
