"""Engine-neutral deterministic detection of approved service topics."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TopicResolution:
    matched: bool = False
    topic: str | None = None
    explicit_topic: bool = False
    normalized_message: str = ""
    match_reason: str | None = None


_TOPICS = (
    ("self_driving", ("drive", "myself", "self driven", "self-driven", "operate", "control")),
    ("swimming_requirement", ("swim", "swimming", "swimming aana", "non-swimmer", "swimming nahi aati", "swimming zaruri", "tairna", "tair sakte", "swim karna")),
    ("pregnancy", ("pregnant", "pregnancy", "pregnent", "pregnency", "pragnant")),
    ("fall_safety", ("fall", "falls", "fell")),
    ("capacity", ("how many", "how many people can sit", "capacity", "people can ride", "persons", "kitne log", "kitna log", "kitne aadmi", "kitna aadmi", "kitne guest", "kitne person", "maximum kitne", "minimum kitne", "aa sakte", "ja sakte", "ek baar mein kitne", "ek ride mein kitne", "beth sakte", "baith sakte", "single or double", "solo or tandem")),
    ("duration", ("how long", "duration", "minutes", "kitni der", "kitne minute", "kitna time", "kitne time", "ride time", "session time", "extend", "extension", "\u0915\u093f\u0924\u0928\u0940 \u0926\u0947\u0930", "\u0915\u093f\u0924\u0928\u0947 \u092e\u093f\u0928\u091f", "\u0905\u0935\u0927\u093f", "duartion", "durtion")),
    ("suitable_for", ("suitable for", "who is it suitable for", "for whom", "kiske liye", "kis ke liye", "ideal for", "recommended for", "good for kids", "family ke liye", "couple ke liye", "children ke liye")),
    ("inclusions", ("included", "include", "inclusion", "what is included", "what are the inclusions", "breakfast", "food included", "decoration included", "what comes with", "kya included", "isme kya milega", "isme kya milta", "kya kya milta", "package mein kya", "package me kya", "activities included", "rides included")),
    ("key_characteristics", ("key characteristics", "key features", "features")),
    ("conduct_rules", ("not allowed", "not permitted", "conduct rules", "restrictions")),
    ("onboard_environment", ("air conditioning", "air conditioner", "is there ac", "there ac", "onboard environment", "onboard facilities")),
    ("eligibility", ("who can participate", "age limit", "age requirement", "kis age ke liye", "child allowed", "bacche kar", "kaun kar sakta", "allowed hai", "height", "weight")),
    ("operating_hours", ("timing", "opening time", "opening hours", "closing hours", "visiting hours", "operating hours", "during the day", "kab open", "kab khulta", "kab band", "kitne baje", "kab tak", "kab se kab tak", "khulta", "khulta hai", "band hota", "band hota hai", "what time", "ride kab chalti", "\u0915\u092c \u0938\u0947 \u0915\u092c \u0924\u0915", "\u0915\u093f\u0924\u0928\u0947 \u092c\u091c\u0947", "\u0938\u092e\u092f \u0915\u094d\u092f\u093e \u0939\u0948", "\u0938\u092e\u092f", "\u0915\u093f\u0924\u0928\u0947 \u092c\u091c\u0947 \u0916\u0941\u0932\u0924\u093e \u0939\u0948", "\u0915\u093f\u0924\u0928\u0947 \u092c\u091c\u0947 \u092c\u0902\u0926 \u0939\u094b\u0924\u093e \u0939\u0948", "\u0915\u092c \u0938\u0947 \u0915\u092c \u0924\u0915 \u0916\u0941\u0932\u093e \u0930\u0939\u0924\u093e \u0939\u0948", "\u0915\u092c \u0916\u0941\u0932\u0924\u093e \u0939\u0948", "\u0915\u092c \u092c\u0902\u0926 \u0939\u094b\u0924\u093e \u0939\u0948")),
    ("safety", ("safe", "safety", "life jacket", "helmet", "safety equipment", "instructor available", "safe hai", "suraksha")),
    ("how_it_works", ("how does it work", "how it works", "what happens", "kaise hota", "kaise karte", "kaise chalta", "ride ka process", "how do we ride", "khud chalana", "captain hoga", "isko kaise operate karte")),
    ("more_details", ("tell me more", "more details", "aur batao", "thoda aur batao")),
    ("highlights", ("highlights", "highlight", "video", "videos", "reel", "reels", "instagram", "youtube", "can i see", "how does it look", "dikhao", "video bhejo", "reel bhejo")),
    ("service_comparison", ("difference", "compare", "versus", " vs ")),
)


def resolve_topic(message: object) -> TopicResolution:
    text = message.strip() if isinstance(message, str) else ""
    normalized = text.casefold()
    if re.search(r"\bshow\s+me\s+(?:the\s+)?(?:water\s+activities|entartica(?:\s+raipur)?|raipur)\b", normalized):
        return TopicResolution(True, "highlights", True, normalized, "highlights")
    if re.search(r"\bage\b", normalized):
        return TopicResolution(True, "eligibility", True, normalized, "eligibility")
    for topic, terms in _TOPICS:
        if any(term in normalized for term in terms):
            return TopicResolution(True, topic, True, normalized, topic)
    return TopicResolution(normalized_message=normalized)


_GRAPH_TOPIC_ALIASES = {
    "swimming_requirement": "swimming",
    "pregnancy": "eligibility",
    "self_driving": "how_it_works",
    "fall_safety": "safety",
    "service_comparison": "overview",
}


def topic_for_graph(resolution: TopicResolution) -> str | None:
    """Map resolver topics onto the graph's supported topic spellings."""
    return _GRAPH_TOPIC_ALIASES.get(resolution.topic, resolution.topic)
