"""Approved-evidence celebration recommendation policy tests."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.booking_enquiries import BookingDetails
from app.services.raipur.customer_understanding import CustomerUnderstandingService
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
from app.services.raipur.sales_state import SalesStage
from app.services.raipur.service_recommendation import (
    CelebrationRecommendationPolicy,
    RecommendationDecision,
    RecommendationEvidence,
)
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, knowledge_service_code
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


def _candidates():
    return [{"name": item.name, "is_active": True} for item in APPROVED_RAIPUR_SERVICES if item.category == "floating_celebration"]


class _Evidence:
    def __init__(self):
        self.rows = {
            "floating_gazebo": [
                ("Experience Overview", "A private celebration setting designed for intimate occasions."),
                ("Best For", "Romantic anniversaries, birthdays, and intimate private celebrations."),
                ("Capacity", "Published configuration for 2 guests; this is not a confirmed maximum capacity."),
                ("Celebration Inclusions", "Ambient music is included for Floating Gazebo."),
            ],
            "pontoon_celebration": [
                ("Experience Overview", "A peaceful option for intimate special occasions."),
                ("Best For", "Anniversary celebrations, romantic dates, and small private celebrations."),
            ],
            "party_boat_celebration": [
                ("Experience Overview", "An energetic group celebration for birthdays and corporate gatherings."),
                ("Best For", "Birthday celebrations, corporate gatherings, team celebrations, and private parties."),
                ("Experience Highlights", "Music creates a lively party atmosphere."),
                ("Celebration Inclusions", "Music is available on board."),
            ],
            "jetty_gazebo": [
                ("Experience Overview", "An elegant relaxed setting for intimate occasions and larger events."),
                ("Best For", "Anniversary celebrations, corporate gatherings, private dinners, and groups."),
            ],
            "houseboat_celebration": [
                ("Best For", "Birthdays, cozy group gatherings, and intimate wedding-related ceremonies."),
            ],
        }

    def recommendation_evidence(self, code):
        return [
            {"service_code": code, "section": section, "text": text, "source_document_id": f"doc-{code}"}
            for section, text in self.rows.get(code, [])
        ]


def test_private_anniversary_recommendations_are_supported_and_traceable():
    decision = CelebrationRecommendationPolicy(_Evidence()).recommend(
        candidates=_candidates(), occasion="anniversary", preference="private_intimate", guest_count=2,
    )
    assert not decision.insufficient_evidence
    assert decision.recommended_service_codes
    assert "party_boat_celebration" not in decision.recommended_service_codes
    assert all(item.service_code in decision.recommended_service_codes for item in decision.evidence)
    assert all(item.section in {"Experience Overview", "Best For"} for item in decision.evidence)


def test_lively_birthday_uses_only_party_specific_evidence():
    decision = CelebrationRecommendationPolicy(_Evidence()).recommend(
        candidates=_candidates(), occasion="birthday", preference="lively_party", guest_count=12,
    )
    assert decision.recommended_service_codes == ("party_boat_celebration",)
    assert all(item.service_code == "party_boat_celebration" for item in decision.evidence)
    joined = " ".join(item.text for item in decision.evidence).casefold()
    assert "lively party atmosphere" in joined and "music" in joined
    assert "Floating Gazebo" not in joined


def test_corporate_group_uses_explicit_corporate_evidence_only():
    decision = CelebrationRecommendationPolicy(_Evidence()).recommend(
        candidates=_candidates(), occasion="corporate event", preference=None, guest_count=20,
    )
    assert set(decision.recommended_service_codes) == {"party_boat_celebration", "jetty_gazebo"}
    assert all("corporate" in item.text.casefold() or "team" in item.text.casefold() for item in decision.evidence)


def test_insufficient_state_returns_no_guessed_recommendation():
    decision = CelebrationRecommendationPolicy(_Evidence()).recommend(
        candidates=_candidates(), occasion="special event", preference=None, guest_count=12,
    )
    assert decision.insufficient_evidence
    assert decision.recommended_service_codes == () and decision.evidence == ()


def test_published_configuration_is_not_treated_as_a_maximum_capacity():
    small = CelebrationRecommendationPolicy(_Evidence()).recommend(
        candidates=_candidates(), occasion="anniversary", preference="private_intimate", guest_count=2,
    )
    larger = CelebrationRecommendationPolicy(_Evidence()).recommend(
        candidates=_candidates(), occasion="anniversary", preference="private_intimate", guest_count=12,
    )
    assert small.recommended_service_codes == larger.recommended_service_codes


def test_cross_service_rows_and_disallowed_sections_are_rejected():
    class Contaminated(_Evidence):
        def recommendation_evidence(self, code):
            rows = super().recommendation_evidence(code)
            if code == "party_boat_celebration":
                rows += [
                    {"service_code": "floating_gazebo", "section": "Celebration Inclusions", "text": "Floating Gazebo food and cake.", "source_document_id": "floating"},
                    {"service_code": code, "section": "Pricing", "text": "Unsupported price evidence.", "source_document_id": "party"},
                ]
            return rows

    decision = CelebrationRecommendationPolicy(Contaminated()).recommend(
        candidates=_candidates(), occasion="birthday", preference="lively_party", guest_count=12,
    )
    assert all("Floating Gazebo food" not in item.text and item.section != "Pricing" for item in decision.evidence)


class _Services:
    def list_active_for_location(self, _location_id): return [{"name": item.name, "is_active": True} for item in APPROVED_RAIPUR_SERVICES]


class _Knowledge:
    def answer_service_details(self, _question, service_name, service_code, **kwargs):
        return KnowledgeDraft(f"{service_name} lasts 2 hours.", f"{service_code}.md", .9, False, "Duration", 1, service_code, ("Duration",))


class _Policy:
    def __init__(self): self.calls = 0
    def recommend(self, **_kwargs):
        self.calls += 1
        return RecommendationDecision(
            ("floating_gazebo",), "strong",
            (RecommendationEvidence("floating_gazebo", "Best For", "Approved for intimate anniversary celebrations.", "floating-doc"),),
            "approved_service_specific_evidence_match", False,
        )


def _state(message):
    return {"message_id":"m","conversation_id":"c","customer_id":"u","customer_message":message,"normalized_message":message.casefold(),"language":"en","location_code":"raipur","previous_service_code":None,"previous_topic":None,"intent":None,"entity_type":"unknown","service_code":None,"topic":None,"use_previous_service":False,"requires_handover":False,"handover_reason":None,"selected_route":None,"answer_source":None,"validation_errors":[],"plan_consistency_repaired":False,"invocation_id":"i","draft_response":None,"validation_status":"pending","error":None,"route":None}


def _turn(workflow, message, context=None):
    return workflow.invoke(_state(message),message=SimpleNamespace(content=message),customer={"id":"u"},conversation={"id":"c","location_id":"raipur"},source_message_id="m",current_state=context)


def _qualified_context():
    return ConversationContext(
        BookingDetails(None,None,__import__('datetime').date(2026,8,13),None,None,None,12),
        pending_field="celebration_preference",active_topic="celebration_catalogue",active_entity_type="catalogue",active_entity_name="celebration",pending_action="celebration_sales",pending_slots={"occasion":"birthday"},sales_stage=SalesStage.QUALIFYING,
    )


def test_multiturn_reaches_recommendation_without_reasking_known_fields():
    policy = _Policy()
    extractor = CustomerUnderstandingService(lambda *_: {"intent":"celebration","preference":"private_intimate","confidence":.98})
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(),services=_Services(),customer_understanding=extractor,recommendation_policy=policy)
    result = _turn(workflow,"private and intimate",_qualified_context())
    assert policy.calls == 1
    assert "Floating Gazebo" in result.draft_text and "intimate anniversary" in result.draft_text
    assert result.context.pending_field is None
    assert "how many guests" not in result.draft_text.casefold() and "what date" not in result.draft_text.casefold()


def test_restricted_and_explicit_service_routes_never_call_recommendation():
    policy = _Policy()
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(),services=_Services(),recommendation_policy=policy)
    context = _qualified_context()
    pricing = _turn(workflow,"What is the price?",context)
    availability = _turn(workflow,"Is it available 15 August?",context)
    selected = _turn(workflow,"I want Floating Gazebo",context)
    assert pricing.detected_intent == "pricing" and pricing.human_handover_required
    assert availability.detected_intent == "availability" and availability.human_handover_required
    assert selected.context.last_service_code == "floating_gazebo"
    assert policy.calls == 0
