"""Fake-only integration coverage for the enabled LangGraph orchestrator path."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.booking_enquiries import BookingDetails
from app.services.raipur_conversation import ConversationContext, KnowledgeDraft
from app.services.raipur_automatic_replies import eligible_for_automatic_reply
import app.services.raipur_inbound_orchestrator as module


class _Locations:
    def __init__(self, _client): pass

    def get_location_by_code(self, _code):
        return {
            "id": "raipur-id",
            "metadata": {
                "location_name": "Entartica Sea World Raipur",
                "address_line": "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh",
                "landmark": "Near MAYFAIR Resort",
                "maps_url": "https://maps.example/raipur",
            },
        }


class _Services:
    def __init__(self, _client): pass

    def list_active_for_location(self, _location_id):
        return [{"name": "Speed Boat"}, {"name": "Kayak"}, {"name": "Jet Ski"}]


class _Contexts:
    def __init__(self, _client): self.saved = []; self.records = {}

    def get_service_context(self, conversation_id, customer_id): return self.records.get((conversation_id, customer_id))

    def save_service_context(self, conversation_id, customer_id, record):
        self.saved.append((conversation_id, customer_id, record)); self.records[(conversation_id, customer_id)] = record


class _Knowledge:
    def __init__(self): self.service_calls = []; self.venue_calls = []

    def answer_service_details(self, question, service_name, service_code, **kwargs):
        self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
        text = "Speed Boat capacity is six guests." if kwargs.get("detail_mode") == "capacity" else "Speed Boat is an approved Raipur water-ride experience."
        return KnowledgeDraft(text, "speed_boat_ride.md", 0.8, False, "Capacity" if kwargs.get("detail_mode") == "capacity" else "Overview", 2, "document-speed-boat")

    def answer_venue_overview(self, question):
        self.venue_calls.append(question)
        return KnowledgeDraft(
            "Entartica Sea World Raipur is a water activity and celebration destination on Jhanjh Lake. "
            "It offers water sports such as Jet Ski and Speed Boat, non-motorised activities such as Kayaking, and celebration experiences.",
            "raipur_general_information.md", 0.8, False, "About Entartica Raipur", 1, "document-venue",
        )


def _message(text):
    return NormalizedInboundMessage(
        external_message_id="message-id", customer_whatsapp_number="+910000000000",
        business_whatsapp_number="+911111111111", message_type="text", content=text,
        received_at=datetime.now(timezone.utc),
    )


def _orchestrator(monkeypatch, knowledge):
    monkeypatch.setattr(module, "LocationRepository", _Locations)
    monkeypatch.setattr(module, "ServiceRepository", _Services)
    monkeypatch.setattr(module, "ConversationRepository", _Contexts)
    monkeypatch.setattr(module, "BookingEnquiryRepository", lambda _client: object())
    monkeypatch.setattr(module, "BookingEnquiryService", lambda *_args: object())
    monkeypatch.setattr(module, "build_raipur_availability_provider", lambda *_args, **_kwargs: object())
    settings = SimpleNamespace(
        app_timezone="Asia/Kolkata", raipur_langgraph_enabled=True,
        router_revision="raipur-router-test", raipur_conversation_context_ttl_minutes=120,
        conversation_session_ttl_minutes=30,
    )
    return module.RaipurInboundOrchestrator(object(), settings, knowledge_provider=knowledge)


def _process(orchestrator, text, context=None, *, customer_id="customer-id", conversation_id="conversation-id"):
    return orchestrator.process(
        _message(text), customer={"id": customer_id}, conversation={"id": conversation_id},
        source_message_id="message-id", current_state=context,
    )


def test_enabled_graph_catalogue_uses_multiple_services_and_no_handover(monkeypatch):
    result = _process(_orchestrator(monkeypatch, _Knowledge()), "can you tell me about various rides")
    assert result.detected_intent == "service_catalogue"
    assert result.safe_metadata["active_engine"] == "langgraph"
    assert "Speed Boat" in result.draft_text and "Kayak" in result.draft_text
    assert not result.human_handover_required
    assert "visit date" not in result.draft_text.casefold() and "guest count" not in result.draft_text.casefold()
    assert result.safe_metadata["response_basis"] == "deterministic"


def test_enabled_graph_location_overrides_stale_service_context(monkeypatch):
    context = ConversationContext(BookingDetails(None, None, None, None, None, None, None), last_service_name="Speed Boat", last_service_code="speed_boat_ride")
    result = _process(_orchestrator(monkeypatch, _Knowledge()), "What is the location of Raipur?", context)
    assert result.detected_intent == "location" and result.context.last_service_code is None
    assert "Sector 24" in result.draft_text and not result.human_handover_required


def test_enabled_graph_exact_service_preserves_grounding_for_automatic_reply(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "Tell me about Speed Boat.")
    assert knowledge.service_calls == [("Tell me about Speed Boat.", "Speed Boat", "speed_boat_ride", "overview")]
    assert result.safe_metadata["service_code"] == "speed_boat_ride"
    assert result.safe_metadata["source_filename"] == "speed_boat_ride.md"
    assert result.safe_metadata["source_document_id"] == "document-speed-boat"
    assert result.safe_metadata["source_heading"] == "Overview"
    settings = SimpleNamespace(
        raipur_automatic_reply_enabled=True, exotel_outbound_enabled=True,
        raipur_approved_draft_send_enabled=True,
        raipur_automatic_reply_intents=("information",),
    )
    assert eligible_for_automatic_reply(
        settings, result,
        {"draft_status": "pending_review", "sent_at": None, "external_message_id": None},
    ) == (True, "eligible")


def test_enabled_graph_capacity_uses_exact_service_topic_and_preserves_source(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "What is the capacity of Speed Boat?")
    assert knowledge.service_calls == [("What is the capacity of Speed Boat?", "Speed Boat", "speed_boat_ride", "capacity")]
    assert result.safe_metadata["topic"] == "capacity"
    assert result.safe_metadata["source_filename"] == "speed_boat_ride.md"


def test_enabled_graph_venue_overview_calls_venue_provider(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "Tell me about Entartica Raipur.")
    assert result.detected_intent == "venue_overview"
    assert knowledge.venue_calls == ["Tell me about Entartica Raipur."]
    assert result.safe_metadata["source_filename"] == "raipur_general_information.md"
    assert "destination" in result.draft_text.casefold() and "speed boat" in result.draft_text.casefold()
    assert not result.human_handover_required and result.context.last_service_code is None
    settings = SimpleNamespace(raipur_automatic_reply_enabled=True, exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True, raipur_automatic_reply_intents=("information",))
    assert eligible_for_automatic_reply(settings, result, {"draft_status": "pending_review", "sent_at": None, "external_message_id": None}) == (True, "eligible")


def test_weak_venue_provider_uses_catalogue_backed_fallback_without_sales(monkeypatch):
    class WeakKnowledge(_Knowledge):
        def answer_venue_overview(self, question):
            self.venue_calls.append(question)
            return KnowledgeDraft("Our location is in Raipur, Chhattisgarh.", "raipur_general_information.md", .8, False, "Location")
    result = _process(_orchestrator(monkeypatch, WeakKnowledge()), "Tell me about Entartica Raipur.")
    assert "destination" in result.draft_text.casefold() and "Speed Boat" in result.draft_text
    assert "sales@" not in result.draft_text.casefold()


def test_enabled_graph_venue_overview_variants_preserve_general_source(monkeypatch):
    for question in (
        "What is Entartica Sea World?",
        "Entartica ke baare mein batao.",
        "Can you give me information about the Raipur venue?",
    ):
        knowledge = _Knowledge()
        result = _process(_orchestrator(monkeypatch, knowledge), question)
        assert result.detected_intent == "venue_overview"
        assert knowledge.venue_calls == [question]
        assert result.safe_metadata["source_filename"] == "raipur_general_information.md"


def test_enabled_graph_booking_is_handover_without_rag_or_collection(monkeypatch):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "I want to book Speed Boat.")
    assert result.human_handover_required and result.detected_intent == "booking"
    assert not knowledge.service_calls and not knowledge.venue_calls
    lowered = result.draft_text.casefold()
    assert "date" not in lowered and "guest count" not in lowered and "sales@entartica.com" in lowered


def test_enabled_graph_technical_questions_do_not_call_service_rag(monkeypatch):
    for question in (
        "What exact engine does your Speed Boat use?",
        "Which motor is installed in the Speed Boat?",
        "What horsepower is the Speed Boat?",
        "What is the current fuel level?",
        "Who is operating Jet Ski today?",
    ):
        knowledge = _Knowledge()
        result = _process(_orchestrator(monkeypatch, knowledge), question)
        assert result.detected_intent == "unknown_entartica_fact"
        assert result.safe_metadata["topic"] == "technical_specification"
        assert not knowledge.service_calls and not knowledge.venue_calls
        assert "not confirmed" in result.draft_text.casefold()
        assert "speed boat capacity" not in result.draft_text.casefold()


def test_enabled_graph_explicit_topics_keep_only_the_requested_section(monkeypatch):
    class TopicKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            answers = {
                "duration": "The Jet Ski Ride generally lasts around 5 to 10 minutes per session.",
                "swimming": "Swimming ability is not required. All passengers are provided with mandatory high-buoyancy life jackets before boarding.",
                "inclusions": "The Daycation Package includes H2O Play Park access, a Boat House pass, and a food voucher.",
            }
            heading = "Duration" if kwargs["detail_mode"] == "duration" else "Swimming Requirement" if kwargs["detail_mode"] == "swimming" else kwargs["detail_mode"]
            return KnowledgeDraft(answers[kwargs["detail_mode"]], f"{service_code}.md", .8, False, heading, 1, f"document-{service_code}", (heading,))
    knowledge = TopicKnowledge()
    duration = _process(_orchestrator(monkeypatch, knowledge), "What is the duration of Jet Ski?")
    duration_hinglish = _process(_orchestrator(monkeypatch, knowledge), "Jet Ski kitni der ki hai?")
    swimming = _process(_orchestrator(monkeypatch, knowledge), "Is swimming required for Speed Boat?")
    swimming_hinglish = _process(_orchestrator(monkeypatch, knowledge), "Speed Boat ke liye swimming zaruri hai?")
    inclusions = _process(_orchestrator(monkeypatch, knowledge), "What is included in Daycation?")
    assert duration.draft_text.startswith("The Jet Ski Ride generally lasts")
    assert "capacity" not in duration.draft_text.casefold() and "operating" not in duration.draft_text.casefold()
    assert duration.safe_metadata["selected_section_heading"] == "Duration"
    assert duration.safe_metadata["retrieved_section_headings"] == ["Duration"]
    assert duration_hinglish.safe_metadata["topic"] == "duration" and "5 to 10 minutes" in duration_hinglish.draft_text
    assert swimming.draft_text == "No, swimming ability is not required for the Speed Boat Ride. All passengers are provided with mandatory high-buoyancy life jackets before boarding."
    assert not swimming.draft_text.startswith("Speed Boat swimming:")
    assert swimming_hinglish.safe_metadata["topic"] == "swimming"
    assert swimming_hinglish.draft_text.startswith("No,") and "high-buoyancy life jackets" in swimming_hinglish.draft_text
    assert inclusions.draft_text.count("H2O Play Park") == 1


def test_enabled_graph_current_turn_plan_never_leaks_across_sequential_services(monkeypatch):
    class SequenceKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            facts = {
                ("daycation_package", "inclusions"): ("The Daycation Package includes H2O Play Park access.", "What Is Included"),
                ("speed_boat_ride", "swimming"): ("Swimming ability is not required. All passengers are provided with mandatory high-buoyancy life jackets before boarding.", "Swimming Requirement"),
                ("jet_ski_ride", "duration"): ("The Jet Ski Ride generally lasts around 5 to 10 minutes per session.", "Duration"),
                ("staycation_combo", "overview"): ("The Staycation Combo is an approved Raipur experience.", "Overview"),
                ("speed_boat_ride", "capacity"): ("Speed Boat capacity is six guests.", "Capacity"),
            }
            text, heading = facts[(service_code, kwargs["detail_mode"])]
            return KnowledgeDraft(text, f"{service_code}.md", .8, False, heading, 1, f"document-{service_code}", (heading,))
    orchestrator = _orchestrator(monkeypatch, SequenceKnowledge())
    turns = [
        ("What is included in Daycation?", "daycation_package", "inclusions", False),
        ("Is swimming required for Speed Boat?", "speed_boat_ride", "swimming", False),
        ("What is the duration of Jet Ski?", "jet_ski_ride", "duration", False),
        ("Tell me about Staycation.", "staycation_combo", "overview", False),
        ("What is the capacity of Speed Boat?", "speed_boat_ride", "capacity", False),
        ("What is included in Daycation?", "daycation_package", "inclusions", False),
        ("Is swimming required for Speed Boat?", "speed_boat_ride", "swimming", False),
        ("What is the duration of Jet Ski?", "jet_ski_ride", "duration", False),
    ]
    for question, service_code, topic, previous in turns:
        result = _process(orchestrator, question)
        assert result.safe_metadata["service_code"] == service_code
        assert result.safe_metadata["topic"] == topic
        assert result.safe_metadata["selected_route"] == "answer_service_knowledge"
        assert result.safe_metadata["plan_consistency_repaired"] is False
        assert result.safe_metadata.get("context_service_used", False) is previous
    assert "Daycation" not in _process(orchestrator, "Is swimming required for Speed Boat?").draft_text


def test_enabled_graph_uses_previous_service_only_for_a_genuine_follow_up(monkeypatch):
    class FollowupKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            text = "The Jet Ski Ride generally lasts around 5 to 10 minutes per session." if kwargs["detail_mode"] == "duration" else "The Jet Ski Ride is an approved Raipur experience."
            heading = "Duration" if kwargs["detail_mode"] == "duration" else "Overview"
            return KnowledgeDraft(text, "jet_ski_ride.md", .8, False, heading, 1, "jet-ski", (heading,))
    orchestrator = _orchestrator(monkeypatch, FollowupKnowledge())
    _process(orchestrator, "Tell me about Jet Ski.")
    followup = _process(orchestrator, "How long is it?")
    assert followup.safe_metadata["service_code"] == "jet_ski_ride"
    assert followup.safe_metadata["topic"] == "duration"
    assert followup.safe_metadata["selected_route"] == "answer_service_knowledge"
    assert followup.safe_metadata["context_service_used"] is True


def test_enabled_graph_location_clears_current_service_topic_after_service_context(monkeypatch):
    orchestrator = _orchestrator(monkeypatch, _Knowledge())
    _process(orchestrator, "Tell me about Speed Boat.")
    location = _process(orchestrator, "What is the location?")
    assert location.detected_intent == "location"
    assert location.safe_metadata.get("service_code") is None
    assert location.safe_metadata.get("topic") is None


def test_enabled_graph_two_conversations_keep_current_turn_metadata_isolated(monkeypatch):
    class IsolatedKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            facts = {
                "speed_boat_ride": ("Swimming ability is not required. All passengers are provided with mandatory high-buoyancy life jackets before boarding.", "Swimming Requirement"),
                "jet_ski_ride": ("The Jet Ski Ride generally lasts around 5 to 10 minutes per session.", "Duration"),
            }
            text, heading = facts[service_code]
            return KnowledgeDraft(text, f"{service_code}.md", .8, False, heading, 1, service_code, (heading,))
    orchestrator = _orchestrator(monkeypatch, IsolatedKnowledge())
    speed = _process(orchestrator, "Is swimming required for Speed Boat?", customer_id="customer-a", conversation_id="conversation-a")
    jet = _process(orchestrator, "What is the duration of Jet Ski?", customer_id="customer-b", conversation_id="conversation-b")
    speed_again = _process(orchestrator, "Is swimming required for Speed Boat?", customer_id="customer-a", conversation_id="conversation-a")
    assert (speed.safe_metadata["service_code"], speed.safe_metadata["topic"]) == ("speed_boat_ride", "swimming")
    assert (jet.safe_metadata["service_code"], jet.safe_metadata["topic"]) == ("jet_ski_ride", "duration")
    assert (speed_again.safe_metadata["service_code"], speed_again.safe_metadata["topic"]) == ("speed_boat_ride", "swimming")


def test_enabled_graph_automatic_reply_eligibility_keeps_graph_selection_metadata(monkeypatch):
    class SwimmingKnowledge(_Knowledge):
        def answer_service_details(self, *_args, **_kwargs):
            return KnowledgeDraft("Swimming ability is not required. All passengers are provided with mandatory high-buoyancy life jackets before boarding.", "speed_boat_ride.md", .8, False, "Swimming Requirement", 1, "speed-boat", ("Swimming Requirement",))
    result = _process(_orchestrator(monkeypatch, SwimmingKnowledge()), "Is swimming required for Speed Boat?")
    before = dict(result.safe_metadata)
    settings = SimpleNamespace(raipur_automatic_reply_enabled=True, exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True, raipur_automatic_reply_intents=("information",))
    draft = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}
    assert eligible_for_automatic_reply(settings, result, draft)[0] is True
    assert result.safe_metadata["service_code"] == before["service_code"] == "speed_boat_ride"
    assert result.safe_metadata["topic"] == before["topic"] == "swimming"
    assert result.safe_metadata["selected_route"] == before["selected_route"] == "answer_service_knowledge"


def test_enabled_graph_end_to_end_dynamic_pipeline_keeps_routes_and_context_isolated(monkeypatch):
    class PipelineKnowledge(_Knowledge):
        def answer_service_details(self, _question, _service_name, service_code, **kwargs):
            facts = {
                ("daycation_package", "overview"): ("The Daycation Package is an approved full-day Raipur experience.", "Definition"),
                ("daycation_package", "inclusions"): ("The Daycation Package includes approved day-use access.", "What Is Typically Included"),
                ("speed_boat_ride", "swimming"): ("Swimming ability is not required. All passengers are provided with mandatory high-buoyancy life jackets before boarding.", "Swimming Requirement"),
                ("jet_ski_ride", "duration"): ("The Jet Ski Ride generally lasts around 5 to 10 minutes per session.", "Duration"),
                ("kayaking", "overview"): ("Kayaking at Entartica is an approved Raipur water activity.", "Definition"),
            }
            text, heading = facts[(service_code, kwargs["detail_mode"])]
            return KnowledgeDraft(text, f"{service_code}.md", .8, False, heading, 1, service_code, (heading,))
    orchestrator = _orchestrator(monkeypatch, PipelineKnowledge())
    expected = [
        ("Tell me about Daycation.", "answer_service_knowledge", "daycation_package", "overview"),
        ("What is included in Daycation?", "answer_service_knowledge", "daycation_package", "inclusions"),
        ("Is swimming required for Speed Boat?", "answer_service_knowledge", "speed_boat_ride", "swimming"),
        ("What is the duration of Jet Ski?", "answer_service_knowledge", "jet_ski_ride", "duration"),
        ("What is the location?", "answer_location", None, None),
        ("What rides are available?", "answer_catalogue", None, None),
        ("What is the price of Jet Ski?", "handover_to_sales", None, None),
        ("What is kayaking?", "answer_general_openai", None, None),
        ("Tell me about Kayaking at Entartica.", "answer_service_knowledge", "kayaking", "overview"),
        ("What exact engine does your Speed Boat use?", "answer_unknown_entartica_fact", "speed_boat_ride", "technical_specification"),
        ("Thank you.", "answer_greeting", None, None),
    ]
    for message, route, service, topic in expected:
        result = _process(orchestrator, message)
        assert result.safe_metadata["selected_route"] == route
        assert result.safe_metadata.get("service_code") == service
        assert result.safe_metadata.get("topic") == topic
    assert "5 to 10 minutes" in _process(orchestrator, "What is the duration of Jet Ski?").draft_text
