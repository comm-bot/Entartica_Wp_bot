from types import SimpleNamespace
import importlib.util
from pathlib import Path

from app.services.raipur_langgraph import ApprovedFacts, MessagePlan, RaipurLangGraphWorkflow, deterministic_fact_fallback, normalize_section_heading, rank_sections_for_followup, validate_response_against_facts
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
from app.services.raipur_automatic_replies import eligible_for_automatic_reply
from app.services.booking_enquiries import BookingDetails


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


def test_resolver_only_topics_map_to_supported_graph_topics_without_crashing():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    cases = (
        ("Can pregnant women ride Jet Ski?", "service_topic", "jet_ski_ride", "eligibility"),
        ("Can I drive Jet Ski myself?", "service_topic", "jet_ski_ride", "how_it_works"),
        ("What happens if I fall from Jet Ski?", "service_topic", "jet_ski_ride", "safety"),
    )
    for message, intent, service_code, topic in cases:
        update = workflow.plan_message({**state(message), "_runtime": {"current_state": None}})
        assert (update["intent"], update["service_code"], update["topic"]) == (intent, service_code, topic)
        assert workflow.route({**state(message), **update}) == "answer_service_knowledge"


def test_service_comparison_question_maps_to_overview_without_crashing():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    update = workflow.plan_message({**state("Compare Jet Ski and Speed Boat."), "_runtime": {"current_state": None}})
    assert update["topic"] == "overview"
    assert update["selected_route"] == "answer_service_knowledge"
    assert update["requires_handover"] is False


def test_explicit_service_alias_definitions_use_canonical_service_context():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    for message in ("What is kayaking?", "What is a pontoon boat?", "What is a jet ski?", "How does kayaking generally work?"):
        plan = workflow.plan_message({**state(message), "_runtime": {"current_state": None}})
        assert plan["intent"] in {"service_overview", "service_topic"}
        assert plan["selected_route"] == "answer_service_knowledge"
        assert plan["service_code"] is not None and plan["use_previous_service"] is False
    specific = workflow.plan_message({**state("Tell me about Kayaking at Entartica."), "_runtime": {"current_state": None}})
    assert (specific["intent"], specific["service_code"], specific["selected_route"]) == ("service_overview", "kayaking", "answer_service_knowledge")


def test_unknown_facts_and_thanks_use_dedicated_deterministic_routes():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    unknown = workflow.plan_message({**state("What exact engine does your Speed Boat use?"), "_runtime": {"current_state": None}})
    thanks = workflow.plan_message({**state("Thank you."), "_runtime": {"current_state": None}})
    assert unknown["selected_route"] == "answer_unknown_entartica_fact"
    assert (thanks["intent"], thanks["service_code"], thanks["topic"], thanks["use_previous_service"]) == ("greeting", None, None, False)


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


def _service_context(code, name):
    return ConversationContext(
        BookingDetails(None, None, None, None, None, None, None),
        last_service_name=name, last_service_code=code, active_topic="overview",
    )


def _greeting_answer_state(message, context):
    base = state(message)
    base.update({
        "selected_route": "answer_greeting",
        "intent": "greeting",
        "_runtime": {"current_state": context, "customer": {"id": "customer"}, "conversation": {"id": "conversation"}},
    })
    return base


def test_acknowledgement_preserves_active_service_context():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    context = _service_context("houseboat_celebration", "Houseboat Celebration")
    result = workflow.answer_existing(_greeting_answer_state("Thank you", context))["result"]
    assert result.context.last_service_code == "houseboat_celebration"
    assert result.context.last_service_name == "Houseboat Celebration"
    assert result.context.active_topic == "overview"
    assert "welcome" in result.draft_text.casefold() or "swagat" in result.draft_text.casefold()


def test_fresh_greeting_still_clears_active_service_context():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    context = _service_context("houseboat_celebration", "Houseboat Celebration")
    result = workflow.answer_existing(_greeting_answer_state("Hello", context))["result"]
    assert result.context.last_service_code is None
    assert result.context.last_service_name is None
    assert result.context.active_topic is None


def test_acknowledgement_without_active_service_keeps_context_unchanged():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    context = ConversationContext(BookingDetails(None, None, None, None, None, None, None))
    result = workflow.answer_existing(_greeting_answer_state("theek hai", context))["result"]
    assert result.context.last_service_code is None
    assert result.draft_text.strip()


def test_family_fun_questions_route_to_family_discovery_intent():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    for message in (
        "i am coming with my family, which fun activities we can do?",
        "family ke saath kya activities kar sakte hain?",
        "परिवार के साथ क्या कर सकते हैं?",
        "We are coming with children. What rides can we do?",
        "family ke saath kya kar sakte hain?",
    ):
        update = workflow.plan_message({**state(message), "_runtime": {"current_state": None}})
        assert update["intent"] == "family_activity_discovery", message
        assert update["requires_handover"] is False, message
        assert workflow.route({**state(message), **update}) == "answer_venue_knowledge", message


def test_family_discovery_does_not_hijack_service_restricted_or_catalogue_routes():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    cases = (
        ("Tell me about Jet Ski", "service_overview", "answer_service_knowledge", False),
        ("What activities do you have?", "service_catalogue", "answer_catalogue", False),
        ("What is the price for family activities?", "pricing", "handover_to_sales", True),
        ("Book family activities for tomorrow.", "booking", "handover_to_sales", True),
        ("Which family rides are available today?", "service_catalogue", "answer_catalogue", False),
        ("What is the location of Raipur?", "location", "answer_location", False),
    )
    for message, intent, route, handover in cases:
        update = workflow.plan_message({**state(message), "_runtime": {"current_state": None}})
        assert update["intent"] == intent, message
        assert workflow.route({**state(message), **update}) == route, message
        assert update["requires_handover"] is handover, message


def test_family_discovery_context_followup_uses_catalogue_context():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    update = workflow.plan_message({**state("kids options batao"), "previous_topic": "activity_catalogue", "_runtime": {"current_state": None}})
    assert update["intent"] == "service_catalogue"
    assert update["selected_route"] == "answer_catalogue"
    assert update["requires_handover"] is False


class FakeServices:
    def __init__(self, rows):
        self.rows = rows
    def list_active_for_location(self, location_id):
        return self.rows


def test_general_celebration_intent_routes_directly_to_catalogue():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    for message in (
        "I want to celebrate",
        "mujhe celebration karvana hain",
        "मुझे सेलिब्रेशन करना है",
    ):
        update = workflow.plan_message({**state(message), "_runtime": {"current_state": None}})
        assert update["intent"] == "celebration_service_list", message
        assert update["requires_handover"] is False, message
        assert workflow.route({**state(message), **update}) == "answer_catalogue", message


def test_general_celebration_requests_show_approved_options_immediately():
    from app.services.raipur_services import APPROVED_RAIPUR_SERVICES

    class ForbiddenPlanner:
        def plan(self, *_args, **_kwargs):
            raise AssertionError("general celebration request reached planner")

    rows = [
        {"id": item.slug, "name": item.name, "active": True}
        for item in APPROVED_RAIPUR_SERVICES
        if item.category == "floating_celebration"
    ]
    workflow = RaipurLangGraphWorkflow(
        FakeConversation(), planner=ForbiddenPlanner(), services=FakeServices(rows)
    )
    forbidden = (
        "what occasion", "birthday or anniversary", "what kind of event",
        "corporate or client event", "couple or family",
        "relaxed or adventurous", "what kind of adventure",
    )

    for message in (
        "mujhe celebration karvana hain",
        "I want to celebrate something",
        "anniversary celebration karni hai",
        "corporate event karna hai",
        "one special event",
    ):
        plan = workflow.plan_message({
            **state(message), "previous_service_code": None,
            "previous_topic": None, "_runtime": {"current_state": None},
        })
        answer_state = {
            **state(message), **plan,
            "_runtime": {"current_state": None, "customer": {"id": "customer"}, "conversation": {"id": "conversation", "location_id": "raipur"}},
        }
        result = workflow.answer_existing(answer_state)["result"]
        assert result.detected_intent == "celebration_service_list", message
        for option in (
            "Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo",
            "Party Boat Celebration", "Pontoon Celebration",
        ):
            assert option in result.draft_text, (message, option)
        response = result.draft_text.casefold()
        assert not any(question in response for question in forbidden), message
        assert result.context.pending_clarification_type is None


def test_occasion_reply_after_pending_celebration_uses_celebration_catalogue():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    for message in (
        "anniversary",
        "birthday",
        "सालगिरह",
        "birthday karna hai",
        "corporate event",
        "corporate outing",
        "client event",
        "team celebration",
        "birthday celebration",
        "anniversary celebration",
        "corporate function",
        "office event",
    ):
        update = workflow.plan_message({**state(message), "previous_topic": "celebration_catalogue", "_runtime": {"current_state": None}})
        assert update["intent"] == "celebration_service_list", message
        assert update["requires_handover"] is False, message
        assert workflow.route({**state(message), **update}) == "answer_catalogue", message


def test_occasion_reply_after_pending_celebration_shows_approved_options():
    from app.services.raipur_services import APPROVED_RAIPUR_SERVICES
    rows = [{"id": item.slug, "name": item.name, "active": True} for item in APPROVED_RAIPUR_SERVICES if item.category == "floating_celebration"]
    workflow = RaipurLangGraphWorkflow(FakeConversation(), services=FakeServices(rows))
    context = ConversationContext(
        BookingDetails(None, None, None, None, None, None, None),
        active_topic="celebration_catalogue", active_entity_type="catalogue", active_entity_name="celebration",
    )
    base = state("anniversary")
    base.update({
        "selected_route": "answer_catalogue",
        "intent": "celebration_service_list",
        "_runtime": {"current_state": context, "customer": {"id": "customer"}, "conversation": {"id": "conversation", "location_id": "raipur"}},
    })
    result = workflow.answer_existing(base)["result"]
    assert "Floating Gazebo" in result.draft_text
    assert "Houseboat Celebration" in result.draft_text
    assert "Pontoon Celebration" in result.draft_text
    assert result.context.active_topic == "celebration_catalogue"
    assert result.context.pending_clarification is False


def test_followup_after_immediate_celebration_catalogue_does_not_requalify():
    from app.services.raipur_services import APPROVED_RAIPUR_SERVICES

    class ForbiddenPlanner:
        def plan(self, *_args, **_kwargs):
            raise AssertionError("generic planner must not receive a pending occasion answer")

    rows = [
        {"id": item.slug, "name": item.name, "active": True}
        for item in APPROVED_RAIPUR_SERVICES
        if item.category == "floating_celebration"
    ]
    workflow = RaipurLangGraphWorkflow(
        FakeConversation(), planner=ForbiddenPlanner(), services=FakeServices(rows)
    )
    forbidden_questions = (
        "corporate outing or client event",
        "what type of event",
        "corporate gathering or celebration",
        "what occasion",
        "share your occasion",
    )

    for opening, occasion in (
        ("muje celebration karvana he", "one special event"),
        ("mujhe celebration karvana hain", "something special"),
        ("I want to celebrate", "family function"),
        ("I want to celebrate", "anniversary"),
    ):
        first_plan = workflow.plan_message(
            {**state(opening), "previous_service_code": None, "previous_topic": None, "_runtime": {"current_state": None}}
        )
        first_state = {
            **state(opening), **first_plan,
            "_runtime": {"current_state": None, "customer": {"id": "customer"}, "conversation": {"id": "conversation", "location_id": "raipur"}},
        }
        first_result = workflow.answer_existing(first_state)["result"]
        assert first_result.detected_intent == "celebration_service_list"
        assert first_result.context.pending_clarification is False
        assert first_result.context.pending_clarification_type is None

        second_plan = workflow.plan_message({
            **state(occasion),
            "previous_service_code": first_result.context.last_service_code,
            "previous_topic": first_result.context.active_topic,
            "_runtime": {"current_state": first_result.context},
        })
        second_state = {
            **state(occasion), **second_plan,
            "_runtime": {"current_state": first_result.context, "customer": {"id": "customer"}, "conversation": {"id": "conversation", "location_id": "raipur"}},
        }
        second_result = workflow.answer_existing(second_state)["result"]

        assert second_result.detected_intent == "celebration_service_list", occasion
        for option in (
            "Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo",
            "Party Boat Celebration", "Pontoon Celebration",
        ):
            assert option in second_result.draft_text, (occasion, option)
        response = second_result.draft_text.casefold()
        assert not any(question in response for question in forbidden_questions), occasion
        assert second_result.context.pending_clarification is False
        assert second_result.context.pending_clarification_type is None


def test_pending_celebration_does_not_hijack_clear_intents():
    from app.services.raipur.context_state import set_celebration_occasion_pending

    class ForbiddenPlanner:
        def plan(self, *_args, **_kwargs):
            raise AssertionError("clear intent or pending occasion reached planner")

    context = set_celebration_occasion_pending(
        ConversationContext(BookingDetails(None, None, None, None, None, None, None))
    ).updated_context
    workflow = RaipurLangGraphWorkflow(FakeConversation(), planner=ForbiddenPlanner())
    cases = {
        "where is Entartica Raipur?": "location",
        "what are your timings?": "venue_duration_timing",
        "contact number?": "contact_information",
        "Tell me about Jet Ski": "service_overview",
        "hi": "greeting",
        "thank you": "greeting",
        "one special event": "celebration_service_list",
        "something special": "celebration_service_list",
    }

    for message, expected_intent in cases.items():
        update = workflow.plan_message({
            **state(message),
            "previous_service_code": context.last_service_code,
            "previous_topic": context.active_topic,
            "_runtime": {"current_state": context},
        })
        assert update["intent"] == expected_intent, message


def test_explicit_service_still_wins_with_pending_celebration():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    update = workflow.plan_message({**state("Houseboat Celebration"), "previous_topic": "celebration_catalogue", "_runtime": {"current_state": None}})
    assert update["intent"] == "service_overview"
    assert update["service_code"] == "houseboat_celebration"
    assert update["requires_handover"] is False
    assert workflow.route({**state(""), **update}) == "answer_service_knowledge"


def test_pricing_still_wins_with_pending_celebration():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    update = workflow.plan_message({**state("corporate event price"), "previous_topic": "celebration_catalogue", "_runtime": {"current_state": None}})
    assert update["intent"] == "pricing"
    assert update["requires_handover"] is True
    assert workflow.route({**state(""), **update}) == "handover_to_sales"


def test_booking_still_wins_with_pending_celebration():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    update = workflow.plan_message({**state("book corporate event"), "previous_topic": "celebration_catalogue", "_runtime": {"current_state": None}})
    assert update["intent"] == "booking"
    assert update["requires_handover"] is True
    assert workflow.route({**state(""), **update}) == "handover_to_sales"


def test_cancel_clears_pending_celebration_flow():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    for message in ("cancel", "cancel karo", "stop"):
        update = workflow.plan_message({**state(message), "previous_topic": "celebration_catalogue", "_runtime": {"current_state": None}})
        assert update["intent"] == "celebration_cancel", message
        assert update["requires_handover"] is False, message
        assert workflow.route({**state(message), **update}) == "answer_venue_knowledge", message


def test_cancel_answer_clears_pending_celebration_context():
    from app.services.raipur.context_state import set_celebration_occasion_pending
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    context = set_celebration_occasion_pending(_service_context("houseboat_celebration", "Houseboat Celebration")).updated_context
    base = state("cancel")
    base.update({
        "selected_route": "answer_venue_knowledge",
        "intent": "celebration_cancel",
        "_runtime": {"current_state": context, "customer": {"id": "customer"}, "conversation": {"id": "conversation"}},
    })
    result = workflow.answer_existing(base)["result"]
    assert result.context.pending_clarification is False
    assert result.context.pending_clarification_type is None
    assert result.context.pending_clarification_options == ()
    assert result.context.active_topic is None
    assert result.context.active_entity_name is None
    assert result.context.last_service_code is None


def test_celebration_cancel_never_hijacks_restricted_handover_routes():
    workflow = RaipurLangGraphWorkflow(FakeConversation())
    abandon = workflow.plan_message({**state("cancel"), "previous_topic": "celebration_catalogue", "_runtime": {"current_state": None}})
    assert abandon["intent"] == "celebration_cancel"
    assert abandon["requires_handover"] is False
    for message in (
        "cancel my booking",
        "I want a refund for my anniversary booking",
    ):
        update = workflow.plan_message({**state(message), "previous_topic": "celebration_catalogue", "_runtime": {"current_state": None}})
        assert update["intent"] in {"booking", "cancellation_refund"}, message
        assert update["intent"] != "celebration_cancel", message
        assert update["requires_handover"] is True, message
        assert workflow.route({**state(message), **update}) == "handover_to_sales", message


def _celebration_workflow():
    from app.services.raipur_services import APPROVED_RAIPUR_SERVICES
    from app.rag.raipur_ingestion import build_plan
    from app.services.raipur.pontoon_package import render_pontoon_package

    rows = [
        {"id": item.slug, "name": item.name, "is_active": True}
        for item in APPROVED_RAIPUR_SERVICES
        if item.category == "floating_celebration"
    ]

    plan, errors = build_plan(Path(__file__).resolve().parents[1])
    assert not errors
    pontoon_document = next(
        row.document for row in plan
        if row.document and row.document.source_file == "active/services/pontoon_celebration.md"
    )
    pontoon_package = render_pontoon_package(
        {section.heading: section.text for section in pontoon_document.sections},
        source_file=pontoon_document.source_file,
    )
    assert pontoon_package is not None

    class CelebrationKnowledge:
        def approved_pontoon_package(self):
            return pontoon_package

        def answer_service_details(self, _question, service_name, service_code, **kwargs):
            topic = kwargs["detail_mode"]
            text = "Party Boat Celebration lasts 2 hours." if topic == "duration" else f"{service_name} is an approved celebration service."
            heading = "Duration" if topic == "duration" else "Experience Overview"
            return KnowledgeDraft(text, f"{service_code}.md", .9, False, heading, 1, service_code, (heading,))

    return RaipurLangGraphWorkflow(FakeConversation(), knowledge=CelebrationKnowledge(), services=FakeServices(rows))


def _sales_turn(workflow, message, context=None, language="en"):
    turn_state = {**state(message), "language": language, "previous_service_code": getattr(context, "last_service_code", None), "previous_topic": getattr(context, "active_topic", None)}
    return workflow.invoke(
        turn_state,
        message=SimpleNamespace(content=message),
        customer={"id": "customer"},
        conversation={"id": "conversation", "location_id": "raipur"},
        source_message_id="message",
        current_state=context,
    )


def test_celebration_sales_journey_collects_guests_then_date_without_duplicates():
    workflow = _celebration_workflow()
    first = _sales_turn(workflow, "I want to celebrate my birthday")
    assert "Floating Gazebo" in first.draft_text and "guests" in first.draft_text.casefold()
    assert first.context.pending_field == "total_guests"

    second = _sales_turn(workflow, "12", first.context)
    assert second.context.details.total_guests == 12
    assert second.context.pending_field == "preferred_date"
    assert "date" in second.draft_text.casefold() and "guest" not in second.draft_text.casefold().split("what date")[1]

    third = _sales_turn(workflow, "13/08/2026", second.context)
    assert third.context.details.total_guests == 12
    assert third.context.details.preferred_date.isoformat() == "2026-08-13"
    assert third.context.pending_field == "celebration_preference"
    assert "13 August 2026" in third.draft_text and "12" in third.draft_text
    assert "what date" not in third.draft_text.casefold()
    assert "how many guests" not in third.draft_text.casefold()


def test_hinglish_celebration_sales_journey_keeps_context():
    workflow = _celebration_workflow()
    first = _sales_turn(workflow, "mujhe birthday celebrate karna hai", language="hinglish")
    second = _sales_turn(workflow, "10", first.context, "hinglish")
    third = _sales_turn(workflow, "15 August", second.context, "hinglish")
    assert third.context.details.total_guests == 10
    assert third.context.details.preferred_date is not None
    assert third.context.pending_field == "celebration_preference"


def test_celebration_sales_interruptions_preserve_collected_guests():
    workflow = _celebration_workflow()
    first = _sales_turn(workflow, "birthday celebration")
    second = _sales_turn(workflow, "12", first.context)

    duration = _sales_turn(workflow, "How long is Party Boat Celebration?", second.context)
    assert "2 hours" in duration.draft_text
    assert duration.context.details.total_guests == 12
    assert duration.context.pending_field == "preferred_date"

    pricing = _sales_turn(workflow, "what is the price?", second.context)
    assert pricing.human_handover_required is True
    assert pricing.detected_intent == "pricing"

    selected = _sales_turn(workflow, "Party Boat Celebration", second.context)
    assert selected.context.last_service_code == "party_boat_celebration"
    assert selected.context.details.total_guests == 12
    assert selected.context.pending_field == "preferred_date"


def test_pontoon_selection_attaches_approved_media_once_and_enters_durable_qualification():
    workflow = _celebration_workflow()
    selected = _sales_turn(workflow, "Pontoon Boat Celebration")
    assert selected.context.last_service_code == "pontoon_celebration"
    assert selected.context.active_journey == "celebration"
    assert selected.context.pending_action == "celebration_sales"
    assert "what date" in selected.draft_text.casefold() and "how many persons" in selected.draft_text.casefold()
    assert selected.safe_metadata["pontoon_package_content_configured"] is True
    assert selected.safe_metadata["pontoon_media_attached"] is True
    media = selected.safe_metadata["media_message"]
    assert media["type"] == "image"
    assert media["url"].startswith("https://apsjacfeiaiwcklnjmaj.supabase.co/storage/v1/object/sign/")
    assert media["caption"].startswith("Pontoon Boat Celebration Package\n\nInclusions:")
    assert "Rack Rate: ₹9,500" in media["caption"]
    assert "Offer/Discounted Rate: ₹7,499" in media["caption"]
    assert "₹1,000 token payment" in media["caption"]
    assert "Full refund if cancelled before 24 hours" in media["caption"]
    assert media["caption"].endswith("Rates are valid for today.")
    assert selected.context.pending_slots["pontoon_media_sent"] == "true"

    repeated = _sales_turn(workflow, "Pontoon Boat Celebration", selected.context)
    assert repeated.safe_metadata["pontoon_media_attached"] is False
    assert "media_message" not in repeated.safe_metadata

    dated = _sales_turn(workflow, "25 August", selected.context)
    assert dated.context.details.preferred_date is not None
    assert dated.context.details.total_guests is None
    assert dated.context.pending_field == "total_guests"
    assert "how many" in dated.draft_text.casefold() and "what date" not in dated.draft_text.casefold()


def test_pontoon_combined_hinglish_qualification_and_corrections_replace_old_values():
    workflow = _celebration_workflow()
    selected = _sales_turn(workflow, "Pontoon Boat Celebration")
    combined = _sales_turn(workflow, "25 August ko 6 log", selected.context, "hinglish")
    assert combined.context.details.preferred_date is not None
    assert combined.context.details.total_guests == 6

    guests = _sales_turn(workflow, "actually 8 people", combined.context)
    assert guests.context.details.total_guests == 8
    changed = _sales_turn(workflow, "change date to 27 August", guests.context)
    assert changed.context.details.preferred_date.day == 27

    slash = _sales_turn(workflow, "25/08, total 6", selected.context)
    assert slash.context.details.preferred_date is not None
    assert slash.context.details.total_guests == 6


def test_pontoon_future_combined_input_bypasses_generic_completion_response():
    workflow = _celebration_workflow()
    selected = _sales_turn(workflow, "Pontoon Celebration")
    completed = _sales_turn(workflow, "25/08/2026, 25", selected.context)
    assert completed.context.details.preferred_date.isoformat() == "2026-08-25"
    assert completed.context.details.total_guests == 25
    assert completed.context.last_service_code == "pontoon_celebration"
    assert completed.safe_metadata["graph_answer_source"] == "pontoon_post_qualification"
    assert completed.safe_metadata["pontoon_package_content_configured"] is True
    assert "noted the celebration details" not in completed.draft_text.casefold()
    assert "approved next step" not in completed.draft_text.casefold()


def test_pontoon_past_date_rejected_but_valid_guest_count_is_retained():
    workflow = _celebration_workflow()
    selected = _sales_turn(workflow, "Pontoon Celebration")
    result = _sales_turn(workflow, "15/08/2026, 25", selected.context)
    assert result.context.details.preferred_date is None
    assert result.context.details.total_guests == 25
    assert result.context.pending_field == "preferred_date"
    assert result.safe_metadata["past_date_rejected"] is True
    assert "already passed" in result.draft_text.casefold()
    assert "guest" not in result.draft_text.casefold()


def test_pontoon_question_interruption_and_explicit_service_switch_preserve_durable_facts():
    workflow = _celebration_workflow()
    selected = _sales_turn(workflow, "Pontoon Boat Celebration")
    qualified = _sales_turn(workflow, "25 August, 6 people", selected.context)
    duration = _sales_turn(workflow, "duration?", qualified.context)
    assert duration.context.last_service_code == "pontoon_celebration"
    assert duration.context.details.preferred_date == qualified.context.details.preferred_date
    assert duration.context.details.total_guests == 6
    assert "what date" not in duration.draft_text.casefold() and "how many" not in duration.draft_text.casefold()

    switched = _sales_turn(workflow, "Tell me about Staycation", duration.context)
    assert switched.context.last_service_code == "staycation_combo"
    assert switched.context.details.preferred_date == qualified.context.details.preferred_date
    assert switched.context.details.total_guests == 6


def test_pontoon_customization_handover_preserves_known_qualification():
    workflow = _celebration_workflow()
    selected = _sales_turn(workflow, "Pontoon Boat Celebration")
    qualified = _sales_turn(workflow, "25 August, 6 people", selected.context)
    handover = _sales_turn(workflow, "Can I customize the decoration and food?", qualified.context)
    assert handover.human_handover_required is True
    assert handover.context.last_service_code == "pontoon_celebration"
    assert handover.context.details.preferred_date == qualified.context.details.preferred_date
    assert handover.context.details.total_guests == 6
