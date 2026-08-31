"""Coimbatore-only graph routing and deterministic performance contracts."""
from dataclasses import replace

from app.services.coimbatore.langgraph_workflow import CoimbatoreLangGraphWorkflow
from app.services.coimbatore.pontoon_package import load_standard_package
from app.services.latency import LatencyTrace, use_latency_trace
from tests.test_coimbatore_llm_brain import run, service


def graph_service():
    bot = service(persist=False)
    bot._settings.coimbatore_langgraph_enabled = True
    bot._langgraph_enabled = True
    bot._langgraph = CoimbatoreLangGraphWorkflow(bot._process_turn)
    return bot


def test_graph_entry_guest_date_and_direct_package_are_coimbatore_only():
    bot = graph_service()
    hello = run(bot, "hello")
    assert hello.safe_metadata["graph_route"] == "qualification"
    assert hello.safe_metadata["raipur_graph_used"] is False
    guest = run(bot, "5")
    assert guest.context.details.total_guests == 5
    assert guest.context.pending_field == "preferred_date"
    package = run(bot, "23/08/2026")
    assert package.safe_metadata["graph_route"] == "standard_package"
    assert package.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert package.context.details.total_guests == 5
    assert package.context.details.preferred_date.isoformat() == "2026-08-23"


def test_graph_multifield_package_is_deterministic_without_openai_or_embedding():
    bot = graph_service()
    trace = LatencyTrace(request_id="coimbatore-deterministic")
    with use_latency_trace(trace):
        package = run(bot, "5,23/08/2026")
    assert package.safe_metadata["graph_route"] == "standard_package"
    assert trace.counters["logical_openai_calls"] == 0
    assert trace.counters["embedding_calls"] == 0
    assert trace.value("package_render") < 100
    assert trace.value("total_orchestration") == 0  # outer webhook owns this stage


def test_graph_routes_faq_booking_question_handoff_and_photos():
    bot = graph_service()
    package = run(bot, "5,23/08/2026")
    bot.confirm_standard_package_presented(package, "customer", "conversation")

    faq = run(bot, "what is pyro?")
    assert faq.safe_metadata["graph_route"] == "faq"
    assert faq.safe_metadata["raipur_graph_used"] is False
    booking = run(bot, "Book Now")
    assert booking.safe_metadata["graph_route"] == "booking"

    bot = graph_service(); package = run(bot, "5,23/08/2026")
    bot.confirm_standard_package_presented(package, "customer", "conversation")
    question = run(bot, "Ask a Question")
    assert question.safe_metadata["graph_route"] == "faq_wait"

    bot = graph_service(); package = run(bot, "5,23/08/2026")
    bot.confirm_standard_package_presented(package, "customer", "conversation")
    customize = run(bot, "Customize")
    assert customize.safe_metadata["graph_route"] == "handoff"

    bot = graph_service(); package = run(bot, "5,23/08/2026")
    bot.confirm_standard_package_presented(package, "customer", "conversation")
    photos = run(bot, "See Photo & Video")
    assert photos.safe_metadata["graph_route"] == "photos"
    assert [item["type"] for item in photos.safe_metadata["media_sequence"]] == ["image", "image", "video", "video"]


def test_graph_flag_false_preserves_existing_fallback_and_package_cache_hits():
    load_standard_package.cache_clear()
    bot = service(persist=False)
    bot._settings.coimbatore_langgraph_enabled = False
    bot._langgraph = None
    first = run(bot, "5,23/08/2026")
    second = run(bot, "send standard package")
    assert first.safe_metadata.get("active_engine") != "coimbatore_langgraph"
    assert second.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    assert load_standard_package.cache_info().hits >= 1
