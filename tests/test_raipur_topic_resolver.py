import pytest

from app.services.raipur.topic_resolver import resolve_topic, topic_for_graph


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("Bumper Boat me kitne log aa sakte hain?", "capacity"),
        ("Kitni der ki hai?", "duration"),
        ("Swimming compulsory hai?", "swimming_requirement"),
        ("How does it work?", "how_it_works"),
        ("kaise karte hain", "how_it_works"),
        ("age", "eligibility"),
        ("kis age ke liye", "eligibility"),
        ("family ke liye", "suitable_for"),
        ("tell me more", "more_details"),
        ("aur batao", "more_details"),
        ("highlights", "highlights"),
        ("isme kya included hai?", "inclusions"),
        ("for whom house boat is suitable for", "suitable_for"),
        ("houseboat kiske liye hai", "suitable_for"),
        ("is there AC", "onboard_environment"),
        ("what is not allowed", "conduct_rules"),
        ("Party Boat kitni der ki hai?", "duration"),
        ("Party Boat kitne minute ki hai?", "duration"),
        ("Party Boat ka duration kya hai?", "duration"),
        ("What is the duartion of Jet Ski?", "duration"),
        ("What is the durtion of Jet Ski?", "duration"),
        ("Party Boat ka timing kya hai?", "operating_hours"),
        ("Party Boat kab se kab tak chalta hai?", "operating_hours"),
        ("Zorbing Ball kab tak chalta hai?", "operating_hours"),
        ("Water sports kab se kab tak chalti hain?", "operating_hours"),
        ("Jet Ski kitne baje tak chalti hai?", "operating_hours"),
        ("\u092a\u093e\u0930\u094d\u091f\u0940 \u092c\u094b\u091f \u0915\u093f\u0924\u0928\u0940 \u0926\u0947\u0930 \u0915\u0940 \u0939\u0948?", "duration"),
        ("\u091c\u0947\u091f \u0938\u094d\u0915\u0940 \u0915\u093f\u0924\u0928\u0947 \u092e\u093f\u0928\u091f \u0915\u0940 \u0939\u0948?", "duration"),
        ("\u092a\u093e\u0930\u094d\u091f\u0940 \u092c\u094b\u091f \u0915\u093e \u0938\u092e\u092f \u0915\u094d\u092f\u093e \u0939\u0948?", "operating_hours"),
        ("\u092a\u093e\u0930\u094d\u091f\u0940 \u092c\u094b\u091f \u0915\u093f\u0924\u0928\u0947 \u092c\u091c\u0947 \u0938\u0947 \u0915\u093f\u0924\u0928\u0947 \u092c\u091c\u0947 \u0924\u0915 \u0939\u0948?", "operating_hours"),
    ],
)
def test_resolves_existing_english_and_hinglish_topics(question, topic):
    result = resolve_topic(question)
    assert result.matched and result.topic == topic


def test_preserves_graph_swimming_spelling_without_a_duplicate_phrase_map():
    assert topic_for_graph(resolve_topic("Is swimming required?")) == "swimming"


@pytest.mark.parametrize(
    ("question", "graph_topic"),
    [
        ("Can pregnant women ride Jet Ski?", "eligibility"),
        ("Can I drive Jet Ski myself?", "how_it_works"),
        ("What happens if I fall from Jet Ski?", "safety"),
        ("Compare Jet Ski and Speed Boat.", "overview"),
    ],
)
def test_graph_topic_maps_unsupported_resolver_topics_into_supported_spellings(question, graph_topic):
    assert topic_for_graph(resolve_topic(question)) == graph_topic


def test_no_topic_result_is_safe():
    assert not resolve_topic("tell me about Jet Ski").matched
