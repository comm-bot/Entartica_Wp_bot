from datetime import date
import asyncio
import json
from types import SimpleNamespace

import httpx

from app.rag.coimbatore_knowledge_provider import CoimbatoreEvidence
from app.services.coimbatore.customer_understanding import (
    CoimbatoreUnderstanding, CoimbatoreUnderstandingService, CustomerIntent, PackageReference,
)
from app.services.coimbatore.inbound_orchestrator import CoimbatoreInboundOrchestrator
from app.services.coimbatore.response_composer import CoimbatoreResponseComposer
from app.services.raipur.sales_state import SalesStage
from app.services.raipur_automatic_replies import eligible_for_automatic_reply
from app.services.raipur_draft_integration import create_draft_after_orchestration
from app.services.raipur_draft_sender import RaipurDraftSender
from app.integrations.exotel import ExotelClient
from tests.support.fake_outbound_drafts import FakeOutboundDraftRepository


def meaning(intent, **values):
    return CoimbatoreUnderstanding(intent=intent, confidence=.96, **values)


class Contexts:
    def __init__(self): self.record = None; self.loads = 0; self.saves = 0
    def get_service_context(self, *_): self.loads += 1; return self.record
    def save_service_context(self, _conversation, _customer, record): self.saves += 1; self.record = record; return True


class Evidence:
    def __init__(self): self.calls = []
    def retrieve_evidence(self, question, **kwargs):
        self.calls.append((question, kwargs))
        value = question.casefold()
        if "unknown" in value: return CoimbatoreEvidence((), question)
        facts = (
            "250 g cake, any available flavour. Couple package includes 2 cold pyros. "
            "The Couple Romance ride duration is 20 minutes. Pyro Gun add-on is ₹750 per gun."
        )
        if "location" in value: facts = "Entartica SeaWorld is at Periyakulam Lake Boat House, Ukkadam, Coimbatore 641001."
        return CoimbatoreEvidence(({"content": facts, "section_heading": "Approved Package Master", "location_code": "coimbatore", "confidence": .92},), question)


def interpretation(message, _context):
    value = message.casefold()
    if value == "hello": return meaning(CustomerIntent.GREETING)
    if "we are couple" in value: return meaning(CustomerIntent.QUALIFICATION_UPDATE, guest_count=2, guest_count_explicit=True, package_reference=PackageReference.CURRENT)
    if "we are 5 people" in value: return meaning(CustomerIntent.QUALIFICATION_UPDATE, guest_count=5, guest_count_explicit=True, package_reference=PackageReference.CURRENT)
    if "flavour" in value or "kind of cake" in value: return meaning(CustomerIntent.FAQ, topic="cake", attribute="flavour", package_reference=PackageReference.CURRENT)
    if "duration" in value or "how long" in value: return meaning(CustomerIntent.FAQ, topic="duration", attribute="ride_duration", package_reference=PackageReference.CURRENT)
    if "only 2 pyro" in value: return meaning(CustomerIntent.FAQ_CLARIFICATION, topic="pyro", attribute="quantity", mentioned_number=2, guest_count_explicit=False, package_reference=PackageReference.CURRENT)
    if "what is pyro" in value: return meaning(CustomerIntent.FAQ_DEFINITION, topic="pyro", attribute="meaning", package_reference=PackageReference.CURRENT)
    if "250 g" in value: return meaning(CustomerIntent.FAQ_CLARIFICATION, topic="cake", attribute="weight", mentioned_number=250)
    if "20 minutes" in value: return meaning(CustomerIntent.FAQ_CLARIFICATION, topic="duration", attribute="duration", mentioned_number=20)
    if "location" in value: return meaning(CustomerIntent.FAQ, topic="location", attribute="address")
    if "book" in value: return meaning(CustomerIntent.BOOKING, booking_intent=True, package_reference=PackageReference.CURRENT)
    if "available" in value: return meaning(CustomerIntent.AVAILABILITY, availability_intent=True, preferred_date_text="tomorrow", preferred_time_text="7pm")
    if "paid" in value: return meaning(CustomerIntent.PAYMENT, payment_intent=True)
    if "discount" in value: return meaning(CustomerIntent.DISCOUNT)
    if "birthday" in value: return meaning(CustomerIntent.OCCASION, occasion="birthday")
    if any(term in value for term in ("package", "full details", "pontoon offer")):
        return meaning(CustomerIntent.PACKAGE_DETAILS, topic="package", package_reference=PackageReference.STANDARD)
    return meaning(CustomerIntent.FAQ, topic="unsupported_fact", attribute="unknown")


def responder(brief):
    evidence = " ".join(item["content"] for item in brief.evidence)
    topic, attribute = brief.understanding.topic, brief.understanding.attribute
    if brief.business_output.get("handoff_reason") == "live_availability_unverified": return "I can't confirm that slot. Our team must verify live availability."
    if brief.business_output.get("handoff_reason") == "payment_unverified": return "I can't verify that payment. Our team will check it."
    if brief.business_output.get("handoff_reason") == "discount_requires_team": return "Discount approval needs our team. I'll connect you."
    standard = brief.state.get("active_package_id") == "coimbatore_pontoon_standard"
    if topic == "cake" and attribute == "flavour": return "The package cake can be provided in any available flavour 😊" if standard else "The included 250 g cake can be provided in any available flavour 😊"
    if topic == "cake": return "Yes, the approved evidence says the cake is 250 g."
    if topic == "duration": return "The Standard Pontoon Celebration includes a 30-minute Premium Boat Ride 😊" if standard else "The Couple Romance Celebration includes a 20-minute Pontoon ride."
    if topic == "pyro" and attribute == "quantity": return "Yes, the Couple Romance package includes 2 cold pyros for the entry."
    if topic == "pyro": return "The package includes cold-pyro entry effects. I don't have a more technical approved definition."
    if topic == "location": return evidence
    if topic == "unsupported_fact": return "I don't have an approved detail for that. Our team can clarify it."
    if brief.business_output.get("price_inr"): return f"The recommended package is ₹{brief.business_output['price_inr']:,}." + (f"\n{brief.next_question}" if brief.next_question else "")
    return "Sure 😊 We have Couple Romance and Family & Friends Pontoon packages.\nHow many guests will be joining?"


def service(*, persist=True, contexts=None, media=True):
    result = CoimbatoreInboundOrchestrator.__new__(CoimbatoreInboundOrchestrator)
    result._settings = SimpleNamespace(
        app_timezone="Asia/Kolkata", coimbatore_persist_sales_state=persist,
        coimbatore_package_media_enabled=media, public_base_url="https://book.entartica.test/",
    )
    result._context_ttl_minutes = 120
    result._contexts = contexts or Contexts()
    result._knowledge = Evidence()
    result._understanding = CoimbatoreUnderstandingService(interpretation)
    result._composer = CoimbatoreResponseComposer(responder)
    return result


def run(bot, text):
    return bot.process(SimpleNamespace(content=text), customer={"id":"customer"}, conversation={"id":"conversation"}, source_message_id="message")


def run_echt(bot, text):
    return bot.process(
        SimpleNamespace(content=text, external_provider="echt_connect"),
        customer={"id":"customer"}, conversation={"id":"conversation"},
        source_message_id="message",
    )


def test_attribute_level_cake_duration_and_new_paraphrase_use_llm_and_rag():
    bot = service(); run(bot, "we are couple")
    cake = run(bot, "what is the flavour of cake?")
    assert cake.safe_metadata["understanding_mode"] == "llm" and cake.safe_metadata["rag_used"] is True
    assert "available flavour" in cake.draft_text
    duration = run(bot, "what the duration of this package??")
    assert "30-minute" in duration.draft_text and "₹3,999" not in duration.draft_text
    paraphrase = run(bot, "What kind of cake do you guys give with this?")
    assert "available flavour" in paraphrase.draft_text


def test_fresh_package_interest_gets_full_welcome_then_auto_standard_draft():
    bot = service()
    welcome = run(bot, "i want to learn about package")
    assert welcome.draft_text == (
        "Hi 👋 Welcome to Entartica Coimbatore.\n\n"
        "I'll help you plan your Pontoon Celebration 🎉\n\n"
        "How many guests will be visiting, and what date are you planning for?\n\n"
        "💡 eg. 7 , 26/08/2026"
    )
    assert welcome.context.pending_field == "total_guests"
    package = run(bot, "05/10/2026,6")
    assert package.context.details.preferred_date == date(2026, 10, 5)
    assert package.context.details.total_guests == 6
    assert package.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert package.safe_metadata["package_presentation_pending"] is True
    interactive = package.safe_metadata["interactive_message"]
    assert interactive["kind"] == "list"
    assert [option["title"] for option in interactive["options"]] == [
        "Book Now", "Talk to Sales Person", "Customize", "See Photo & Video",
        "See Pontoon Brochure", "Check Couple Package",
    ]

    settings = SimpleNamespace(
        raipur_draft_creation_enabled=True, raipur_draft_review_migration_ready=True,
        raipur_inbound_orchestrator_enabled=True,
    )
    repository = FakeOutboundDraftRepository()
    created = create_draft_after_orchestration(
        settings=settings, inbound_message={"id":"inbound"}, customer={"id":"customer"},
        conversation={"id":"conversation"}, orchestration=package,
        repository_factory=lambda: repository,
    )
    assert created.draft_saved is True
    draft = repository.get_draft_by_id("fake-draft-1")
    assert draft["message_type"] == "interactive"
    assert draft["draft_metadata"]["interactive_message"]["header_image_url"] is None
    assert len(draft["draft_metadata"]["interactive_message"]["options"]) == 6


def test_live_guest_first_comma_date_captures_both_and_queues_complete_package():
    bot = service()
    welcome = run(bot, "hello")
    assert welcome.context.form_values["qualification_missing_fields"] == ["preferred_date", "total_guests"]
    result = run(bot, "5 , 06/10/2026")
    assert result.context.details.total_guests == 5
    assert result.context.details.preferred_date == date(2026, 10, 6)
    assert result.context.form_values["qualification_missing_fields"] == []
    assert "How many guests" not in result.draft_text
    assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert result.safe_metadata["package_presentation_pending"] is True
    assert result.context.form_values.get("standard_package_presented") is not True
    assert all(value in result.draft_text for value in (
        "Event Date: 06 Oct 2026", "Guests: 5", "~₹5,999/-~",
        "₹5,100/- (15% OFF)",
        "30 Minutes Premium Boat Ride",
    ))
    assert result.safe_metadata["interactive_message"]["header_image_url"] is None
    assert len(result.safe_metadata["interactive_message"]["options"]) == 6

    repository = FakeOutboundDraftRepository()
    created = create_draft_after_orchestration(
        settings=SimpleNamespace(raipur_draft_creation_enabled=True, raipur_draft_review_migration_ready=True,
                                 raipur_inbound_orchestrator_enabled=True),
        inbound_message={"id":"live-inbound"}, customer={"id":"customer"}, conversation={"id":"conversation"},
        orchestration=result, repository_factory=lambda: repository,
    )
    assert created.draft_saved
    draft = repository.get_draft_by_id("fake-draft-1")
    assert draft["draft_metadata"]["package_id"] == "coimbatore_pontoon_standard"
    assert draft["draft_metadata"]["package_presentation_pending"] is True
    assert draft["draft_metadata"]["interactive_message"]["header_image_url"] is None
    assert "Event Date: 06 Oct 2026" in draft["draft_metadata"]["interactive_message"]["body"]


def test_exotel_to_echt_guest_and_date_survive_orchestrator_recreation_and_send_package():
    contexts = Contexts()
    first_process = service(persist=False, contexts=contexts)
    first_process._settings.echt_connect_enabled = True

    # The native details Flow and its continuation arrive through Exotel.
    welcome = run(first_process, "Hello")
    assert "How many guests" in welcome.draft_text
    guests = run(first_process, "3")
    assert guests.context.details.total_guests == 3
    assert guests.context.pending_field == "preferred_date"

    # Simulate a later CRM callback being handled by a fresh application
    # worker. The state must come from the durable conversation context.
    later_process = service(persist=False, contexts=contexts)
    later_process._settings.echt_connect_enabled = True
    package = run_echt(later_process, "23/09/2026")

    assert package.context.details.total_guests == 3
    assert package.context.details.preferred_date == date(2026, 9, 23)
    assert package.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert package.safe_metadata["package_presentation_pending"] is True
    assert "Event Date: 23 Sep 2026" in package.draft_text
    assert "Guests: 3" in package.draft_text


def test_unexpected_reply_then_guest_past_date_and_future_date_sends_package():
    bot = service()
    welcome = run(bot, "Hello")
    assert welcome.context.pending_field == "total_guests"

    unexpected = run(bot, "???")
    assert unexpected.draft_text == "How many guests will be joining? 👥"
    assert unexpected.context.pending_field == "total_guests"

    guests = run(bot, "7")
    assert guests.draft_text == "Please share your celebration date 📅"
    assert guests.context.pending_field == "preferred_date"

    past = run(bot, "01/01/2026")
    assert "has already passed" in past.draft_text
    assert "future date" in past.draft_text
    assert past.context.details.total_guests == 7
    assert past.context.pending_field == "preferred_date"

    package = run(bot, "31/12/2026")
    assert package.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert "Event Date: 31 Dec 2026" in package.draft_text
    assert "Guests: 7" in package.draft_text


def test_two_guests_still_auto_sends_standard_unless_couple_explicitly_requested():
    bot = service()
    automatic = run(bot, "05/10/2026,2")
    assert automatic.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    explicit = run(bot, "couple package")
    assert explicit.safe_metadata["package_id"] == "coimbatore_pontoon_couple_romance"


def test_explicit_standard_package_is_canonical_media_buttons_dynamic_and_resendable():
    bot = service()
    run(bot, "hello")
    qualified = run(bot, "30/08/2026,5")
    bot.confirm_standard_package_presented(qualified, "customer", "conversation")
    for phrase in ("standard package", "5999 package", "show me 5999 package", "send standard package"):
        result = run(bot, phrase)
        metadata = result.safe_metadata
        assert metadata["package_id"] == "coimbatore_pontoon_standard"
        assert metadata["response_composer"] == "exact_kb_package_block"
        assert metadata["interactive_message"]["header_image_url"] is None
        assert metadata["interactive_message"]["kind"] == "list"
        assert [item["title"] for item in metadata["interactive_message"]["options"]] == [
            "Book Now", "Talk to Sales Person", "Customize", "See Photo & Video",
            "See Pontoon Brochure", "Check Couple Package",
        ]
        assert all(value in result.draft_text for value in (
            "~₹5,999/-~", "₹5,100/- (15% OFF)",
            "30 Minutes Premium Boat Ride",
        ))
        assert result.context.form_values.get("package_presentation_pending") is True
        automatic_settings = SimpleNamespace(
            raipur_automatic_reply_enabled=True, exotel_outbound_enabled=True,
            raipur_approved_draft_send_enabled=True,
            raipur_automatic_reply_intents=("information", "location", "services"),
        )
        draft = {"draft_status":"pending_review", "sent_at":None, "external_message_id":None}
        assert eligible_for_automatic_reply(automatic_settings, result, draft) == (True, "eligible")
    bot._contexts.record["booking_details"].update(preferred_date="2026-08-30", total_guests=5)
    dynamic = run(bot, "send full details plz")
    assert "Event Date: 30 Aug 2026" in dynamic.draft_text and "Guests: 5" in dynamic.draft_text


def test_standard_package_presented_commits_only_after_acceptance_callback():
    bot = service(); run(bot, "hello"); result = run(bot, "05/10/2026,5")
    assert result.context.form_values["package_presentation_pending"] is True
    assert result.context.form_values.get("standard_package_presented") is not True
    assert bot.confirm_standard_package_presented(result, "customer", "conversation") is True
    assert bot._contexts.record["form_values"]["standard_package_presented"] is True
    assert bot._contexts.record["form_values"]["package_presentation_pending"] is False
    assert bot._contexts.record["sales_stage"] == "package_presented"


def test_multifield_past_date_preserves_guest_and_asks_only_for_date():
    bot = service()
    result = run(bot, "10/08/2026,25")
    assert result.context.details.total_guests == 25
    assert result.context.details.preferred_date is None
    assert "noted 25 guests" in result.draft_text
    assert "already passed" in result.draft_text
    assert "future date" in result.draft_text
    assert "how many" not in result.draft_text.casefold()
    assert "duration" not in result.draft_text.casefold()


def test_pending_numeric_guest_above_ten_requests_in_capacity_correction():
    bot = service()
    partial = run(bot, "5 October")
    assert partial.context.pending_field == "total_guests"
    result = run(bot, "25")
    assert result.context.details.total_guests == 25
    assert result.context.details.preferred_date == date(2026, 10, 5)
    assert "maximum capacity" in result.draft_text
    assert "10 guests" in result.draft_text
    assert result.context.pending_field == "total_guests"
    assert result.human_handover_required is False


def test_pending_guest_words_and_phrases_bypass_llm_and_rag():
    for reply in ("6", "25", "six", "we are 6"):
        bot = service()
        partial = run(bot, "5 October")
        calls_before = len(bot._knowledge.calls)
        result = run(bot, reply)
        expected = 6 if reply != "25" else 25
        assert result.context.details.total_guests == expected
        assert len(bot._knowledge.calls) == calls_before
        assert "what does" not in result.draft_text.casefold()
        assert "20-minute" not in result.draft_text.casefold()


def test_exact_couple_package_comes_from_kb_without_invented_media():
    bot = service()
    for phrase in ("couple package", "romantic package", "3999 package", "package for 2"):
        result = run(bot, phrase)
        assert result.safe_metadata["package_id"] == "coimbatore_pontoon_couple_romance"
        assert result.safe_metadata["exact_kb_package_block"] is True
        assert result.safe_metadata["response_composer"] == "exact_kb_package_block"
        assert "Pontoon Couple Romance Celebration ❤️✨" in result.draft_text
        assert "Guests: 2" in result.draft_text
        assert "20 Minutes Private Pontoon Boat Ride" in result.draft_text
        assert "~₹3,999/-~" in result.draft_text
        assert "₹3,400/- (15% off)" in result.draft_text
        assert "media_message" not in result.safe_metadata
        assert result.safe_metadata["interactive_message"]["kind"] == "list"
        assert result.safe_metadata["interactive_message"]["options"][-1]["title"] == "Check Standard Package"


def test_active_package_context_controls_duration_and_vague_resend():
    bot = service()
    standard = run(bot, "standard package")
    bot.confirm_standard_package_presented(standard, "customer", "conversation")
    standard_duration = run(bot, "how long?")
    assert "30-minute" in standard_duration.draft_text
    resent = run(bot, "send package")
    assert resent.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    couple = run(bot, "3999 package")
    bot.confirm_standard_package_presented(couple, "customer", "conversation")
    couple_duration = run(bot, "how long?")
    assert "20-minute" in couple_duration.draft_text


def test_multifield_valid_formats_complete_and_send_exact_standard_package():
    for message in ("05/10/2026,5", "05-10-2026 5", "October 5 for 5 people"):
        bot = service()
        result = run(bot, message)
        assert result.context.details.preferred_date == date(2026, 10, 5)
        assert result.context.details.total_guests == 5
        assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
        assert result.safe_metadata["response_composer"] == "exact_kb_package_block"
        assert "Family & Friends" not in result.draft_text


def test_package_faq_does_not_resend_and_pyro_quantity_does_not_change_guests():
    bot = service()
    run(bot, "standard package")
    package = run(bot, "30/08/2026,5")
    bot.confirm_standard_package_presented(package, "customer", "conversation")
    cake = run(bot, "what is cake flavour?")
    assert "available flavour" in cake.draft_text
    assert "Rack Rate" not in cake.draft_text
    pyro = run(bot, "only 2 pyros?")
    assert pyro.context.details.total_guests == 5
    assert "Rack Rate" not in pyro.draft_text
    resent = run(bot, "send package again")
    assert resent.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert "~₹5,999/-~" in resent.draft_text
    assert "₹5,100/- (15% OFF)" in resent.draft_text


def test_standard_package_intent_beats_stale_package_and_guest_state():
    bot = service(); run(bot, "we are couple")
    bot._contexts.record["booking_details"]["total_guests"] = 25
    bot._contexts.record["form_values"]["active_package_id"] = "some_old_package"
    package = run(bot, "send me package details")
    assert package.context.details.total_guests == 25
    assert package.context.form_values["active_package_id"] == "coimbatore_pontoon_standard"
    assert "maximum capacity" in package.draft_text and "₹5,999" not in package.draft_text
    corrected = run(bot, "we are 5 people")
    assert corrected.context.details.total_guests == 5
    assert corrected.context.form_values["active_package_id"] == "coimbatore_pontoon_standard"
    pyro = run(bot, "only 2 pyro entries???")
    assert pyro.context.details.total_guests == 5


def test_bare_guest_correction_after_over_capacity_sends_package_details():
    bot = service()
    over_capacity = run(bot, "25 people, 5 September 2026")
    assert over_capacity.context.details.total_guests == 25
    assert "maximum capacity" in over_capacity.draft_text
    assert over_capacity.context.pending_field == "total_guests"
    assert over_capacity.human_handover_required is False

    corrected = run(bot, "8")

    assert corrected.context.details.total_guests == 8
    assert corrected.human_handover_required is False
    assert corrected.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert "₹7,500" in corrected.draft_text
    assert "₹6,375" in corrected.draft_text
    assert "maximum capacity" not in corrected.draft_text


def test_pyro_numbers_never_overwrite_stale_guest_count_and_definition_retrieves():
    bot = service(); first = run(bot, "we are couple")
    bot._contexts.record["booking_details"]["total_guests"] = 8
    quantity = run(bot, "only 2 pyro entries???")
    assert quantity.context.details.total_guests == 8
    assert "2 cold pyros" in quantity.draft_text
    definition = run(bot, "what is pyro entries???")
    assert definition.safe_metadata["rag_used"] is True
    assert "technical approved definition" in definition.draft_text


def test_non_guest_numbers_do_not_mutate_guest_state():
    bot = service(); run(bot, "we are couple")
    cake = run(bot, "is the cake 250 g?")
    duration = run(bot, "is duration 20 minutes?")
    assert cake.context.details.total_guests == duration.context.details.total_guests == 2


def test_current_couple_overrides_stale_25_and_persists_package_and_occasion():
    bot = service(); run(bot, "we are couple")
    bot._contexts.record["booking_details"]["total_guests"] = 25
    corrected = run(bot, "we are couple")
    assert corrected.context.details.total_guests == 2
    assert corrected.context.form_values.get("active_package_id") != "coimbatore_pontoon_couple_romance"
    assert "celebration date" in corrected.draft_text
    occasion = run(bot, "birthday")
    assert occasion.context.form_values["occasion"] == "birthday"


def test_booking_business_transition_and_live_fact_boundaries():
    bot = service(); run(bot, "we are couple")
    bot._contexts.record["booking_details"]["preferred_date"] = date(2026, 8, 30).isoformat()
    booking = run(bot, "i want to book this package")
    assert booking.context.sales_stage == SalesStage.PAYMENT_PENDING
    assert booking.context.pending_field is None
    assert "secure test payment link is not configured" in booking.draft_text
    assert "https://" not in booking.draft_text
    assert "confirmed" not in booking.draft_text.casefold()
    bot = service(); run(bot, "hello")
    availability = run(bot, "is tomorrow at 7pm available?")
    payment = run(bot, "I paid already")
    discount = run(bot, "give me 20% discount")
    assert availability.human_handover_required and "can't confirm" in availability.draft_text
    assert payment.human_handover_required and "can't verify" in payment.draft_text
    assert discount.human_handover_required and "team" in discount.draft_text


def test_unknown_fact_and_llm_failures_are_safe_and_nonblank():
    bot = service()
    welcome = run(bot, "unknown unsupported fact")
    assert "Welcome to Entartica Coimbatore" in welcome.draft_text
    unknown = run(bot, "unknown unsupported fact")
    assert "don't have an approved detail" in unknown.draft_text
    bot._composer = CoimbatoreResponseComposer(lambda _brief: (_ for _ in ()).throw(TimeoutError()))
    fallback = run(bot, "unknown unsupported fact")
    assert fallback.draft_text and "approved detail" in fallback.draft_text
    bot._understanding = CoimbatoreUnderstandingService(lambda *_: (_ for _ in ()).throw(TimeoutError()))
    deterministic = run(bot, "hello")
    assert deterministic.draft_text


def test_live_like_multi_turn_keeps_context_and_never_uses_raipur():
    bot = service()
    messages = ["hello", "can you send me details of package?", "we are couple",
                "what is the flavour of cake?", "what the duration of this package??",
                "only 2 pyro entries???", "what is pyro entries???", "what s the location?"]
    results = [run(bot, message) for message in messages]
    assert all(item.safe_metadata["raipur_retrieval_used"] is False for item in results)
    assert results[-1].context.details.total_guests == 2
    booking = run(bot, "i want to book this package")
    assert "Which date" in booking.draft_text and "confirmed" not in booking.draft_text.casefold()


def test_session_mode_ignores_stale_supabase_and_keeps_guest_date_in_process():
    contexts = Contexts()
    persistent = service(contexts=contexts)
    run(persistent, "hello")
    qualified = run(persistent, "5, 06/10/2026")
    booked = run(persistent, "Book Now")
    contexts.record = {
        **contexts.record,
        "pending_field": "preferred_time",
        "sales_stage": "interested",
    }

    bot = service(persist=False, contexts=contexts)
    welcome = run(bot, "hii")
    assert "Welcome to Entartica Coimbatore" in welcome.draft_text
    assert "preferred" not in welcome.draft_text.casefold()
    assert contexts.loads == 3  # only the prior persistent turns loaded it
    assert contexts.saves == 3
    partial = run(bot, "5")
    assert partial.context.details.total_guests == 5
    assert partial.context.details.preferred_date is None
    package = run(bot, "06/10/2026")
    assert package.context.details.total_guests == 5
    assert package.context.details.preferred_date == date(2026, 10, 6)
    assert package.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert contexts.saves == 3


def test_session_restart_reset_after_book_now_payment_link():
    contexts = Contexts()
    bot = service(persist=False, contexts=contexts)
    run(bot, "5, 06/10/2026")
    interested = run(bot, "Book Now")
    assert interested.context.pending_field is None
    assert interested.context.sales_stage == SalesStage.PAYMENT_PENDING
    assert "secure test payment link is not configured" in interested.draft_text

    reset = run(bot, "start over")
    assert reset.draft_text == (
        "Sure 😊 Let's start again.\n\n"
        "How many guests will be visiting, and what date are you planning for?\n\n"
        "💡 eg. 7 , 26/08/2026"
    )
    assert reset.context.details.total_guests is None

    restarted = service(persist=False, contexts=contexts)
    welcome = run(restarted, "hello")
    assert "Welcome to Entartica Coimbatore" in welcome.draft_text
    assert welcome.context.pending_field == "total_guests"


def test_persistent_mode_still_restores_durable_sales_state():
    contexts = Contexts()
    first = service(persist=True, contexts=contexts)
    run(first, "hello")
    partial = run(first, "5")
    assert partial.context.details.total_guests == 5
    restarted = service(persist=True, contexts=contexts)
    restored = run(restarted, "06/10/2026")
    assert restored.context.details.total_guests == 5
    assert restored.safe_metadata["package_id"] == "coimbatore_pontoon_standard"


def test_live_like_standard_package_sends_one_text_message_with_all_actions():
    bot = service(persist=False)
    welcome = run(bot, "hello")
    assert "How many guests" in welcome.draft_text
    package = run(bot, "5 , 07/10/2026")
    assert package.context.details.total_guests == 5
    assert package.context.details.preferred_date == date(2026, 10, 7)

    repository = FakeOutboundDraftRepository()
    created = create_draft_after_orchestration(
        settings=SimpleNamespace(
            raipur_draft_creation_enabled=True,
            raipur_draft_review_migration_ready=True,
            raipur_inbound_orchestrator_enabled=True,
        ),
        inbound_message={"id": "live-package-inbound"},
        customer={"id": "customer"}, conversation={"id": "conversation"},
        orchestration=package, repository_factory=lambda: repository,
    )
    assert created.draft_saved
    duplicate = create_draft_after_orchestration(
        settings=SimpleNamespace(
            raipur_draft_creation_enabled=True,
            raipur_draft_review_migration_ready=True,
            raipur_inbound_orchestrator_enabled=True,
        ),
        inbound_message={"id": "live-package-inbound"},
        customer={"id": "customer"}, conversation={"id": "conversation"},
        orchestration=package, repository_factory=lambda: repository,
    )
    assert duplicate.draft_saved is False
    assert repository.count_drafts_for_inbound_message("live-package-inbound") == 1
    draft = repository.get_draft_by_id("fake-draft-1")
    assert draft is not None and repository.approve_draft(draft["id"])

    captured = []
    def provider(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(202, json={"response":{"whatsapp":{"messages":[
            {"code":202, "status":"success", "data":{"sid":"provider-package-1"}}
        ]}}})

    exotel = ExotelClient(
        account_sid="account", api_key="key", api_token="token",
        whatsapp_from="+919900000000", transport=httpx.MockTransport(provider),
    )
    send_settings = SimpleNamespace(
        exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True,
        raipur_outbound_test_recipients=("+919000000000",),
        exotel_status_callback_url="https://example.test/status",
    )
    sent = asyncio.run(RaipurDraftSender(repository, send_settings, exotel).send(
        draft["id"], "+919000000000", confirmed=True,
    ))
    assert sent.accepted and sent.sid_recorded
    assert len(captured) == 1
    message = captured[0]["whatsapp"]["messages"][0]
    assert message["content"]["type"] == "interactive"
    interactive = message["content"]["interactive"]
    assert "header" not in interactive
    assert all(value in interactive["body"]["text"] for value in (
        "Event Date: 07 Oct 2026", "Guests: 5", "Red Carpet Welcome",
            "~₹5,999/-~", "₹5,100/- (15% OFF)",
    ))
    rows = interactive["action"]["sections"][0]["rows"]
    assert [row["title"] for row in rows] == [
        "Book Now", "Talk to Sales Person", "Customize", "See Photo & Video",
        "See Pontoon Brochure", "Check Couple Package",
    ]
    assert interactive["body"]["text"] != "What would you like to do next?"
    duplicate_send = asyncio.run(RaipurDraftSender(repository, send_settings, exotel).send(
        draft["id"], "+919000000000", confirmed=True,
    ))
    assert duplicate_send.duplicate_prevented
    assert len(captured) == 1


def test_standard_package_brochure_action_uses_durable_document_send_path():
    bot = service(persist=False)
    run(bot, "5 , 08/10/2026")
    brochure = run(bot, "See Pontoon Brochure")
    expected_url = (
        "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/"
        "Pontoon_Celebration_Brochure.pdf"
    )
    assert brochure.context.details.total_guests == 5
    assert brochure.context.details.preferred_date == date(2026, 10, 8)
    assert brochure.context.form_values["active_package_id"] == "coimbatore_pontoon_standard"
    assert brochure.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert brochure.safe_metadata["document_message"] == {
        "type": "document", "url": expected_url,
        "caption": "Pontoon Boat Celebration Brochure",
        "filename": "Pontoon-Celebration-Brochure.pdf",
    }

    repository = FakeOutboundDraftRepository()
    created = create_draft_after_orchestration(
        settings=SimpleNamespace(
            raipur_draft_creation_enabled=True,
            raipur_draft_review_migration_ready=True,
            raipur_inbound_orchestrator_enabled=True,
        ),
        inbound_message={"id": "brochure-inbound"}, customer={"id": "customer"},
        conversation={"id": "conversation"}, orchestration=brochure,
        repository_factory=lambda: repository,
    )
    assert created.draft_saved
    draft = repository.get_draft_by_id("fake-draft-1")
    assert draft["message_type"] == "document"
    assert repository.approve_draft(draft["id"])

    captured = []
    def provider(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(202, json={"response":{"whatsapp":{"messages":[
            {"code":202, "status":"success", "data":{"sid":"brochure-sid"}}
        ]}}})

    exotel = ExotelClient(
        account_sid="account", api_key="key", api_token="token",
        whatsapp_from="+919900000000", transport=httpx.MockTransport(provider),
    )
    send_settings = SimpleNamespace(
        exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True,
        raipur_outbound_test_recipients=("+919000000000",), exotel_status_callback_url=None,
    )
    sent = asyncio.run(RaipurDraftSender(repository, send_settings, exotel).send(
        draft["id"], "+919000000000", confirmed=True,
    ))
    assert sent.accepted and len(captured) == 1
    document = captured[0]["whatsapp"]["messages"][0]["content"]
    assert document == {"type": "document", "document": {
        "link": expected_url, "caption": "Pontoon Boat Celebration Brochure",
        "filename": "Pontoon-Celebration-Brochure.pdf",
    }}
