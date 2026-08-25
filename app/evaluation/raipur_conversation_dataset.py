"""Deterministic product-regression scenarios for realistic Raipur chats."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationTurn:
    message: str
    expected_intent: str
    expected_route: str
    expected_service_code: str | None = None
    expected_topic: str | None = None
    expected_handover: bool = False


@dataclass(frozen=True)
class ConversationScenario:
    scenario_id: str
    category: str
    language: str
    turns: tuple[EvaluationTurn, ...]


def _one(identifier, category, language, message, intent, route, service=None, topic=None, handover=False):
    return ConversationScenario(identifier, category, language, (EvaluationTurn(message, intent, route, service, topic, handover),))


SCENARIOS: tuple[ConversationScenario, ...] = (
    _one("celebrate_hi", "celebration", "hinglish", "mujhe celebration karvana hai", "celebration_service_list", "answer_catalogue"),
    _one("celebrate_en", "celebration", "en", "I want to celebrate something", "celebration_service_list", "answer_catalogue"),
    _one("birthday_party", "celebration", "en", "birthday party karni hai", "celebration_service_list", "answer_catalogue"),
    _one("anniversary", "celebration", "hinglish", "anniversary celebration karni hai", "celebration_service_list", "answer_catalogue"),
    _one("corporate", "celebration", "hinglish", "corporate event karna hai", "celebration_service_list", "answer_catalogue"),
    _one("proposal", "celebration", "en", "I want to plan a marriage proposal celebration", "celebration_service_list", "answer_catalogue"),
    _one("special_event", "celebration", "en", "one special event", "celebration_service_list", "answer_catalogue"),
    _one("hindi_birthday", "celebration", "hi", "जन्मदिन सेलिब्रेट करना है", "celebration_service_list", "answer_catalogue"),
    _one("hindi_anniversary", "celebration", "hi", "सालगिरह मनानी है", "celebration_service_list", "answer_catalogue"),
    _one("celebration_typo", "celebration", "hinglish", "muje selebration krvana he", "celebration_service_list", "answer_catalogue"),
    _one("family_options", "family", "en", "What activities are good for my family?", "family_activity_discovery", "answer_venue_knowledge"),
    _one("family_hinglish", "family", "hinglish", "family ke liye kya activities hain?", "family_activity_discovery", "answer_venue_knowledge"),
    _one("kids_options", "family", "en", "What can children and parents do together?", "family_activity_discovery", "answer_venue_knowledge"),
    _one("water_fun_family", "family", "en", "We want water fun as a family", "family_activity_discovery", "answer_venue_knowledge"),
    _one("jet_ski", "explicit_service", "en", "Tell me about Jet Ski", "service_overview", "answer_service_knowledge", "jet_ski_ride", "overview"),
    _one("speed_boat_typo", "explicit_service", "en", "speed baot details", "service_overview", "answer_service_knowledge", "speed_boat_ride", "overview"),
    _one("kayaking", "explicit_service", "en", "What is kayaking?", "service_overview", "answer_service_knowledge", "kayaking", "overview"),
    _one("pontoon_ride", "explicit_service", "en", "Tell me about Pontoon Boat", "service_overview", "answer_service_knowledge", "pontoon_boat_ride", "overview"),
    _one("floating", "explicit_service", "en", "I want Floating Gazebo", "service_overview", "answer_service_knowledge", "floating_gazebo", "overview"),
    _one("houseboat", "explicit_service", "hinglish", "Houseboat Celebration batao", "service_overview", "answer_service_knowledge", "houseboat_celebration", "overview"),
    _one("party_boat", "explicit_service", "en", "Tell me about Party Boat Celebration", "service_overview", "answer_service_knowledge", "party_boat_celebration", "overview"),
    _one("jetty", "explicit_service", "en", "Jetty Gazebo details please", "service_overview", "answer_service_knowledge", "jetty_gazebo", "overview"),
    _one("duration_party", "duration", "en", "How long is Party Boat Celebration?", "service_topic", "answer_service_knowledge", "party_boat_celebration", "duration"),
    _one("duration_jet_ski", "duration", "hinglish", "Jet Ski kitni der ki hai?", "service_topic", "answer_service_knowledge", "jet_ski_ride", "duration"),
    _one("duration_houseboat", "duration", "hi", "Houseboat Celebration कितनी देर है?", "service_topic", "answer_service_knowledge", "houseboat_celebration", "duration"),
    _one("duration_speed", "duration", "en", "speed boat duration", "service_topic", "answer_service_knowledge", "speed_boat_ride", "duration"),
    _one("venue_timings", "timings", "en", "What are your timings?", "venue_duration_timing", "answer_venue_knowledge", None, "operating_hours"),
    _one("closing_time", "timings", "en", "What time does Entartica close?", "venue_duration_timing", "answer_venue_knowledge", None, "operating_hours"),
    _one("timings_hinglish", "timings", "hinglish", "Entartica kab tak khula hai?", "venue_duration_timing", "answer_venue_knowledge", None, "operating_hours"),
    _one("celebration_hours", "timings", "en", "What are celebration service operating hours?", "venue_duration_timing", "answer_venue_knowledge", None, "operating_hours"),
    _one("location_en", "location", "en", "Where is Entartica Raipur?", "location", "answer_location"),
    _one("location_hi", "location", "hinglish", "Raipur location bhejo", "location", "answer_location"),
    _one("maps", "location", "en", "Send the Google Maps link", "location", "answer_location"),
    _one("price_celebration", "restricted", "en", "celebration price", "pricing", "handover_to_sales", None, None, True),
    _one("price_jet_ski", "restricted", "hinglish", "Jet Ski ka price kya hai", "pricing", "handover_to_sales", None, None, True),
    _one("quotation", "restricted", "en", "Can I get a corporate event quotation?", "pricing", "handover_to_sales", None, None, True),
    _one("book_anniversary", "restricted", "en", "book anniversary celebration", "booking", "handover_to_sales", None, None, True),
    _one("reserve_boat", "restricted", "en", "reserve Party Boat Celebration", "booking", "handover_to_sales", None, None, True),
    _one("availability_event", "restricted", "en", "Is corporate event available tomorrow?", "availability", "handover_to_sales", None, None, True),
    _one("availability_jet", "restricted", "hinglish", "Jet Ski slot available hai?", "availability", "handover_to_sales", None, None, True),
    _one("payment", "restricted", "en", "How can I make payment?", "payment", "handover_to_sales", None, None, True),
    _one("refund", "restricted", "en", "I need a refund", "cancellation_refund", "handover_to_sales", None, None, True),
    _one("hello", "acknowledgement", "en", "hi", "greeting", "answer_greeting"),
    _one("thanks", "acknowledgement", "en", "thank you", "greeting", "answer_greeting"),
    _one("dhanyavad", "acknowledgement", "hi", "धन्यवाद", "greeting", "answer_greeting"),
    _one("contact", "general", "en", "contact number?", "contact_information", "approved_sales_contact"),
    _one("facilities", "general", "en", "Do you have parking and washrooms?", "venue_facility", "answer_venue_knowledge"),
    _one("venue_overview", "general", "en", "Tell me about Entartica Sea World Raipur", "venue_overview", "answer_venue_knowledge"),
    _one("technical", "general", "en", "What engine model does the Speed Boat use?", "unknown_entartica_fact", "answer_unknown_entartica_fact", "speed_boat_ride", "technical_specification"),
    _one("open_general", "general", "en", "What is a lake?", "general_question", "answer_general_openai"),
    ConversationScenario("birthday_multiturn", "multi_turn", "en", (
        EvaluationTurn("I want to celebrate my birthday", "celebration_service_list", "answer_catalogue"),
        EvaluationTurn("12", "celebration_guest_count", "answer_venue_knowledge"),
        EvaluationTurn("13/08/2026", "celebration_planned_date", "answer_venue_knowledge"),
        EvaluationTurn("lively party-style", "customer_understanding_update", "answer_venue_knowledge"),
    )),
    ConversationScenario("birthday_multifact", "multi_turn", "en", (
        EvaluationTurn("birthday for 12 people on 13 August, something lively", "customer_understanding_update", "answer_venue_knowledge"),
    )),
    ConversationScenario("anniversary_multifact", "multi_turn", "en", (
        EvaluationTurn("anniversary for 2 people, private and relaxed", "celebration_service_list", "answer_catalogue"),
    )),
    ConversationScenario("guest_correction", "multi_turn", "en", (
        EvaluationTurn("I want a birthday celebration", "celebration_service_list", "answer_catalogue"),
        EvaluationTurn("12", "celebration_guest_count", "answer_venue_knowledge"),
        EvaluationTurn("Actually 14", "customer_understanding_update", "answer_venue_knowledge"),
    )),
    ConversationScenario("duration_interruption", "multi_turn", "en", (
        EvaluationTurn("I want a birthday celebration", "celebration_service_list", "answer_catalogue"),
        EvaluationTurn("12", "celebration_guest_count", "answer_venue_knowledge"),
        EvaluationTurn("How long is Party Boat?", "service_topic", "answer_service_knowledge", "party_boat_celebration", "duration"),
    )),
    ConversationScenario("price_interruption", "multi_turn", "hinglish", (
        EvaluationTurn("birthday celebration", "celebration_service_list", "answer_catalogue"),
        EvaluationTurn("price kya hai", "pricing", "handover_to_sales", None, None, True),
    )),
    ConversationScenario("location_interruption", "multi_turn", "en", (
        EvaluationTurn("birthday celebration", "celebration_service_list", "answer_catalogue"),
        EvaluationTurn("where is Entartica Raipur?", "location", "answer_location"),
    )),
)


@dataclass(frozen=True)
class EvaluationOutcome:
    intent_correct: bool
    state_extraction_correct: bool | None
    next_action_correct: bool | None
    restricted_policy_correct: bool | None
    recommendation_correct: bool | None
    context_retained: bool | None
    generic_fallback_used: bool


def evaluation_summary(outcomes: list[EvaluationOutcome]) -> dict[str, int | float | None]:
    total = len(outcomes)
    passed = sum(all(value is not False for value in (o.intent_correct, o.state_extraction_correct, o.next_action_correct, o.restricted_policy_correct, o.recommendation_correct, o.context_retained)) for o in outcomes)
    def rate(field):
        applicable = [getattr(o, field) for o in outcomes if getattr(o, field) is not None]
        return round(100 * sum(bool(value) for value in applicable) / len(applicable), 2) if applicable else None
    return {
        "total_scenarios": total, "passed": passed, "failed": total - passed,
        "intent_accuracy": rate("intent_correct"),
        "state_extraction_accuracy": rate("state_extraction_correct"),
        "correct_next_action": rate("next_action_correct"),
        "restricted_policy_accuracy": rate("restricted_policy_correct"),
        "recommendation_correctness": rate("recommendation_correct"),
        "context_retention": rate("context_retained"),
        "generic_fallback_rate": round(100 * sum(o.generic_fallback_used for o in outcomes) / total, 2) if total else 0.0,
    }


def evaluate_single_turn_routes(workflow) -> tuple[dict[str, int | float | None], list[str]]:
    """Evaluate deterministic route semantics without network or persistence."""
    outcomes: list[EvaluationOutcome] = []
    failures: list[str] = []
    expected_general_fallbacks = 0
    unexpected_entartica_fallbacks = 0
    for scenario in SCENARIOS:
        if len(scenario.turns) != 1:
            continue
        turn = scenario.turns[0]
        state = {
            "normalized_message": turn.message.casefold(), "previous_service_code": None,
            "previous_topic": None, "language": scenario.language,
            "_runtime": {"current_state": None}, "message_id": scenario.scenario_id,
            "intent": None, "service_code": None, "topic": None,
        }
        plan = workflow.plan_message(state)
        intent_ok = plan.get("intent") == turn.expected_intent
        route_ok = plan.get("selected_route") == turn.expected_route
        service_ok = plan.get("service_code") == turn.expected_service_code
        topic_ok = plan.get("topic") == turn.expected_topic
        handover_ok = bool(plan.get("requires_handover")) == turn.expected_handover
        passed = intent_ok and route_ok and service_ok and topic_ok and handover_ok
        if not passed:
            failures.append(scenario.scenario_id)
        generic = plan.get("selected_route") == "answer_general_openai"
        expected_general = turn.expected_route == "answer_general_openai"
        expected_general_fallbacks += int(generic and expected_general)
        unexpected_entartica_fallbacks += int(generic and not expected_general)
        outcomes.append(EvaluationOutcome(
            intent_correct=intent_ok and route_ok and service_ok and topic_ok,
            state_extraction_correct=None,
            next_action_correct=route_ok,
            restricted_policy_correct=handover_ok if turn.expected_handover else None,
            recommendation_correct=None,
            context_retained=None,
            generic_fallback_used=generic,
        ))
    summary = evaluation_summary(outcomes)
    total = len(outcomes)
    summary["expected_general_fallback_rate"] = round(100 * expected_general_fallbacks / total, 2) if total else 0.0
    summary["unexpected_entartica_fallback_rate"] = round(100 * unexpected_entartica_fallbacks / total, 2) if total else 0.0
    return summary, failures
