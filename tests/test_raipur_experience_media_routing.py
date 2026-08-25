"""Deterministic approved Experience Media routing and isolation."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rag.experience_media import ExperienceMedia, extract_approved_media
from app.services.booking_enquiries import BookingDetails
from app.services.raipur.response_models import ConversationContext, KnowledgeDraft
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


STAY = "https://www.instagram.com/reel/DYzUySLIoSV/?igsh=em5nZ2hvbjgxYmlz&igsi=em5nZ2hvbjgxYmlz"
PONTOON = "https://youtu.be/V--yiHZ7oiM?si=CYFyzoJsIpZDZdHS"
CELEBRATION = "https://www.instagram.com/reel/DYw4n-ToPBy/?igsh=MTFscmMwaWZ2eDUwYQ==&igsi=MTFscmMwaWZ2eDUwYQ=="
WATER_I = "https://www.instagram.com/reel/DbLHbqUIFLA/?igsh=MW85eGRraHY1b2d0Mg==&igsi=MW85eGRraHY1b2d0Mg=="
WATER_Y = "https://youtube.com/shorts/B8zgeznoPf8?si=Igub9aZ67w-6K-9o"
RAIPUR = "https://www.instagram.com/reel/DaXsQJUqTQD/?igsh=b295ZnV2dHJ0aWJ0&igsi=b295ZnV2dHJ0aWJ0"
HELD = "4pDAMd6yCfk"


class _Knowledge:
    def experience_media(self, *, scope, service_code=None, category=None):
        if service_code == "staycation_combo": return ExperienceMedia((STAY,), (), "service", service_code, category, "staycation_combo.md")
        if service_code == "pontoon_celebration": return ExperienceMedia((), (PONTOON,), "service", service_code, category, "pontoon_celebration.md")
        if category == "celebration": return ExperienceMedia((CELEBRATION,), (), "celebration", service_code, category, "raipur_celebration_faq.md")
        if category == "activity": return ExperienceMedia((WATER_I,), (WATER_Y,), "activity", service_code, category, "raipur_general_information.md")
        if scope == "venue" or category == "venue": return ExperienceMedia((RAIPUR,), (), "venue", source_document="raipur_general_information.md")
        return ExperienceMedia(scope=scope, service_code=service_code, category=category)

    def answer_service_details(self, _question, service_name, service_code, **kwargs):
        topic = kwargs["detail_mode"]
        text = f"{service_name} package timings are 2:00 PM to 12:00 PM the next day." if service_code == "staycation_combo" else f"{service_name} operating hours are 10:00 AM to 9:00 PM."
        return KnowledgeDraft(text, f"{service_code}.md", .9, False, "Duration" if topic == "duration" else "Operating Hours", 1, service_code, ("Duration",))


def _context(code, name):
    return ConversationContext(BookingDetails(None, None, None, None, None, None, None), last_service_code=code, last_service_name=name, active_topic="overview", active_entity_type="service", active_entity_name=name)


def _turn(message, context=None):
    workflow = RaipurLangGraphWorkflow(knowledge=_Knowledge(), understanding_enabled=False)
    state = {"message_id":"m", "conversation_id":"c", "customer_id":"u", "customer_message":message, "normalized_message":message.casefold(), "language":"en", "location_code":"raipur", "previous_service_code":getattr(context,"last_service_code",None), "previous_topic":getattr(context,"active_topic",None), "intent":None, "entity_type":"unknown", "service_code":None, "topic":None, "use_previous_service":False, "requires_handover":False, "handover_reason":None}
    return workflow.invoke(state, message=SimpleNamespace(content=message), customer={"id":"u"}, conversation={"id":"c","location_id":"raipur"}, source_message_id="m", current_state=context)


@pytest.mark.parametrize("word", ["highlights", "video", "youtube"])
def test_service_specific_media_wins_and_preserves_context(word):
    result = _turn(word, _context("staycation_combo", "Staycation Combo"))
    assert STAY in result.draft_text and PONTOON not in result.draft_text
    assert result.context.last_service_code == "staycation_combo" and not result.human_handover_required


def test_pontoon_specific_media_wins_then_factual_followup_still_uses_pontoon():
    media = _turn("video", _context("pontoon_celebration", "Pontoon Celebration"))
    assert PONTOON in media.draft_text and CELEBRATION not in media.draft_text
    timing = _turn("timings", media.context)
    assert "10:00 AM to 9:00 PM" in timing.draft_text
    assert timing.context.last_service_code == "pontoon_celebration"


@pytest.mark.parametrize(("code","name"), [("party_boat_celebration","Party Boat Celebration"),("floating_gazebo","Floating Gazebo")])
def test_celebration_service_uses_only_general_celebration_fallback(code, name):
    result = _turn("highlights", _context(code, name))
    assert CELEBRATION in result.draft_text and PONTOON not in result.draft_text


@pytest.mark.parametrize(("code","name"), [("zorbing_ball","Zorbing Ball"),("aqua_roller","Aqua Roller")])
def test_water_service_uses_only_water_category_media(code, name):
    result = _turn("video", _context(code, name))
    assert WATER_I in result.draft_text and WATER_Y in result.draft_text and RAIPUR not in result.draft_text


@pytest.mark.parametrize(("message","expected"), [("show me water activities",WATER_I),("show celebration videos",CELEBRATION),("show me Entartica Raipur video",RAIPUR)])
def test_general_media_requests_use_correct_scope(message, expected):
    result = _turn(message)
    assert expected in result.draft_text and not result.human_handover_required


def test_daycation_has_safe_no_media_and_never_uses_held_or_staycation_media():
    result = _turn("video", _context("daycation_package", "Daycation Package"))
    assert "don't have approved media" in result.draft_text
    assert HELD not in result.draft_text and STAY not in result.draft_text
    assert not result.human_handover_required


def test_typed_extractor_keeps_general_venue_and_water_scopes_separate():
    rows = [
        {"chunk_index":38,"content":"- "+RAIPUR,"metadata":{"section_heading":"Instagram"}},
        {"chunk_index":39,"content":"- "+WATER_I,"metadata":{"section_heading":"Instagram"}},
        {"chunk_index":40,"content":"- "+WATER_Y,"metadata":{"section_heading":"YouTube"}},
    ]
    venue = extract_approved_media(rows, scope="venue", source_document="active/general/raipur_general_information.md")
    activity = extract_approved_media(rows, scope="activity", source_document="active/general/raipur_general_information.md")
    assert venue.urls == (RAIPUR,)
    assert activity.urls == (WATER_I, WATER_Y)
