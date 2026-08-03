from types import SimpleNamespace
import importlib.util
from pathlib import Path

from app.services.raipur_langgraph import ApprovedFacts, MessagePlan, RaipurLangGraphWorkflow, deterministic_fact_fallback, normalize_section_heading, rank_sections_for_followup, validate_response_against_facts
from app.services.raipur_conversation import KnowledgeDraft
from app.services.raipur_automatic_replies import eligible_for_automatic_reply


class FakeConversation:
    def __init__(self): self.calls = 0
    def process(self, *_args, **_kwargs):
        self.calls += 1
        return SimpleNamespace(response_valid=True, draft_text="Approved customer response")


def state(message: str):
    return {
        "message_id": "message", "conversation_id": "conversation", "customer_id": "customer",
        "customer_message": message, "normalized_message": message.casefold(), "language": "en",
        "location_code": "raipur", "previous_service_code": "speed_boat_ride", "intent": "unknown",
        "entity_type": "unknown", "service_code": None, "topic": None, "use_previous_service": False,
        "requires_handover": False, "handover_reason": None, "answer_source": "none",
        "draft_response": None, "validation_status": "pending", "error": None, "route": "",
    }


def test_message_plan_rejects_unknown_fields():
    try: MessagePlan(intent="greeting", unsafe="value")
    except Exception: pass
    else: raise AssertionError("unknown plan fields must be rejected")


def test_location_and_catalogue_override_stale_service_context():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    location = workflow.plan_message({**state("What is the location of Raipur?"), "_runtime": {"current_state": None}})
    catalogue = workflow.plan_message({**state("What are the rides?"), "_runtime": {"current_state": None}})
    assert location["intent"] == "location"
    assert location["use_previous_service"] is False
    assert workflow.route({**state(""), **location}) == "answer_location"
    assert catalogue["intent"] == "service_catalogue"
    assert workflow.route({**state(""), **catalogue}) == "answer_catalogue"


def test_various_rides_is_catalogue_and_ignores_previous_service():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    plan = workflow.plan_message({**state("can you tell me about various rides"), "_runtime": {"current_state": None}})
    assert plan["intent"] == "service_catalogue"
    assert plan["use_previous_service"] is False


def test_restricted_route_never_depends_on_retrieval():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    update = workflow.plan_message({**state("What is the price of Jet Ski?"), "_runtime": {"current_state": None}})
    assert update["requires_handover"] is True
    assert workflow.route({**state(""), **update}) == "handover_to_sales"


def test_known_service_topics_use_canonical_codes_and_priority():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    cases = (
        ("Hat is the capacity of speed baot", "speed_boat_ride", "capacity"),
        ("Jet Ski kitni der ki hai", "jet_ski_ride", "duration"),
        ("Staycation me kya included hai", "staycation_combo", "inclusions"),
        ("Kayak me kitne log baith sakte hain", "kayaking", "capacity"),
    )
    for message, service_code, topic in cases:
        update = workflow.plan_message({**state(message), "_runtime": {"current_state": None}})
        assert (update["intent"], update["service_code"], update["topic"]) == ("service_topic", service_code, topic)


def test_named_service_is_not_misrouted_to_the_catalogue():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    plan = workflow.plan_message({**state("Tell me about the Jet Ski Ride"), "_runtime": {"current_state": None}})
    assert plan["intent"] == "service_overview"
    assert plan["service_code"] == "jet_ski_ride"


def test_booking_question_is_not_misrouted_to_location_by_where_word():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    plan = workflow.plan_message({**state("Where can I book Jet Ski?"), "_runtime": {"current_state": None}})
    assert plan["intent"] == "booking"
    assert plan["requires_handover"] is True


def test_context_followup_is_used_only_for_real_reference():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    followup = workflow.plan_message({**state("Can you give more details about it?"), "_runtime": {"current_state": None}})
    location = workflow.plan_message({**state("What is the address?"), "_runtime": {"current_state": None}})
    assert followup["intent"] == "contextual_service_followup"
    assert followup["use_previous_service"] is True
    assert location["intent"] == "location"
    assert location["use_previous_service"] is False


def test_broad_venue_questions_route_to_venue_knowledge_not_unknown_fact():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    for message in (
        "Tell me about Entartica Raipur.",
        "What is Entartica Sea World?",
        "Entartica ke baare mein batao.",
        "Can you give me information about the Raipur venue?",
    ):
        plan = workflow.plan_message({**state(message), "_runtime": {"current_state": None}})
        assert plan["intent"] == "venue_overview"
        assert plan["use_previous_service"] is False
        assert workflow.route({**state(""), **plan}) == "answer_venue_knowledge"


def test_graph_venue_answer_requires_identity_and_multiple_experiences():
    class VenueKnowledge:
        def answer_venue_overview(self, _question):
            return KnowledgeDraft(
                "Entartica Sea World Raipur is a water activity and celebration destination on Jhanjh Lake. "
                "Guests can enjoy Jet Ski, Speed Boat, Kayaking, and celebration experiences.",
                "raipur_general_information.md", .8, False, "About Entartica Raipur", 1, "general-id",
            )
    workflow = RaipurLangGraphWorkflow(FakeConversation(), knowledge=VenueKnowledge())
    result = workflow.invoke(state("Tell me about Entartica Raipur."), message=SimpleNamespace(content="Tell me about Entartica Raipur."), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="message")
    assert result.detected_intent == "venue_overview"
    assert result.safe_metadata["source_filename"] == "raipur_general_information.md"
    assert "destination" in result.draft_text.casefold() and "speed boat" in result.draft_text.casefold()


def test_technical_service_questions_fail_closed_before_service_rag():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    for message in (
        "What exact engine does your Speed Boat use?",
        "Which motor is installed in the Speed Boat?",
        "What horsepower is the Speed Boat?",
        "What is the current fuel level?",
        "Who is operating Jet Ski today?",
    ):
        plan = workflow.plan_message({**state(message), "_runtime": {"current_state": None}})
        assert plan["intent"] == "unknown_entartica_fact"
        assert plan["topic"] == "technical_specification"
        assert plan["use_previous_service"] is False


def test_graph_does_not_call_complete_legacy_processor():
    conversation = FakeConversation(); workflow = RaipurLangGraphWorkflow(conversation)
    result = workflow.invoke(state("Tell me about Jet Ski"), message=SimpleNamespace(content="Tell me about Jet Ski"), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="message")
    assert result.response_valid is True
    assert conversation.calls == 0


class FakeKnowledge:
    def __init__(self): self.calls = []
    def answer_service_details(self, question, service_name, service_code, **kwargs):
        self.calls.append((service_name, service_code, kwargs["detail_mode"]))
        return KnowledgeDraft("Speed Boat capacity is approved for the requested topic.", "speed_boat_ride.md", 0.9, False, "Capacity")


class FakeFallback:
    def __init__(self): self.calls = 0

    def respond(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            valid=True,
            text="I can help you choose an approved Raipur experience. Do you prefer thrill, relaxation, a family activity, or a celebration?",
        )


def test_graph_retrieves_exact_service_with_topic_without_legacy_processor():
    knowledge = FakeKnowledge(); legacy = FakeConversation()
    workflow = RaipurLangGraphWorkflow(legacy, knowledge=knowledge)
    result = workflow.invoke(state("What is the capacity of Speed Boat?"), message=SimpleNamespace(content="What is the capacity of Speed Boat?"), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="message")
    assert result.draft_text.startswith("Speed Boat capacity")
    assert knowledge.calls == [("Speed Boat", "speed_boat_ride", "capacity")]
    assert legacy.calls == 0


def test_graph_formats_duration_and_swimming_from_selected_topic_sections():
    class TopicKnowledge:
        def answer_service_details(self, _question, _service_name, _service_code, **kwargs):
            topic = kwargs["detail_mode"]
            if topic == "duration":
                return KnowledgeDraft("Sessions generally last around 5 to 10 minutes.", "jet_ski_ride.md", .9, False, "Duration", 1, "jet-ski", ("Duration",))
            return KnowledgeDraft("Swimming ability is not required. All passengers are provided with mandatory high-buoyancy life jackets before boarding.", "speed_boat_ride.md", .9, False, "Swimming Requirement", 1, "speed-boat", ("Swimming Requirement",))
    workflow = RaipurLangGraphWorkflow(FakeConversation(), knowledge=TopicKnowledge())
    duration = workflow.invoke(state("Jet Ski kitni der ki hai?"), message=SimpleNamespace(content="Jet Ski kitni der ki hai?"), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="message")
    swimming = workflow.invoke(state("Speed Boat ke liye swimming zaruri hai?"), message=SimpleNamespace(content="Speed Boat ke liye swimming zaruri hai?"), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="message")
    assert duration.safe_metadata["selected_section_heading"] == "Duration"
    assert "5 to 10 minutes" in duration.draft_text and "operating" not in duration.draft_text.casefold()
    assert swimming.draft_text.startswith("No, swimming ability is not required for the Speed Boat Ride.")
    assert "high-buoyancy life jackets" in swimming.draft_text and "Speed Boat swimming:" not in swimming.draft_text


def test_reused_graph_ignores_stale_caller_turn_fields_for_explicit_service_topic():
    class TopicKnowledge:
        def answer_service_details(self, _question, _service_name, service_code, **_kwargs):
            return KnowledgeDraft("Swimming ability is not required. All passengers are provided with mandatory high-buoyancy life jackets before boarding.", f"{service_code}.md", .9, False, "Swimming Requirement", 1, service_code, ("Swimming Requirement",))
    workflow = RaipurLangGraphWorkflow(FakeConversation(), knowledge=TopicKnowledge())
    stale = state("Is swimming required for Speed Boat?")
    stale.update({"intent": "service_topic", "service_code": "daycation_package", "topic": "inclusions", "selected_route": "answer_service_knowledge", "use_previous_service": True, "requires_handover": True, "answer_source": "provider_composition", "source_filename": "daycation_package.md", "validation_errors": ["stale"]})
    result = workflow.invoke(stale, message=SimpleNamespace(content="Is swimming required for Speed Boat?"), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="message")
    assert result.safe_metadata["service_code"] == "speed_boat_ride"
    assert result.safe_metadata["topic"] == "swimming"
    assert result.safe_metadata["selected_route"] == "answer_service_knowledge"
    assert result.safe_metadata["plan_consistency_repaired"] is False
    assert "Daycation" not in result.draft_text


def test_unexpected_question_uses_safe_conversational_fallback_without_inventing_facts():
    fallback = FakeFallback()
    workflow = RaipurLangGraphWorkflow(FakeConversation(), conversational_fallback=fallback)
    result = workflow.invoke(state("Help me choose a fun Raipur experience"), message=SimpleNamespace(content="Help me choose a fun Raipur experience"), customer={"id": "customer"}, conversation={"id": "conversation"}, source_message_id="message")
    assert fallback.calls == 1
    assert result.response_valid is True
    assert result.safe_metadata["response_basis"] == "conversational_fallback"
    assert "price" not in result.draft_text.casefold()


def test_validated_conversational_fallback_is_eligible_for_the_allowed_test_route():
    fallback = FakeFallback()
    result = RaipurLangGraphWorkflow(FakeConversation(), conversational_fallback=fallback).invoke(
        state("Help me choose a fun Raipur experience"),
        message=SimpleNamespace(content="Help me choose a fun Raipur experience"),
        customer={"id": "customer"}, conversation={"id": "conversation"}, source_message_id="message",
    )
    settings = SimpleNamespace(
        raipur_automatic_reply_enabled=True,
        exotel_outbound_enabled=True,
        raipur_approved_draft_send_enabled=True,
        raipur_automatic_reply_intents=("information",),
    )
    eligible, reason = eligible_for_automatic_reply(
        settings,
        result,
        {"draft_status": "pending_review", "sent_at": None, "external_message_id": None},
    )
    assert (eligible, reason) == (True, "eligible")


def test_restricted_question_never_uses_conversational_fallback():
    fallback = FakeFallback()
    workflow = RaipurLangGraphWorkflow(FakeConversation(), conversational_fallback=fallback)
    result = workflow.invoke(state("What is the price of Jet Ski?"), message=SimpleNamespace(content="What is the price of Jet Ski?"), customer={"id": "customer"}, conversation={"id": "conversation"}, source_message_id="message")
    assert fallback.calls == 0
    assert result.human_handover_required is True


def test_topic_validation_rejects_duration_only_and_unsupported_capacity():
    plan = MessagePlan(intent="service_topic", entity_type="service", service_code="speed_boat_ride", topic="capacity", confidence=1.0)
    facts = ApprovedFacts("raipur", "speed_boat_ride", "Speed Boat", "capacity", ("Capacity is 6 persons.",), ("capacity",))
    assert "missing_capacity_answer" in validate_response_against_facts(plan, "The duration is 15 minutes.", facts)
    assert "unsupported_number" in validate_response_against_facts(plan, "Speed Boat capacity is 10 persons.", facts)


def test_fact_validation_preserves_negation_and_fallback_is_deterministic():
    plan = MessagePlan(intent="service_topic", entity_type="service", service_code="kayaking", topic="swimming", confidence=1.0)
    facts = ApprovedFacts("raipur", "kayaking", "Kayaking", "swimming", ("Swimming is not required.",), ("swimming requirement",))
    assert "negation_changed" in validate_response_against_facts(plan, "Swimming is mandatory.", facts)
    assert deterministic_fact_fallback(facts, "en") == "Swimming is not required."


def test_followup_sections_prefer_unused_and_explicit_topic_overrides():
    headings = ["Overview", "Safety Equipment", "Swimming Requirement", "Duration"]
    assert normalize_section_heading("Safety-Equipment!") == "safety equipment"
    ranked = rank_sections_for_followup(headings, ["overview", "Duration."])
    assert ranked[:2] == ["Safety Equipment", "Swimming Requirement"]
    explicit = rank_sections_for_followup(headings, ["duration"], explicit_topic="duration")
    assert explicit[0] == "Duration"


def test_readonly_evaluation_adapter_hides_client_and_blocks_writes():
    from app.evaluation.raipur_readonly_adapter import RaipurReadOnlyAdapter, ReadOnlyEvaluationViolation
    adapter = RaipurReadOnlyAdapter(object())
    assert not hasattr(adapter, "client")
    try: adapter.insert()
    except ReadOnlyEvaluationViolation: pass
    else: raise AssertionError("write guard must fail closed")
    assert adapter.database_write_attempts == 1


def test_promptfoo_provider_is_offline_and_reports_route():
    path = Path("evals/providers/chatbot_provider.py")
    spec = importlib.util.spec_from_file_location("offline_promptfoo_provider", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    output = module.call_api("What is the price of Jet Ski?", {}, {})
    assert output["output"] == "route=handover_to_sales; intent=pricing; service_code=none"
