"""Temporary Coimbatore date/time and text-only package milestone."""
from datetime import date, time
import asyncio
import json
from types import SimpleNamespace

import httpx

from app.services.latency import LatencyTrace, use_latency_trace
from app.services.raipur_automatic_replies import eligible_for_automatic_reply
from app.services.raipur_draft_integration import create_draft_after_orchestration
from app.services.raipur_draft_sender import RaipurDraftSender
from app.integrations.exotel import ExotelClient
from tests.support.fake_outbound_drafts import FakeOutboundDraftRepository
from tests.test_coimbatore_llm_brain import run, service


def text_bot():
    return service(persist=False, media=False)


def test_fresh_date_then_occupancy_auto_sends_package_with_actions_without_media():
    bot = text_bot()
    welcome = run(bot, "hello")
    assert welcome.draft_text == (
        "Hi 👋 Welcome to Entartica Coimbatore.\n\n"
        "I'll help you plan your Pontoon Celebration 🎉\n\n"
        "How many guests will be visiting, and what date are you planning for?\n\n"
        "💡 eg. 7 , 26/08/2026"
    )
    dated = run(bot, "23/08/2026")
    assert dated.context.details.preferred_date == date(2026, 8, 23)
    assert dated.context.pending_field == "total_guests"
    assert "guests" in dated.draft_text
    trace = LatencyTrace(request_id="text-package")
    with use_latency_trace(trace):
        package = run(bot, "5")
    assert package.context.details.total_guests == 5
    assert package.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert trace.counters["logical_openai_calls"] == 0
    assert trace.counters["embedding_calls"] == 0
    assert "media_message" not in package.safe_metadata
    assert package.safe_metadata["interactive_message"]["kind"] == "list"
    assert len(package.safe_metadata["interactive_message"]["options"]) == 6
    assert all(value in package.draft_text for value in (
        "Pontoon Boat Celebration Package", "Event Date: 23 Aug 2026",
            "Guests: 5", "~₹5,999/-~", "₹5,100/- (15% OFF)",
        "30 Minutes Premium Boat Ride",
    ))
    assert "What time" not in package.draft_text


def test_occupancy_then_date_and_combined_input_do_not_ask_time():
    bot = text_bot()
    occupied = run(bot, "5")
    assert occupied.context.details.total_guests == 5
    assert occupied.context.pending_field == "preferred_date"
    assert "date" in occupied.draft_text.casefold()
    package = run(bot, "23/08/2026")
    assert "Guests: 5" in package.draft_text
    assert "What time would" not in package.draft_text

    combined = run(text_bot(), "5, 23/08/2026")
    assert combined.context.details.preferred_date == date(2026, 8, 23)
    assert combined.context.details.total_guests == 5
    assert combined.safe_metadata["package_id"] == "coimbatore_pontoon_standard"


def test_past_date_correction_retains_guests_and_immediately_sends_package():
    bot = text_bot()
    run(bot, "huu")

    rejected = run(bot, "20/06/2026 , 5")
    assert rejected.context.details.total_guests == 5
    assert rejected.context.details.preferred_date is None
    assert "has already passed" in rejected.draft_text
    assert rejected.context.pending_field == "preferred_date"

    package = run(bot, "26/08/2026")
    assert package.context.details.total_guests == 5
    assert package.context.details.preferred_date == date(2026, 8, 26)
    assert package.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert package.safe_metadata["approved_package"] is True
    assert package.draft_text.startswith("Thank you for sharing your details 😊")
    assert "Event Date: 26 Aug 2026" in package.draft_text
    assert "Guests: 5" in package.draft_text
    assert "₹5,100/- (15% OFF)" in package.draft_text


def test_explicit_package_is_nonblank_and_has_actions_without_media():
    explicit = run(text_bot(), "send package")
    assert explicit.draft_text.startswith("Pontoon Boat Celebration Package")
    assert "media_message" not in explicit.safe_metadata
    assert len(explicit.safe_metadata["interactive_message"]["options"]) == 6


def test_text_package_draft_is_eligible_plain_text_and_faqs_still_route_normally():
    bot = text_bot()
    package = run(bot, "5, 23/08/2026")
    repository = FakeOutboundDraftRepository()
    created = create_draft_after_orchestration(
        settings=SimpleNamespace(raipur_inbound_orchestrator_enabled=True,
                                 raipur_draft_creation_enabled=True,
                                 raipur_draft_review_migration_ready=True),
        inbound_message={"id":"text-inbound"}, customer={"id":"customer"},
        conversation={"id":"conversation"}, orchestration=package,
        repository_factory=lambda: repository,
    )
    assert created.draft_saved
    draft = repository.get_draft_by_id("fake-draft-1")
    assert draft["message_type"] == "interactive"
    assert "media_message" not in draft["draft_metadata"]
    settings = SimpleNamespace(
        raipur_automatic_reply_enabled=True, exotel_outbound_enabled=True,
        raipur_approved_draft_send_enabled=True,
        raipur_automatic_reply_intents=("information", "location", "services"),
    )
    assert eligible_for_automatic_reply(settings, package, draft) == (True, "eligible")
    assert repository.approve_draft(draft["id"])
    captured = []
    def provider(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(202, json={"response":{"whatsapp":{"messages":[
            {"code":202, "status":"success", "data":{"sid":"text-package-sid"}}
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
    content = captured[0]["whatsapp"]["messages"][0]["content"]
    assert content["type"] == "interactive"
    interactive = content["interactive"]
    assert "Pontoon Boat Celebration Package" in interactive["body"]["text"]
    assert "header" not in interactive and "video" not in content
    assert len(interactive["action"]["sections"][0]["rows"]) == 6
    assert interactive["action"]["sections"][0]["rows"][-2]["title"] == "See Pontoon Brochure"
    assert interactive["action"]["sections"][0]["rows"][-1]["title"] == "Check Couple Package"
    bot.confirm_standard_package_presented(package, "customer", "conversation")
    cake = run(bot, "what is cake flavour?")
    pyro = run(bot, "only 2 pyros?")
    duration = run(bot, "what is duration?")
    assert "available flavour" in cake.draft_text
    assert "2 cold pyros" in pyro.draft_text
    assert "30-minute" in duration.draft_text
    assert all("Rack Rate" not in result.draft_text for result in (cake, pyro, duration))


def test_approved_location_answer_and_photo_video_action_send_three_messages():
    bot = text_bot()
    package = run(bot, "5, 23/08/2026")
    bot.confirm_standard_package_presented(package, "customer", "conversation")
    location = run(bot, "what is the address of your site")
    assert "Periyakulam Lake Boat House" in location.draft_text
    assert "Ukkadam, Coimbatore, Tamil Nadu 641001" in location.draft_text
    assert "https://share.google/AUJRM6sIvbEqeJeH2" in location.draft_text

    media = run(bot, "See Photo & Video")
    sequence = media.safe_metadata["media_sequence"]
    assert [item["type"] for item in sequence] == ["image", "image", "video"]
    assert [item["url"] for item in sequence] == [
        "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/pontoon_standard_package_coimbatore.jpeg",
        "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/pontoon_celebration_photo_coimbatore.jpeg",
        "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/pontoon_boat_celebration_video_coimbatore.mp4",
    ]
    repository = FakeOutboundDraftRepository()
    created = create_draft_after_orchestration(
        settings=SimpleNamespace(raipur_inbound_orchestrator_enabled=True,
                                 raipur_draft_creation_enabled=True,
                                 raipur_draft_review_migration_ready=True),
        inbound_message={"id":"media-action-inbound"}, customer={"id":"customer"},
        conversation={"id":"conversation"}, orchestration=media,
        repository_factory=lambda: repository,
    )
    assert created.draft_saved
    draft = repository.get_draft_by_id("fake-draft-1")
    assert repository.approve_draft(draft["id"])
    captured = []
    def provider(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        index = len(captured)
        return httpx.Response(202, json={"response":{"whatsapp":{"messages":[
            {"code":202, "status":"success", "data":{"sid":f"media-sid-{index}"}}
        ]}}})
    exotel = ExotelClient(
        account_sid="account", api_key="key", api_token="token",
        whatsapp_from="+919900000000", transport=httpx.MockTransport(provider),
    )
    settings = SimpleNamespace(
        exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True,
        raipur_outbound_test_recipients=("+919000000000",), exotel_status_callback_url=None,
    )
    sent = asyncio.run(RaipurDraftSender(repository, settings, exotel).send(
        draft["id"], "+919000000000", confirmed=True,
    ))
    assert sent.accepted
    assert [payload["whatsapp"]["messages"][0]["content"]["type"] for payload in captured] == [
        "image", "image", "video", "interactive",
    ]
    cta = captured[-1]["whatsapp"]["messages"][0]["content"]["interactive"]
    assert cta["type"] == "button"
    assert [button["reply"]["title"] for button in cta["action"]["buttons"]] == [
        "Book Now", "Customize", "Talk to Sales Person",
    ]
