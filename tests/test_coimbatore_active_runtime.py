from datetime import date
from types import SimpleNamespace

import pytest

from app.api import exotel_webhook
from app.services.coimbatore.inbound_orchestrator import CoimbatoreInboundOrchestrator
from app.services.coimbatore.pontoon_qualification import FIRST_MESSAGE
from app.services.raipur.sales_state import SalesStage
from app.services.raipur_automatic_replies import attempt_automatic_reply, eligible_for_automatic_reply
from app.services.raipur_draft_sender import ApprovedDraftSendResult
import asyncio
from app.rag.coimbatore_knowledge_provider import compose_approved_answer, recommended_package, resolve_topic


class Contexts:
    def __init__(self):
        self.record = None
        self.saves = 0

    def get_service_context(self, _conversation_id, _customer_id):
        return self.record

    def save_service_context(self, _conversation_id, _customer_id, record):
        self.record = record
        self.saves += 1
        return True


def orchestrator() -> tuple[CoimbatoreInboundOrchestrator, Contexts]:
    service = CoimbatoreInboundOrchestrator.__new__(CoimbatoreInboundOrchestrator)
    service._settings = SimpleNamespace(app_timezone="Asia/Kolkata", public_base_url="https://book.entartica.test/")
    service._context_ttl_minutes = 120
    contexts = Contexts()
    service._contexts = contexts
    class Knowledge:
        def answer(self, question, *, guest_count=None, package_id=None):
            topic = resolve_topic(question)
            return compose_approved_answer(topic, guest_count=guest_count, package_id=package_id) if topic else None
    service._knowledge = Knowledge()
    return service, contexts


def run(service, text):
    return service.process(
        SimpleNamespace(content=text), customer={"id": "customer"},
        conversation={"id": "conversation"}, source_message_id="message",
    )


def confirm_package(service, result):
    record = service._contexts.record
    values = dict(record.get("form_values") or {})
    values["standard_package_presented"] = True
    record["form_values"] = values
    record["sales_stage"] = "package_presented"


@pytest.mark.parametrize("text", ["Hi", "Raipur", "asdfgh"])
def test_every_fresh_message_enters_coimbatore_without_selectors(text):
    service, contexts = orchestrator()
    result = run(service, text)
    assert result.draft_text == FIRST_MESSAGE
    assert result.context.selected_location == "coimbatore"
    assert result.context.last_service_code == "pontoon_celebration"
    assert result.context.sales_stage == SalesStage.LEAD
    assert result.safe_metadata["raipur_retrieval_used"] is False
    assert "select" not in result.draft_text.casefold()
    assert contexts.saves == 1


def test_first_message_fields_are_parsed_and_persisted():
    service, contexts = orchestrator()
    result = run(service, "30 August, 5 people")
    assert result.context.details.preferred_date == date(2026, 8, 30)
    assert result.context.details.total_guests == 5
    assert result.context.sales_stage == SalesStage.QUALIFIED
    assert "Pontoon Boat Celebration Package" in result.draft_text
    assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert result.safe_metadata["exact_kb_package_block"] is True
    assert contexts.record["booking_details"]["preferred_date"] == "2026-08-30"
    assert contexts.record["booking_details"]["total_guests"] == 5
    assert contexts.record["form_values"]["active_package_id"] == "coimbatore_pontoon_standard"
    automatic_settings = SimpleNamespace(
        raipur_automatic_reply_enabled=True, exotel_outbound_enabled=True,
        raipur_approved_draft_send_enabled=True,
        raipur_automatic_reply_intents=("information", "location", "services"),
    )
    draft = {"draft_status": "pending_review", "sent_at": None, "external_message_id": None}
    assert eligible_for_automatic_reply(automatic_settings, result, draft) == (True, "eligible")


@pytest.mark.parametrize(
    "message",
    ["7 and 29/08/2026", "7, 29/08/2026", "7 . 29/08/2026"],
)
def test_combined_guest_and_date_accept_common_customer_separators(message):
    service, _contexts = orchestrator()
    result = run(service, message)
    assert result.context.details.total_guests == 7
    assert result.context.details.preferred_date == date(2026, 8, 29)
    assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert "₹7,500" in result.draft_text
    assert "₹6,375" in result.draft_text


def test_exact_guest_and_short_month_date_presents_package():
    service, _contexts = orchestrator()
    result = run(service, "2 guest and 26 aug")
    assert result.context.details.total_guests == 2
    assert result.context.details.preferred_date == date(2026, 8, 26)
    assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert "₹5,999" in result.draft_text
    assert "₹5,100" in result.draft_text


def test_unknown_second_step_sends_default_standard_package():
    service, _contexts = orchestrator()
    welcome = run(service, "Hi")
    assert welcome.draft_text == FIRST_MESSAGE
    result = run(service, "not sure what to write")
    assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert result.safe_metadata["default_package_fallback"] is True
    assert result.safe_metadata["default_pricing_slab"] == "up_to_6"
    assert result.context.details.total_guests is None
    assert result.context.details.preferred_date is None
    assert "Guests:" not in result.draft_text
    assert "Event Date:" not in result.draft_text
    assert "₹5,999" in result.draft_text
    assert "₹5,100" in result.draft_text


@pytest.mark.parametrize(
    "message",
    ["7 people, date is not decided", "7 guests and we are not sure about the date", "7 people, no date yet"],
)
def test_undecided_date_still_presents_guest_priced_package(message):
    service, _contexts = orchestrator()
    result = run(service, message)
    assert result.context.details.total_guests == 7
    assert result.context.details.preferred_date is None
    assert result.context.form_values["date_undecided"] is True
    assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert "Event Date:" not in result.draft_text
    assert "₹7,500" in result.draft_text
    assert "₹6,375" in result.draft_text


def test_book_now_after_undecided_date_requests_date_before_payment():
    service, _contexts = orchestrator()
    offered = run(service, "7 guests, still not decided the date")
    confirm_package(service, offered)
    booking = run(service, "Book Now")
    assert booking.reason_code == "coimbatore_booking_date_required"
    assert booking.context.pending_field == "preferred_date"
    assert booking.safe_metadata["booking_allowed"] is False
    assert "share your celebration date" in booking.draft_text


def test_existing_state_survives_and_corrections_preserve_other_field():
    service, _contexts = orchestrator()
    first = run(service, "30 August, 5 people")
    second = run(service, "hello")
    assert second.context.details.preferred_date == first.context.details.preferred_date
    assert second.context.details.total_guests == first.context.details.total_guests
    assert second.draft_text != FIRST_MESSAGE
    changed = run(service, "actually 8 people")
    assert changed.context.details.preferred_date == date(2026, 8, 30)
    assert changed.context.details.total_guests == 8
    changed_date = run(service, "change date to 31 August")
    assert changed_date.context.details.preferred_date == date(2026, 8, 31)
    assert changed_date.context.details.total_guests == 8


@pytest.mark.parametrize(
    "message",
    [
        "I want to know about the package",
        "package information",
    ],
)
def test_returning_customer_package_phrases_resend_saved_appropriate_package(message):
    first, contexts = orchestrator()
    offered = run(first, "7 people and 5 september")
    confirm_package(first, offered)

    returning, _unused = orchestrator()
    returning._contexts = contexts
    result = run(returning, message)

    assert result.context.details.total_guests == 7
    assert result.context.details.preferred_date == date(2026, 9, 5)
    assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert "Guests: 7" in result.draft_text
    assert "₹7,500" in result.draft_text
    assert "₹6,375" in result.draft_text


@pytest.mark.parametrize(
    "message",
    [
        "I want to celebrate",
        "celebration package",
        "planning a celebration",
        "i want to celebrate birthday",
    ],
)
def test_returning_interested_customer_celebration_intent_gets_default_package_with_actions(message):
    service, contexts = orchestrator()
    offered = run(service, "20 people and 5 september")
    record = contexts.record
    record["sales_stage"] = "interested"
    record["booking_details"]["preferred_time"] = "18:00:00"

    result = run(service, message)

    assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert result.safe_metadata["default_package_fallback"] is True
    assert result.safe_metadata["interactive_message"]["kind"] == "list"
    assert len(result.safe_metadata["interactive_message"]["options"]) == 6
    assert result.context.details.total_guests == 20
    assert result.context.details.preferred_date == date(2026, 9, 5)
    assert "Guests:" not in result.draft_text
    assert "Event Date:" not in result.draft_text
    assert "₹5,999" in result.draft_text
    assert "₹5,100" in result.draft_text


def test_live_factory_never_constructs_raipur_or_knowledge(monkeypatch):
    client = object()
    settings = SimpleNamespace(active_location="coimbatore")
    monkeypatch.setattr(exotel_webhook, "get_supabase_client", lambda: client)
    monkeypatch.setattr(exotel_webhook, "get_settings", lambda: settings)
    monkeypatch.setattr(exotel_webhook, "RaipurInboundOrchestrator", lambda *_a, **_k: pytest.fail("Raipur runtime used"))
    exotel_webhook.get_raipur_inbound_orchestrator.cache_clear()
    result = exotel_webhook.get_raipur_inbound_orchestrator()
    assert isinstance(result, CoimbatoreInboundOrchestrator)
    exotel_webhook.get_raipur_inbound_orchestrator.cache_clear()


def test_coimbatore_has_strict_no_knowledge_boundary():
    service, _contexts = orchestrator()
    result = run(service, "What are the timings and price?")
    assert result.safe_metadata["knowledge_location"] == "coimbatore"
    assert result.safe_metadata["raipur_retrieval_used"] is False
    assert "how many guests will be visiting" in result.draft_text.casefold()
    assert result.safe_metadata["response_basis"] == "deterministic"


def test_package_actions_preserve_qualification_state():
    service, _contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    photos = run(service, "show more photos")
    assert photos.draft_text.startswith("Here are the approved Pontoon Celebration photos and video")
    assert [item["type"] for item in photos.safe_metadata["media_sequence"]] == ["image", "image", "video"]
    assert photos.safe_metadata["media_sequence"][0]["url"].endswith("pontoon_standard_package_coimbatore.jpeg")
    assert photos.safe_metadata["post_media_cta"] is True
    assert [option["title"] for option in photos.safe_metadata["interactive_message"]["options"]] == [
        "Book Now", "Customize", "Ask a Question",
    ]
    assert all("photo" not in option["title"].casefold() for option in photos.safe_metadata["interactive_message"]["options"])
    assert photos.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert photos.context.details.total_guests == 5
    booked = run(service, "I want this")
    assert booked.context.sales_stage == SalesStage.PAYMENT_PENDING
    assert booked.context.details.preferred_date == date(2026, 8, 30)
    assert "secure test payment link is not configured" in booked.draft_text
    assert "https://" not in booked.draft_text
    assert "confirmed" not in booked.draft_text.casefold()


def test_standard_package_can_open_couple_package_in_same_interactive_layout():
    service, _contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)

    couple = run(service, "coimbatore_pontoon_check_couple")

    assert couple.safe_metadata["package_id"] == "coimbatore_pontoon_couple_romance"
    assert couple.draft_text.startswith("Pontoon Couple Romance Celebration")
    assert "Event Date: 30 Aug 2026" in couple.draft_text
    assert "Guests: 2" in couple.draft_text
    assert "~₹3,999/-~" in couple.draft_text
    assert "₹3,400/- (15% off)" in couple.draft_text
    interactive = couple.safe_metadata["interactive_message"]
    assert interactive["kind"] == "list"
    assert [option["title"] for option in interactive["options"]] == [
        "Book Now", "Ask a Question", "Customize", "See Photo & Video", "Check Standard Package",
    ]
    assert couple.context.form_values["active_package_id"] == "coimbatore_pontoon_couple_romance"
    settings = SimpleNamespace(
        raipur_automatic_reply_enabled=True,
        exotel_outbound_enabled=True,
        raipur_approved_draft_send_enabled=True,
        raipur_automatic_reply_intents=("information",),
    )
    draft = {"draft_status": "pending_review", "sent_at": None, "external_message_id": None}
    assert eligible_for_automatic_reply(settings, couple, draft) == (True, "eligible")

    standard = run(service, "coimbatore_pontoon_check_standard")
    assert standard.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert "~₹5,999/-~" in standard.draft_text
    assert "₹5,100/- (15% OFF)" in standard.draft_text
    assert standard.safe_metadata["interactive_message"]["options"][-1]["title"] == "Check Couple Package"


def test_couple_photo_action_sends_basic_decor_photo_and_video_only():
    service, _contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    couple = run(service, "coimbatore_pontoon_check_couple")
    assert couple.context.form_values["active_package_id"] == "coimbatore_pontoon_couple_romance"

    media = run(service, "See Photo & Video")

    assert media.draft_text == "Here are the approved Couple Romance photos and video 😊"
    assert media.safe_metadata["media_sequence"] == [
        {
            "type": "image",
            "url": "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/pontoon_coimbatore_basic_decor.jpeg",
            "caption": "Couple Romance photo",
        },
        {
            "type": "image",
            "url": "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/Pbc_Coi_couple_package.jpeg",
            "caption": "Couple Romance photo",
        },
        {
            "type": "video",
            "url": "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/pontoon_boat_celebration_video_coimbatore.mp4",
            "caption": "Couple Romance video",
        },
    ]
    assert media.safe_metadata["package_id"] == "coimbatore_pontoon_couple_romance"
    assert media.safe_metadata["interactive_message"]["kind"] == "buttons"
    assert [option["title"] for option in media.safe_metadata["interactive_message"]["options"]] == [
        "Book Now", "Customize", "Ask a Question",
    ]

    booked = run(service, "Book Now")
    assert booked.safe_metadata["package_id"] == "coimbatore_pontoon_couple_romance"
    assert "/pay/coimbatore/couple-romance" in booked.draft_text


def test_post_media_customize_and_question_preserve_active_package_context():
    for package_id in ("coimbatore_pontoon_standard", "coimbatore_pontoon_couple_romance"):
        service, _contexts = orchestrator()
        offered = run(service, "30 August, 5 people")
        confirm_package(service, offered)
        if package_id.endswith("couple_romance"):
            run(service, "Check Couple Package")
        run(service, "See Photo & Video")

        question = run(service, "Ask a Question")
        assert question.context.form_values["active_package_id"] == package_id
        assert "What would you like to know" in question.draft_text

        customize = run(service, "Customize")
        assert customize.safe_metadata["handover_context"]["package_id"] == package_id


def test_media_action_without_package_context_does_not_default_to_standard():
    service, contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    contexts.record["form_values"].pop("active_package_id", None)
    contexts.record["form_values"].pop("standard_package_id", None)
    result = run(service, "See Photo & Video")
    assert "media_sequence" not in result.safe_metadata
    assert result.safe_metadata.get("media_sequence_unavailable") is True


def test_customize_hands_off_with_known_context():
    service, _contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    result = run(service, "special request")
    assert result.human_handover_required is True
    assert result.safe_metadata["handover_context"]["guest_count"] == 5
    assert result.context.details.preferred_date == date(2026, 8, 30)


def test_qualified_reload_without_presented_marker_sends_package_not_acknowledgement():
    service, contexts = orchestrator()
    run(service, "30 August, 5 people")
    result = run(service, "hello")
    assert result.draft_text.startswith("Hi there! 👋 Welcome back")
    assert result.reason_code == "coimbatore_returning_customer_menu"
    assert result.draft_text != "Great 🎉 I have your celebration date and number of guests."


def test_explicit_package_request_resends_even_when_already_presented():
    service, _contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    result = run(service, "tell me about standard package")
    assert result.draft_text.startswith("Thank you for sharing your details 😊")
    assert "Pontoon Boat Celebration Package" in result.draft_text
    assert result.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert result.safe_metadata["source_filename"] == "COIMBATORE_KNOWLEDGE_BASE.md"


def test_presented_package_routes_onward_without_qualification_loop_or_resend():
    service, _contexts = orchestrator()
    run(service, "standard package")
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    hello = run(service, "hello")
    assert hello.draft_text != "Great 🎉 I have your celebration date and number of guests."
    assert "Rack Rate" not in hello.draft_text
    assert hello.detected_intent == "greeting"
    assert hello.draft_text.startswith("Hi there! 👋 Welcome back")
    assert hello.safe_metadata["returning_customer_menu"] is True
    cake = run(service, "is cake included?")
    assert "Cake is included in the Standard Package" in cake.draft_text
    assert cake.safe_metadata["raipur_retrieval_used"] is False


def test_returning_greeting_sends_one_image_header_with_three_buttons():
    service, _contexts = orchestrator()
    run(service, "30 August, 5 people")

    result = run(service, "hii")

    interactive = result.safe_metadata["interactive_message"]
    assert interactive["kind"] == "buttons"
    assert interactive["header_image_url"] == (
        "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/"
        "pontoon_boat_celebration_Coimbtore.jpg"
    )
    assert [option["title"] for option in interactive["options"]] == [
        "See Standard Package", "See Couple Package", "Photos & Videos",
    ]
    assert result.draft_text == (
        "Hi there! 👋 Welcome back to Entartica Coimbatore.\n\n"
        "How can I help you plan your Pontoon Celebration today?"
    )


def test_returning_standard_button_sends_default_5999_package_and_preserves_context():
    service, _contexts = orchestrator()
    run(service, "30 August, 8 people")
    run(service, "hello")

    result = run(service, "coimbatore_pontoon_check_standard")

    assert result.safe_metadata["default_package_fallback"] is True
    assert "₹5,999" in result.draft_text and "₹5,100" in result.draft_text
    assert "Guests:" not in result.draft_text and "Event Date:" not in result.draft_text
    assert result.context.details.total_guests == 8
    assert result.context.details.preferred_date == date(2026, 8, 30)


def test_fresh_partial_and_presented_greetings_are_eligible():
    settings = SimpleNamespace(
        raipur_automatic_reply_enabled=True, exotel_outbound_enabled=True,
        raipur_approved_draft_send_enabled=True,
        raipur_automatic_reply_intents=("information", "location", "services"),
    )
    draft = {"draft_status": "pending_review", "sent_at": None, "external_message_id": None}
    service, _contexts = orchestrator()
    fresh = run(service, "hello")
    assert eligible_for_automatic_reply(settings, fresh, draft) == (True, "eligible")
    run(service, "30 August")
    partial = run(service, "hi")
    assert partial.draft_text == "Hi 😊 How many guests will be joining?"
    assert eligible_for_automatic_reply(settings, partial, draft) == (True, "eligible")
    qualified = run(service, "5 guests")
    confirm_package(service, qualified)
    presented = run(service, "hello")
    assert eligible_for_automatic_reply(settings, presented, draft) == (True, "eligible")


def test_presented_greeting_reaches_approval_and_sender():
    service, _contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    result = run(service, "hello")
    row = {"id": "draft", "draft_status": "pending_review", "sent_at": None, "external_message_id": None}
    class Repo:
        def __init__(self): self.approvals = 0
        def approve_draft(self, _draft_id): self.approvals += 1; return True
    class Sender:
        def __init__(self): self.calls = []
        async def send(self, draft_id, recipient, *, confirmed):
            self.calls.append((draft_id, recipient, confirmed))
            return ApprovedDraftSendResult(True, True, True, False, "completed")
    repo, sender = Repo(), Sender()
    settings = SimpleNamespace(
        raipur_automatic_reply_enabled=True, exotel_outbound_enabled=True,
        raipur_approved_draft_send_enabled=True,
        raipur_automatic_reply_intents=("information", "location", "services"),
    )
    outcome = asyncio.run(attempt_automatic_reply(
        settings=settings, orchestration=result, draft=row, recipient="test-recipient",
        repository=repo, sender_factory=lambda: sender,
    ))
    assert outcome.eligible and outcome.attempted and outcome.response_sent
    assert repo.approvals == 1 and sender.calls == [("draft", "test-recipient", True)]


def test_package_presented_stage_routes_price_token_and_nonsense_contextually():
    service, _contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    price = run(service, "how much is it")
    assert "₹5,999" in price.draft_text and "₹4,999" not in price.draft_text and price.context.sales_stage == SalesStage.PACKAGE_PRESENTED
    token = run(service, "how much token?")
    assert "100% advance payment" in token.draft_text
    nonsense = run(service, "gsgd")
    assert nonsense.draft_text.startswith("I didn't quite catch that")
    assert nonsense.context.sales_stage == SalesStage.PACKAGE_PRESENTED


def test_book_now_immediately_returns_payment_page_without_collecting_details():
    service, _contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    interested = run(service, "I want this")
    assert interested.context.sales_stage == SalesStage.PAYMENT_PENDING
    assert interested.context.pending_field is None
    assert "secure test payment link is not configured" in interested.draft_text
    assert "https://" not in interested.draft_text


def test_date_correction_preserves_once_only_accepted_presentation_state():
    service, _contexts = orchestrator()
    offered = run(service, "30 August, 5 people")
    confirm_package(service, offered)
    corrected = run(service, "change date to 31 August")
    assert corrected.context.details.preferred_date == date(2026, 8, 31)
    assert corrected.context.sales_stage == SalesStage.QUALIFIED
    assert corrected.safe_metadata["standard_package_presented"] is True
    assert "media_message" not in corrected.safe_metadata


def test_context_write_failure_does_not_crash_safe_first_reply(caplog):
    service, contexts = orchestrator()
    contexts.save_service_context = lambda *_args: (_ for _ in ()).throw(RuntimeError("write failed"))
    result = run(service, "hello")
    assert result.draft_text == FIRST_MESSAGE
    assert "coimbatore_context_save_failed operation=context_save" in caplog.text


@pytest.mark.parametrize(
    ("message", "guests"),
    [("we are couple", 2), ("five people", 5), ("family of 8", 8), ("11 guests", 11)],
)
def test_natural_guest_facts_select_current_package(message, guests):
    service, _contexts = orchestrator()
    result = run(service, message)
    assert result.context.details.total_guests == guests
    assert "celebration date" in result.draft_text
    assert result.context.form_values.get("active_package_id") == "coimbatore_pontoon_standard"
    assert result.safe_metadata["raipur_retrieval_used"] is False


def test_stale_twenty_five_is_overridden_by_current_couple_fact():
    service, _contexts = orchestrator()
    stale = run(service, "25 guests")
    confirm_package(service, stale)
    corrected = run(service, "we are couple")
    assert corrected.context.details.total_guests == 2
    assert corrected.context.form_values["active_package_id"] == "coimbatore_pontoon_standard"
    assert "celebration date" in corrected.draft_text
    assert corrected.human_handover_required is False
    follow_up = run(service, "what's the price?")
    assert "₹5,999" in follow_up.draft_text and "₹4,999" not in follow_up.draft_text


def test_natural_couple_sales_conversation_has_no_generic_recovery():
    service, _contexts = orchestrator()
    hello = run(service, "hello")
    assert "Welcome to Entartica Coimbatore" in hello.draft_text
    packages = run(service, "package")
    assert packages.draft_text.startswith("Pontoon Boat Celebration Package")
    assert "Special Offer" not in packages.draft_text and "₹4,999" not in packages.draft_text
    unknown_price = run(service, "what's the price of package")
    assert "share the guest count" in unknown_price.draft_text and "₹4,999" not in unknown_price.draft_text
    couple = run(service, "we are couple")
    assert couple.context.details.total_guests == 2 and "celebration date" in couple.draft_text
    included = run(service, "what is included?")
    assert "Cake" in included.draft_text and "30 Minutes" in included.draft_text
    duration = run(service, "how long?")
    assert "30" in duration.draft_text
    dated = run(service, "date is 30 august")
    assert dated.context.details.preferred_date == date(2026, 8, 30)
    assert "didn't quite catch" not in dated.draft_text


def test_family_then_couple_correction_recomputes_package_context():
    service, _contexts = orchestrator()
    family = run(service, "we are 8 people")
    assert family.context.details.total_guests == 8 and "celebration date" in family.draft_text
    family_price = run(service, "how much is it")
    assert "₹6,375" in family_price.draft_text and "₹7,500" in family_price.draft_text
    couple = run(service, "actually we are couple")
    assert couple.context.details.total_guests == 2 and "celebration date" in couple.draft_text
    assert couple.context.form_values["active_package_id"] == "coimbatore_pontoon_standard"
    duration = run(service, "how long is it")
    assert "30" in duration.draft_text


def test_thirteen_or_more_guests_remains_qualified_for_standard_and_nonsense_uses_recovery():
    service, _contexts = orchestrator()
    large = run(service, "13 people")
    assert large.human_handover_required is False
    assert large.context.details.total_guests == 13
    assert "celebration date" in large.draft_text
    service, _contexts = orchestrator()
    nonsense = run(service, "asdfgh")
    assert nonsense.draft_text == FIRST_MESSAGE


def test_occasion_is_meaningful_sales_intent_not_generic_recovery():
    service, _contexts = orchestrator()
    welcome = run(service, "birthday")
    assert "Welcome to Entartica Coimbatore" in welcome.draft_text
    result = run(service, "birthday")
    assert result.detected_intent == "occasion"
    assert "great way to celebrate" in result.draft_text
    assert "How many guests" in result.draft_text
