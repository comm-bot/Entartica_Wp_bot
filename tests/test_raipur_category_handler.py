import pytest

from app.services.raipur.category_handler import handle_raipur_category_request


def _active_services():
    return [
        {"name": "Jet Ski Ride"},
        {"name": "Staycation Combo"},
        {"name": "Daycation Package"},
        {"name": "Pontoon Celebration"},
        {"name": "Floating Gazebo"},
        {"name": "Kids Bumper Boat"},
        {"name": "Kids Paddle Boat"},
        {"name": "Zorbing Ball"},
        {"name": "Speed Boat"},
    ]


def test_shared_handler_returns_structured_celebration_decision():
    result = handle_raipur_category_request("celebration package i want", "en", _active_services())

    assert result.handled is True
    assert result.route == "approved_celebration_catalogue"
    assert result.intent == "celebration_service_list"
    assert result.answer_source == "approved_celebration_catalogue"
    assert result.response_text and "Pontoon Celebration" in result.response_text
    assert result.service_code is None
    assert result.topic is None
    assert result.fallback_reason is None
    assert result.catalogue_type == "celebration"
    assert result.catalogue_item_count == 2


def test_shared_handler_returns_approved_package_options():
    result = handle_raipur_category_request("i want combo package", "en", _active_services())

    assert result.handled is True
    assert result.intent == "service_catalogue"
    assert result.answer_source == "approved_package_catalogue"
    assert result.response_text and "Staycation Combo" in result.response_text
    assert result.catalogue_type == "package"


def test_shared_handler_returns_activity_catalogue_without_service_context():
    result = handle_raipur_category_request("share water activities info", "en", _active_services())

    assert result.handled is True
    assert result.intent == "service_catalogue"
    assert result.answer_source == "approved_activity_catalogue"
    assert result.response_text and "Jet Ski Ride" in result.response_text
    assert "Pontoon Celebration" not in result.response_text
    assert result.catalogue_type == "activity"


def test_shared_handler_fails_closed_for_non_category_question():
    result = handle_raipur_category_request("what is the duration of Jet Ski", "en", _active_services())

    assert result.handled is False
    assert result.route is None
    assert result.response_text is None


@pytest.mark.parametrize(
    "message,expected_intent,expected_source",
    [
        ("what are the celebartion are there", "celebration_service_list", "approved_celebration_catalogue"),
        ("can you provide list of all celebrations", "celebration_service_list", "approved_celebration_catalogue"),
        ("what celebrations are there", "celebration_service_list", "approved_celebration_catalogue"),
        ("celebration options", "celebration_service_list", "approved_celebration_catalogue"),
        ("celebrations batao", "celebration_service_list", "approved_celebration_catalogue"),
        ("sab celebration batao", "celebration_service_list", "approved_celebration_catalogue"),
        ("what activities do you have", "service_catalogue", "approved_activity_catalogue"),
        ("what rides do you have", "service_catalogue", "approved_activity_catalogue"),
        ("list all activities", "service_catalogue", "approved_activity_catalogue"),
        ("rides batao", "service_catalogue", "approved_activity_catalogue"),
        ("water activities kaun si hai", "service_catalogue", "approved_activity_catalogue"),
        ("what are the activities", "service_catalogue", "approved_activity_catalogue"),
        ("activities", "service_catalogue", "approved_activity_catalogue"),
        ("rides", "service_catalogue", "approved_activity_catalogue"),
        ("water activities", "service_catalogue", "approved_activity_catalogue"),
        ("adventure experience", "service_catalogue", "approved_activity_catalogue"),
        ("adventure experiences", "service_catalogue", "approved_activity_catalogue"),
        ("kya kya activities hai", "service_catalogue", "approved_activity_catalogue"),
    ],
)
def test_shared_handler_recognizes_live_catalogue_wording(message, expected_intent, expected_source):
    result = handle_raipur_category_request(message, "en", _active_services())

    assert result.handled is True
    assert result.intent == expected_intent
    assert result.answer_source == expected_source
    assert result.catalogue_item_count > 0


@pytest.mark.parametrize("catalogue_type,message,source", [
    ("activity", "give me list", "approved_activity_catalogue"),
    ("activity", "show me all", "approved_activity_catalogue"),
    ("celebration", "send list", "approved_celebration_catalogue"),
    ("package", "share options", "approved_package_catalogue"),
])
def test_shared_handler_resolves_short_followup_from_approved_catalogue_context(catalogue_type, message, source):
    result = handle_raipur_category_request(message, "en", _active_services(), previous_catalogue_type=catalogue_type)
    assert result.handled and result.answer_source == source


def test_short_list_without_catalogue_context_fails_closed():
    assert not handle_raipur_category_request("give me list", "en", _active_services()).handled


@pytest.mark.parametrize("message", (
    "water fun rides", "what water activities do you have?", "H2O activities",
    "pani wali activities kya hai?", "water sports",
))
def test_broad_water_discovery_returns_wider_activity_catalogue(message):
    result = handle_raipur_category_request(message, "en", _active_services())
    assert result.handled and result.answer_source == "approved_activity_catalogue"
    assert "Speed Boat" in result.response_text and "Kids Bumper Boat" in result.response_text
    assert "Pontoon Celebration" not in result.response_text


@pytest.mark.parametrize("message", (
    "kids water activities", "boat for kids", "kids ke liye kya hai?",
    "children water activities", "kids boat",
))
def test_kids_discovery_returns_only_approved_kids_group(message):
    result = handle_raipur_category_request(message, "hinglish", _active_services())
    assert result.handled and result.answer_source == "approved_kids_activity_catalogue"
    for name in ("Kids Bumper Boat", "Kids Paddle Boat", "Zorbing Ball"):
        assert name in result.response_text
    assert "Speed Boat" not in result.response_text and "Pontoon Celebration" not in result.response_text
    lowered = result.response_text.casefold()
    assert not any(term in lowered for term in ("price", "booking confirmed", "capacity", "age limit"))
