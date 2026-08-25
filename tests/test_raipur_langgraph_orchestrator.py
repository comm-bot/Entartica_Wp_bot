"""Fake-only integration coverage for the enabled LangGraph orchestrator path."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.exotel_webhook import NormalizedInboundMessage
from app.services.booking_enquiries import BookingDetails
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
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
        return [
            {"name": "Speed Boat"}, {"name": "Kayak"}, {"name": "Jet Ski"},
            {"name": "Pontoon Celebration"}, {"name": "Floating Gazebo"},
            {"name": "Jetty Gazebo"}, {"name": "Party Boat Celebration"}, {"name": "Houseboat Celebration"},
            {"name": "Staycation Combo"}, {"name": "Daycation Package"},
        ]


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


def test_default_langgraph_path_executes_representative_messages_without_legacy_service(monkeypatch):
    """Guard Phase 7: the live graph path must not construct legacy routing."""

    class _ForbiddenLegacy:
        def __init__(self, **_kwargs):
            raise AssertionError("LangGraph constructed RaipurConversationService")

    monkeypatch.setattr(module, "RaipurConversationService", _ForbiddenLegacy)
    orchestrator = _orchestrator(monkeypatch, _Knowledge())

    greeting = _process(orchestrator, "Hello")
    service = _process(orchestrator, "Tell me about Speed Boat")
    family = _process(orchestrator, "What activities can families with kids do?")
    celebration = _process(orchestrator, "I want to have a celebration")
    celebration_followup = _process(
        orchestrator, "12", context=module._context_to_record(celebration.context)
    )
    pricing = _process(orchestrator, "What is the Speed Boat price?")

    assert greeting.detected_intent == "greeting"
    assert service.safe_metadata["service_code"] == "speed_boat_ride"
    assert family.detected_intent == "family_activity_discovery"
    assert celebration.context.pending_clarification_type is None
    assert celebration.context.pending_field == "total_guests"
    assert celebration_followup.detected_intent == "celebration_guest_count"
    assert celebration_followup.context.details.total_guests == 12
    assert celebration_followup.context.pending_field == "preferred_date"
    assert pricing.detected_intent == "pricing"
    assert pricing.human_handover_required is True
    assert all(
        result.safe_metadata["active_engine"] == "langgraph"
        for result in (greeting, service, family, celebration, celebration_followup, pricing)
    )


@pytest.mark.parametrize("message", [
    "can you send me their number", "send me the number", "contact number",
    "Entartica phone number", "sales contact", "email address", "number bhejo",
    "unka number bhejo", "how can I contact you",
])
def test_enabled_graph_contact_requests_use_approved_deterministic_contact(monkeypatch, message):
    """Production-path regression test for contact routing via LangGraph."""
    from app.services.raipur.contact_handler import is_contact_information_request
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), message)
    # Verify contact handler recognizes the request
    assert is_contact_information_request(message), f"Contact handler did not recognize: {message}"
    # Verify deterministic routing
    assert result.detected_intent == "contact_information"
    assert result.safe_metadata["graph_answer_source"] == "approved_sales_contact"
    assert result.safe_metadata["response_mode"] == "direct_contact_details"
    # Verify approved contact details in response
    assert "+91 9429691418" in result.draft_text
    assert "sales@entartica.com" in result.draft_text
    # Verify no generic fallback or external references
    assert "google" not in result.draft_text.casefold()
    assert "website" not in result.draft_text.casefold()
    assert "price" not in result.draft_text.casefold()
    assert "booking confirm" not in result.draft_text.casefold()
    # Verify generic planner and fallback were not called
    assert knowledge.service_calls == [] and knowledge.venue_calls == []
    assert result.safe_metadata.get("response_basis") in {"deterministic", None}


def test_enabled_graph_pronoun_contact_request_overrides_houseboat_context(monkeypatch):
    orchestrator = _orchestrator(monkeypatch, _Knowledge())
    prior = _process(orchestrator, "Tell me about Houseboat Celebration")
    result = _process(orchestrator, "Can you send me their number?", context=prior.context)
    assert result.detected_intent == "contact_information"
    assert result.safe_metadata["graph_answer_source"] == "approved_sales_contact"
    assert "+91 9429691418" in result.draft_text
    assert "sales@entartica.com" in result.draft_text
    assert "Houseboat" not in result.draft_text


def test_enabled_graph_catalogue_uses_multiple_services_and_no_handover(monkeypatch):
    result = _process(_orchestrator(monkeypatch, _Knowledge()), "can you tell me about various rides")
    assert result.detected_intent == "activity_service_list"
    assert result.safe_metadata["active_engine"] == "langgraph"
    assert "Speed Boat" in result.draft_text and "Kayak" in result.draft_text
    assert not result.human_handover_required
    assert "visit date" not in result.draft_text.casefold() and "guest count" not in result.draft_text.casefold()
    assert result.safe_metadata["response_basis"] == "deterministic"


@pytest.mark.parametrize(
    "message,route,intent,catalogue_type",
    [
        ("what are the celebartion are there", "approved_celebration_catalogue", "celebration_service_list", "celebration"),
        ("can you provide list of all celebrations", "approved_celebration_catalogue", "celebration_service_list", "celebration"),
        ("what activities do you have", "approved_activity_catalogue", "activity_service_list", "activity"),
        ("share water activities info", "approved_activity_catalogue", "activity_service_list", "activity"),
        ("i want combo package", "approved_package_catalogue", "service_catalogue", "package"),
    ],
)
def test_enabled_graph_catalogue_requests_use_shared_approved_rows(monkeypatch, message, route, intent, catalogue_type):
    result = _process(_orchestrator(monkeypatch, _Knowledge()), message)

    assert result.detected_intent == intent
    assert result.safe_metadata["graph_answer_source"] == route
    assert result.safe_metadata["catalogue_route"] == route
    assert result.safe_metadata["shared_handler_used"] is True
    assert result.safe_metadata["catalogue_type"] == catalogue_type
    assert result.safe_metadata["catalogue_source"] == "active_raipur_services"
    assert result.safe_metadata["catalogue_item_count"] > 0
    assert not result.human_handover_required
    assert "price" not in result.draft_text.casefold()


@pytest.mark.parametrize("message", [
    "what are the activities", "activities", "rides", "what rides do you have",
    "water activities", "adventure experience", "adventure experiences",
    "kya kya activities hai", "rides batao",
])
def test_enabled_graph_activity_category_requests_never_fall_into_clarification(monkeypatch, message):
    result = _process(_orchestrator(monkeypatch, _Knowledge()), message)
    text = result.draft_text.casefold()
    assert result.detected_intent == "activity_service_list"
    assert result.safe_metadata["graph_answer_source"] == "approved_activity_catalogue"
    assert result.safe_metadata["shared_handler_used"] is True
    assert result.safe_metadata["catalogue_item_count"] > 0
    assert result.context.active_topic == "activity_catalogue"
    assert "family attractions" not in text and "facilities" not in text
    assert "price" not in text and "availability" not in text and "booking confirm" not in text


@pytest.mark.parametrize("first,followup,catalogue_type,source", [
    ("adventure experience", "give me list", "activity", "approved_activity_catalogue"),
    ("activities", "show me all", "activity", "approved_activity_catalogue"),
    ("celebrations", "send list", "celebration", "approved_celebration_catalogue"),
])
def test_enabled_graph_short_list_followup_uses_persisted_catalogue_context(monkeypatch, first, followup, catalogue_type, source):
    orchestrator = _orchestrator(monkeypatch, _Knowledge())
    initial = _process(orchestrator, first)
    result = _process(orchestrator, followup)
    assert initial.context.active_entity_name == catalogue_type
    assert result.safe_metadata["graph_answer_source"] == source
    assert result.safe_metadata["catalogue_type"] == catalogue_type
    assert result.context.active_entity_name == catalogue_type
    assert result.safe_metadata["catalogue_item_count"] > 0


def test_enabled_graph_explicit_facilities_does_not_offer_unsupported_categories(monkeypatch):
    result = _process(_orchestrator(monkeypatch, _Knowledge()), "facilities")
    assert result.detected_intent == "venue_facility"
    assert "not confirmed" in result.draft_text.casefold()
    assert "family attractions" not in result.draft_text.casefold()
    assert "adventure experiences" not in result.draft_text.casefold()


def test_enabled_graph_birthday_enquiry_lists_only_approved_celebration_options(monkeypatch):
    result = _process(_orchestrator(monkeypatch, _Knowledge()), "I want to celebrate birthday party there")

    assert result.detected_intent == "celebration_service_list"
    assert result.safe_metadata["catalogue_type"] == "celebration"
    for name in ("Floating Gazebo", "Jetty Gazebo", "Pontoon Celebration", "Party Boat Celebration", "Houseboat Celebration"):
        assert name in result.draft_text
    assert "Jet Ski" not in result.draft_text
    assert "confirmed booking" not in result.draft_text.casefold()


def test_enabled_graph_houseboat_exact_topics_and_followups_keep_context(monkeypatch):
    class HouseboatKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            answers = {
                "overview": ("Houseboat Celebration is a private floating experience.", "Definition"),
                "suitable_for": ("Couples and intimate groups are suitable for the Houseboat Celebration. Participation is subject to safety requirements and staff assessment.", "Suitable For"),
                "inclusions": ("Confirmed: Private houseboat use and captain navigation. Optional Add-Ons: Food and decoration require confirmation.", "Celebration Inclusions"),
            }
            text, heading = answers[kwargs["detail_mode"]]
            return KnowledgeDraft(text, "houseboat_celebration.md", .8, False, heading, 1, "houseboat-document", (heading,))
    knowledge = HouseboatKnowledge()
    orchestrator = _orchestrator(monkeypatch, knowledge)
    _process(orchestrator, "Tell me about Houseboat Celebration")
    suitable = _process(orchestrator, "Who is it suitable for?")
    inclusions = _process(orchestrator, "What is included?")

    assert suitable.safe_metadata["service_code"] == "houseboat_celebration"
    assert suitable.safe_metadata["topic"] == "suitable_for"
    assert suitable.safe_metadata["selected_section_heading"] == "Suitable For"
    assert "Couples" in suitable.draft_text and "exact information is not confirmed" not in suitable.draft_text.casefold()
    assert inclusions.safe_metadata["service_code"] == "houseboat_celebration"
    assert inclusions.safe_metadata["topic"] == "inclusions"
    assert inclusions.safe_metadata["selected_section_heading"] == "Celebration Inclusions"
    assert "Optional Add-Ons" in inclusions.draft_text


def test_enabled_graph_location_overrides_stale_service_context(monkeypatch):
    context = ConversationContext(BookingDetails(None, None, None, None, None, None, None), last_service_name="Speed Boat", last_service_code="speed_boat_ride")
    result = _process(_orchestrator(monkeypatch, _Knowledge()), "What is the location of Raipur?", context)
    assert result.detected_intent == "location" and result.context.last_service_code is None
    assert "Sector 24" in result.draft_text and not result.human_handover_required


def test_enabled_graph_contextual_hinglish_capacity_uses_active_service(monkeypatch):
    class BumperKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            return KnowledgeDraft(
                "Adult Bumper Boats typically offer single-seater and twin-seater options. Kids Bumper Boats typically accommodate one child per boat. Current capacity must be confirmed before booking.",
                "bumper_boat.md", .8, False, "Capacity", 1, "document-bumper", ("Capacity",),
            )
    knowledge = BumperKnowledge()
    # Production reloads the prior turn through the persisted conversation
    # record; omit an injected object to exercise that same path.
    orchestrator = _orchestrator(monkeypatch, knowledge)
    selected = _process(orchestrator, "Tell me about Bumper Boat.")
    result = _process(orchestrator, "kitna log aa sakte hain isme?")
    assert result.detected_intent in {"service_topic", "contextual_service_followup"}
    assert result.safe_metadata["service_code"] == "bumper_boat"
    assert result.safe_metadata["topic"] == "capacity"
    assert knowledge.service_calls[-1][1:] == ("Bumper Boat", "bumper_boat", "capacity")
    assert "single-seater and twin-seater" in result.draft_text
    assert not result.human_handover_required


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
    assert swimming.draft_text.startswith("*Swimming Requirement*")
    assert "No, swimming ability is not required for the Speed Boat Ride." in swimming.draft_text
    assert "mandatory high-buoyancy life jackets" in swimming.draft_text
    assert not swimming.draft_text.startswith("Speed Boat swimming:")
    assert swimming_hinglish.safe_metadata["topic"] == "swimming"
    assert swimming_hinglish.draft_text.startswith("*Swimming Requirement*")
    assert "No, swimming ability is not required" in swimming_hinglish.draft_text
    assert "high-buoyancy life jackets" in swimming_hinglish.draft_text
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
        ("What is kayaking?", "answer_service_knowledge", "kayaking", "overview"),
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


def test_enabled_graph_acknowledgement_preserves_houseboat_context_for_inclusions(monkeypatch):
    class HouseboatKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            answers = {
                "overview": ("Houseboat Celebration is a private floating experience.", "Definition"),
                "inclusions": ("Confirmed: Private houseboat use and captain navigation. Optional Add-Ons: Food and decoration require confirmation.", "Celebration Inclusions"),
            }
            text, heading = answers[kwargs["detail_mode"]]
            return KnowledgeDraft(text, "houseboat_celebration.md", .8, False, heading, 1, "houseboat-document", (heading,))
    knowledge = HouseboatKnowledge()
    orchestrator = _orchestrator(monkeypatch, knowledge)
    first = _process(orchestrator, "Tell me about Houseboat Celebration")
    thanks = _process(orchestrator, "Thank you")
    third = _process(orchestrator, "What is included?")

    assert first.safe_metadata["service_code"] == "houseboat_celebration"
    assert first.safe_metadata["topic"] == "overview"

    assert thanks.detected_intent == "greeting"
    assert thanks.safe_metadata["selected_route"] == "answer_greeting"
    assert thanks.context.last_service_code == "houseboat_celebration"
    assert thanks.context.last_service_name == "Houseboat Celebration"
    assert "welcome" in thanks.draft_text.casefold()

    assert third.safe_metadata["service_code"] == "houseboat_celebration"
    assert third.safe_metadata["topic"] == "inclusions"
    assert third.safe_metadata["selected_route"] == "answer_service_knowledge"
    assert "Confirmed" in third.draft_text and "Optional Add-Ons" in third.draft_text
    assert "exact information is not confirmed" not in third.draft_text.casefold()


def test_enabled_graph_acknowledgement_preserves_jet_ski_duration_followup(monkeypatch):
    class JetSkiKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            text = ("The Jet Ski Ride generally lasts around 5 to 10 minutes per session." if kwargs["detail_mode"] == "duration" else "The Jet Ski Ride is an approved Raipur water-ride experience.")
            heading = "Duration" if kwargs["detail_mode"] == "duration" else "Overview"
            return KnowledgeDraft(text, "jet_ski_ride.md", .8, False, heading, 1, "jet-ski", (heading,))
    knowledge = JetSkiKnowledge()
    orchestrator = _orchestrator(monkeypatch, knowledge)
    _process(orchestrator, "Tell me about Jet Ski")
    thanks = _process(orchestrator, "Thanks")
    followup = _process(orchestrator, "How long is it?")

    assert thanks.context.last_service_code == "jet_ski_ride"
    assert followup.safe_metadata["service_code"] == "jet_ski_ride"
    assert followup.safe_metadata["topic"] == "duration"
    assert followup.safe_metadata["selected_route"] == "answer_service_knowledge"
    assert "5 to 10 minutes" in followup.draft_text
    assert "exact information is not confirmed" not in followup.draft_text.casefold()


def test_enabled_graph_acknowledgement_then_explicit_switch_replaces_service(monkeypatch):
    class SwitchKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            facts = {
                ("jet_ski_ride", "overview"): ("The Jet Ski Ride is an approved Raipur water-ride experience.", "Overview"),
                ("water_bike", "overview"): ("The Water Bike is an approved Raipur water-ride experience.", "Overview"),
                ("water_bike", "duration"): ("This activity is included in H2O Playpark full-day access from 10:00 AM to 6:30 PM. The access window does not mean one continuous activity session. Individual turn or session duration is not separately confirmed.", "Duration"),
            }
            text, heading = facts[(service_code, kwargs["detail_mode"])]
            return KnowledgeDraft(text, f"{service_code}.md", .8, False, heading, 1, service_code, (heading,))
    orchestrator = _orchestrator(monkeypatch, SwitchKnowledge())
    _process(orchestrator, "Tell me about Jet Ski")
    _process(orchestrator, "Thanks")
    switched = _process(orchestrator, "Tell me about Water Bike")
    followup = _process(orchestrator, "How long is it?")

    assert switched.safe_metadata["service_code"] == "water_bike"
    assert switched.safe_metadata["topic"] == "overview"
    assert followup.safe_metadata["service_code"] == "water_bike"
    assert followup.safe_metadata["topic"] == "duration"
    assert "full-day access" in followup.draft_text
    assert "5 to 10 minutes" not in followup.draft_text
    assert "Jet Ski" not in followup.draft_text


def test_enabled_graph_acknowledgement_without_prior_service_is_safe(monkeypatch):
    orchestrator = _orchestrator(monkeypatch, _Knowledge())
    thanks = _process(orchestrator, "Thank you")
    followup = _process(orchestrator, "What is included?")

    assert thanks.detected_intent == "greeting"
    assert thanks.context.last_service_code is None
    assert followup.context.last_service_code is None
    assert followup.draft_text.strip()


def test_enabled_graph_h2o_duration_answer_uses_duration_knowledge(monkeypatch):
    class H2OKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            if kwargs["detail_mode"] == "duration":
                text = ("This activity is included in H2O Playpark full-day access from 10:00 AM to 6:30 PM. "
                        "The access window does not mean one continuous activity session. "
                        "Individual turn or session duration is not separately confirmed.")
                heading = "Duration"
            else:
                text = "H2O Playpark access is available from 10:00 AM to 6:30 PM, subject to weather and operational conditions."
                heading = "Operating Hours"
            return KnowledgeDraft(text, f"{service_code}.md", .8, False, heading, 1, f"document-{service_code}", (heading,))
    knowledge = H2OKnowledge()
    orchestrator = _orchestrator(monkeypatch, knowledge)
    en = _process(orchestrator, "What is the duration of Water Bike?")
    hinglish = _process(orchestrator, "Water Bike kitni der ki hai?")
    timing = _process(orchestrator, "What are the Water Bike timings?")

    assert en.safe_metadata["service_code"] == "water_bike"
    assert en.safe_metadata["topic"] == "duration"
    assert en.safe_metadata["selected_section_heading"] == "Duration"
    assert "full-day access" in en.draft_text and "does not mean" not in en.draft_text
    assert "not separately confirmed" not in en.draft_text
    assert "5 to 10 minutes" not in en.draft_text
    assert hinglish.safe_metadata["topic"] == "duration" and "full-day access" in hinglish.draft_text
    assert timing.safe_metadata["topic"] == "operating_hours"
    assert timing.safe_metadata["selected_section_heading"] == "Operating Hours"
    assert "10:00 AM to 6:30 PM" in timing.draft_text
    assert "full-day access" not in timing.draft_text


def test_enabled_graph_celebration_timing_uses_operating_hours_knowledge(monkeypatch):
    class PartyBoatKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            return KnowledgeDraft(
                "Celebration services operate from 10:00 AM to 9:00 PM, subject to weather and operational conditions.",
                "party_boat_celebration.md", .8, False, "Operating Hours", 1, "document-party-boat", ("Operating Hours",),
            )
    knowledge = PartyBoatKnowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), "What are the Party Boat Celebration timings?")
    assert result.safe_metadata["service_code"] == "party_boat_celebration"
    assert result.safe_metadata["topic"] == "operating_hours"
    assert result.safe_metadata["selected_section_heading"] == "Operating Hours"
    assert "10:00 AM to 9:00 PM" in result.draft_text


def test_enabled_graph_venue_level_duration_and_timing_are_deterministic(monkeypatch):
    knowledge = _Knowledge()
    orchestrator = _orchestrator(monkeypatch, knowledge)
    duration = _process(orchestrator, "How long do the water rides last?")
    timing = _process(orchestrator, "What are the ride timings?")

    assert duration.detected_intent == "venue_duration_timing"
    assert duration.safe_metadata.get("service_code") is None
    assert duration.safe_metadata["topic"] == "duration"
    assert duration.safe_metadata["selected_route"] == "answer_venue_knowledge"
    assert "One-Time" in duration.draft_text and "H2O Playpark" in duration.draft_text
    assert "5 to 10 minutes" in duration.draft_text

    assert timing.detected_intent == "venue_duration_timing"
    assert timing.safe_metadata.get("service_code") is None
    assert timing.safe_metadata["topic"] == "operating_hours"
    assert "10:00 AM" in timing.draft_text and "9:00 PM" in timing.draft_text

    assert not knowledge.service_calls and not knowledge.venue_calls
    assert not duration.human_handover_required and not timing.human_handover_required


def test_enabled_graph_venue_level_duration_overrides_stale_service_context(monkeypatch):
    orchestrator = _orchestrator(monkeypatch, _Knowledge())
    prior = _process(orchestrator, "Tell me about Jet Ski")
    result = _process(orchestrator, "How long do the water rides last?", context=prior.context)
    assert result.detected_intent == "venue_duration_timing"
    assert result.safe_metadata.get("service_code") is None
    assert result.safe_metadata["topic"] == "duration"
    assert result.safe_metadata.get("use_previous_service", False) is False
    assert "One-Time" in result.draft_text


@pytest.mark.parametrize("message", [
    "what is the opening hours of raipur?",
    "what is the timing of raipur?",
])
def test_enabled_graph_general_operating_hours_questions_use_deterministic_venue_answer(monkeypatch, message):
    knowledge = _Knowledge()
    result = _process(_orchestrator(monkeypatch, knowledge), message)

    assert result.detected_intent == "venue_duration_timing"
    assert result.safe_metadata.get("service_code") is None
    assert result.safe_metadata["topic"] == "operating_hours"
    assert result.safe_metadata["selected_route"] == "answer_venue_knowledge"
    assert result.safe_metadata["response_basis"] == "deterministic"
    assert result.safe_metadata["answer_source"] == "venue_duration_timing"
    assert "10:00 AM to 6:30 PM" in result.draft_text
    assert "10:00 AM to 9:00 PM" in result.draft_text
    assert "2:00 PM to 6:00 PM" in result.draft_text
    assert "2:00 PM to 12:00 PM the next day" in result.draft_text
    assert "weather and operational conditions" in result.draft_text
    assert not knowledge.service_calls and not knowledge.venue_calls
    assert not result.human_handover_required


def test_enabled_graph_venue_timing_confirmation_followup_uses_deterministic_answer(monkeypatch):
    orchestrator = _orchestrator(monkeypatch, _Knowledge())
    first = _process(orchestrator, "what is the timing of raipur?")
    result = _process(orchestrator, "isnt it 10 AM to 6:30 PM")

    assert first.detected_intent == "venue_duration_timing"
    assert result.detected_intent == "venue_timing_confirmation"
    assert result.safe_metadata.get("service_code") is None
    assert result.safe_metadata["topic"] == "operating_hours"
    assert result.safe_metadata["selected_route"] == "answer_venue_knowledge"
    assert result.safe_metadata["answer_source"] == "venue_timing_confirmation"
    assert "Yes" in result.draft_text
    assert "10:00 AM to 6:30 PM" in result.draft_text
    assert "2:00 PM to 6:00 PM" in result.draft_text
    assert "2:00 PM to 12:00 PM the next day" in result.draft_text
    assert not result.human_handover_required


def test_enabled_graph_general_timing_question_overrides_stale_service_context(monkeypatch):
    orchestrator = _orchestrator(monkeypatch, _Knowledge())
    prior = _process(orchestrator, "Tell me about Jet Ski")
    result = _process(orchestrator, "what is the opening hours of raipur?", context=prior.context)
    assert result.detected_intent == "venue_duration_timing"
    assert result.safe_metadata.get("service_code") is None
    assert result.safe_metadata["topic"] == "operating_hours"
    assert result.safe_metadata.get("use_previous_service", False) is False
    assert "2:00 PM to 6:00 PM" in result.draft_text


def test_enabled_graph_service_timing_and_duration_questions_stay_service_specific(monkeypatch):
    class TimingKnowledge(_Knowledge):
        def answer_service_details(self, question, service_name, service_code, **kwargs):
            self.service_calls.append((question, service_name, service_code, kwargs.get("detail_mode")))
            facts = {
                ("party_boat_celebration", "operating_hours"): "Celebration services operate from 10:00 AM to 9:00 PM, subject to weather and operational conditions.",
                ("jet_ski_ride", "operating_hours"): "Water sports and ride activities generally operate between 10:00 AM and 6:30 PM, subject to weather and operational conditions.",
                ("kayaking", "operating_hours"): "H2O Playpark access is available from 10:00 AM to 6:30 PM, subject to weather and operational conditions.",
                ("daycation_package", "operating_hours"): "The Daycation Package is available from 2:00 PM to 6:00 PM.",
                ("staycation_combo", "operating_hours"): "The Staycation Package is available from 2:00 PM to 12:00 PM the next day.",
                ("party_boat_celebration", "duration"): "The Party Boat Celebration has a starting duration of 2 hours, subject to confirmation.",
                ("houseboat_celebration", "duration"): "The Houseboat Celebration has a starting duration of 30 minutes, subject to confirmation.",
            }
            text = facts[(service_code, kwargs["detail_mode"])]
            heading = "Operating Hours" if kwargs["detail_mode"] == "operating_hours" else "Duration"
            return KnowledgeDraft(text, f"{service_code}.md", .8, False, heading, 1, service_code, (heading,))

    knowledge = TimingKnowledge()
    orchestrator = _orchestrator(monkeypatch, knowledge)
    cases = [
        ("What are the Party Boat timings?", "party_boat_celebration", "operating_hours", "10:00 AM to 9:00 PM"),
        ("What are the Jet Ski timings?", "jet_ski_ride", "operating_hours", "10:00 AM and 6:30 PM"),
        ("What are the Kayak timings?", "kayaking", "operating_hours", "10:00 AM to 6:30 PM"),
        ("What is the Daycation timing?", "daycation_package", "operating_hours", "2:00 PM to 6:00 PM"),
        ("What is the Staycation timing?", "staycation_combo", "operating_hours", "2:00 PM to 12:00 PM the next day"),
        ("What is the duration of Party Boat?", "party_boat_celebration", "duration", "2 hours"),
        ("What is the duration of Houseboat?", "houseboat_celebration", "duration", "30 minutes"),
    ]
    for message, service_code, topic, expected in cases:
        result = _process(orchestrator, message)
        assert result.safe_metadata["service_code"] == service_code
        assert result.safe_metadata["topic"] == topic
        assert result.safe_metadata["selected_route"] == "answer_service_knowledge"
        assert expected in result.draft_text
    assert not knowledge.venue_calls
