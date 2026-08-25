"""Offline production-path evaluation with fake structured understanding."""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

from app.evaluation.raipur_conversation_dataset import EvaluationOutcome, evaluation_summary
from app.services.booking_enquiries import BookingDetails
from app.services.raipur.customer_understanding import CustomerUnderstandingService
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
from app.services.raipur.sales_state import SalesStage
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


@dataclass(frozen=True)
class EndToEndScenario:
    scenario_id: str
    message: str
    expected_intent: str
    expected_route: str
    understanding: dict | None = None
    context: ConversationContext | None = None
    expected_guest_count: int | None = None
    expected_preference: str | None = None
    expected_recommendation: str | None = None
    expected_next_action: str | None = None
    expected_handover: bool = False
    expected_general_fallback: bool = False


def _active_sales_context() -> ConversationContext:
    return ConversationContext(
        BookingDetails(None, None, None, None, None, None, 12),
        pending_field="preferred_date", active_topic="celebration_catalogue",
        active_entity_type="catalogue", active_entity_name="celebration",
        pending_action="celebration_sales", pending_slots={"occasion": "birthday"},
        sales_stage=SalesStage.QUALIFYING,
    )


END_TO_END_SCENARIOS: tuple[EndToEndScenario, ...] = (
    EndToEndScenario("typo_celebration", "muje selebration krvana he", "celebration_service_list", "answer_catalogue", {"intent":"celebration","language":"hinglish","confidence":.98}, expected_next_action="ask_guest_count"),
    EndToEndScenario("kids_family", "kids ke saath aa raha hu, kya activities hain?", "family_activity_discovery", "answer_venue_knowledge", {"intent":"family_discovery","preference":"family","language":"hinglish","confidence":.98}),
    EndToEndScenario("kayaking_overview", "What is kayaking?", "service_overview", "answer_service_knowledge"),
    EndToEndScenario("venue_timings", "What are your timings?", "venue_duration_timing", "answer_venue_knowledge"),
    EndToEndScenario("party_timings", "Party Boat timings?", "service_topic", "answer_service_knowledge"),
    EndToEndScenario("location", "Where is Entartica Raipur?", "location", "answer_location"),
    EndToEndScenario("payment", "How can I make payment?", "payment", "handover_to_sales", expected_handover=True),
    EndToEndScenario("birthday_multifact", "birthday for 12 people on 13 August, something lively", "customer_understanding_update", "answer_venue_knowledge", {"intent":"celebration","occasion":"birthday","guest_count":12,"planned_date_text":"13 August","preference":"lively_party","language":"en","confidence":.99}, expected_guest_count=12, expected_preference="lively_party", expected_recommendation="party_boat_celebration", expected_next_action="recommend_service"),
    EndToEndScenario("anniversary_multifact", "anniversary for 8 guests on 15 August, private and relaxed", "customer_understanding_update", "answer_venue_knowledge", {"intent":"celebration","occasion":"anniversary","guest_count":8,"planned_date_text":"15 August","preference":"private_intimate","language":"en","confidence":.99}, expected_guest_count=8, expected_preference="private_intimate", expected_recommendation="floating_gazebo", expected_next_action="recommend_service"),
    EndToEndScenario("location_interrupt", "Where is Entartica Raipur?", "location", "answer_location", context=_active_sales_context()),
    EndToEndScenario("payment_interrupt", "how can I pay?", "payment", "handover_to_sales", context=_active_sales_context(), expected_handover=True),
    EndToEndScenario("allowed_general_interrupt", "What is a lake?", "general_question", "answer_general_openai", {"intent":"general","language":"en","confidence":.95}, context=_active_sales_context(), expected_general_fallback=True),
)


class _Knowledge:
    def answer(self, _question):
        return KnowledgeDraft("Approved Raipur venue information.", "general.md", .9, False, "Overview")

    def answer_service_details(self, _question, service_name, service_code, **kwargs):
        topic = kwargs.get("detail_mode", "overview")
        return KnowledgeDraft(f"Approved {service_name} {topic} information.", f"{service_code}.md", .9, False, topic, 1, service_code, (topic,))

    def recommendation_evidence(self, code):
        text = {
            "party_boat_celebration": "Lively birthday and corporate team celebration.",
            "floating_gazebo": "Private intimate anniversary and proposal celebration.",
            "pontoon_celebration": "Peaceful intimate anniversary celebration.",
            "jetty_gazebo": "Corporate anniversary celebration in a relaxed setting.",
            "houseboat_celebration": "Relaxed birthday celebration.",
        }.get(code)
        return [] if text is None else [{"service_code":code,"section":"Best For","text":text,"source_document_id":code}]


class _Services:
    def list_active_for_location(self, _location_id):
        return [{"name": item.name, "slug": item.slug, "is_active": True} for item in APPROVED_RAIPUR_SERVICES]


def _state(message):
    return {"message_id":"eval","conversation_id":"eval","customer_id":"eval","customer_message":message,"normalized_message":message.casefold(),"language":"en","location_code":"raipur","previous_service_code":None,"previous_topic":None,"intent":None,"entity_type":"unknown","service_code":None,"topic":None,"use_previous_service":False,"requires_handover":False,"handover_reason":None,"selected_route":None,"answer_source":None,"validation_errors":[],"plan_consistency_repaired":False,"invocation_id":"eval","draft_response":None,"validation_status":"pending","error":None,"route":None}


def run_end_to_end_evaluation() -> tuple[dict[str, int | float | None], list[str]]:
    outputs = {scenario.message.casefold(): scenario.understanding for scenario in END_TO_END_SCENARIOS if scenario.understanding is not None}
    understanding = CustomerUnderstandingService(lambda message, _context: outputs[message.casefold()])
    workflow = RaipurLangGraphWorkflow(
        knowledge=_Knowledge(), services=_Services(),
        location={"id":"raipur","name":"Entartica Sea World Raipur","address":"Sector 24","landmark":"Near MAYFAIR Resort","maps_url":"https://maps.example/raipur"},
        customer_understanding=understanding,
    )
    outcomes: list[EvaluationOutcome] = []
    failures: list[str] = []
    unexpected_fallbacks = 0
    for scenario in END_TO_END_SCENARIOS:
        result = workflow.invoke(
            _state(scenario.message), message=SimpleNamespace(content=scenario.message),
            customer={"id":"eval"}, conversation={"id":"eval","location_id":"raipur"},
            source_message_id=scenario.scenario_id, current_state=scenario.context,
        )
        metadata = result.safe_metadata or {}
        telemetry = metadata.get("conversation_telemetry", {})
        intent_ok = result.detected_intent == scenario.expected_intent and metadata.get("selected_route") == scenario.expected_route
        slots = result.context.pending_slots or {}
        state_ok = (
            (scenario.expected_guest_count is None or result.context.details.total_guests == scenario.expected_guest_count)
            and (scenario.expected_preference is None or slots.get("celebration_preference") == scenario.expected_preference)
        )
        next_ok = scenario.expected_next_action is None or metadata.get("sales_next_action") == scenario.expected_next_action or result.context.pending_field == "total_guests"
        restricted_ok = result.human_handover_required == scenario.expected_handover if scenario.expected_handover else None
        recommendation_ok = scenario.expected_recommendation is None or scenario.expected_recommendation in metadata.get("recommended_service_codes", [])
        context_ok = None
        if scenario.context is not None:
            context_ok = result.context.details.total_guests == scenario.context.details.total_guests and result.context.pending_action == scenario.context.pending_action
        generic = bool(telemetry.get("generic_fallback_used"))
        if generic and not scenario.expected_general_fallback:
            unexpected_fallbacks += 1
        outcome = EvaluationOutcome(intent_ok, state_ok, next_ok, restricted_ok, recommendation_ok, context_ok, generic)
        if any(value is False for value in (intent_ok, state_ok, next_ok, restricted_ok, recommendation_ok, context_ok)) or generic != scenario.expected_general_fallback:
            failures.append(scenario.scenario_id)
        outcomes.append(outcome)
    summary = evaluation_summary(outcomes)
    summary["unexpected_entartica_fallback_rate"] = round(100 * unexpected_fallbacks / len(outcomes), 2)
    summary["expected_general_fallback_rate"] = round(100 * sum(s.expected_general_fallback for s in END_TO_END_SCENARIOS) / len(outcomes), 2)
    return summary, failures
