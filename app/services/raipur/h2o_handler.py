"""Deterministic H2O Playpark knowledge answers shared by the Raipur engines.

This module owns no persistence or outbound delivery.  It answers only the
approved H2O Playpark facts and never confirms live availability, pricing, or
bookings.
"""
from __future__ import annotations

import re
from app.services.raipur_services import approved_service_from_message, knowledge_service_code

_H2O_PLAY_PARK_QUESTION = re.compile(r"\b(?:h2o|h20|play\s*park|playpark)\b", re.I)

_ACTIVITIES = (
    "Kayak",
    "Aqua Cycle",
    "Aqua Roller",
    "Bumper Boat",
    "Zorbing Ball",
    "Kids Bumper Boat",
    "Kids Paddle Boat",
    "Water Bike",
)


def h2o_service_codes() -> frozenset[str]:
    """Canonical codes derived from the existing approved H2O catalogue."""
    return frozenset(
        knowledge_service_code(service)
        for name in _ACTIVITIES
        if (service := approved_service_from_message(name)) is not None
    )


def is_h2o_service_code(service_code: object) -> bool:
    return isinstance(service_code, str) and service_code in h2o_service_codes()


def asks_individual_turn_duration(text: object) -> bool:
    return isinstance(text, str) and bool(re.search(
        r"\b(?:one|individual|single|each|per)\s+(?:turn|session|ride)|"
        r"\bexact\s+(?:minutes?|duration)|\bhow\s+many\s+minutes\b",
        text, re.I,
    ))


def h2o_service_duration_answer(service_name: str, *, individual_turn: bool = False) -> str:
    access = f"{service_name} is included with H2O Play Park full-day access from 10:00 AM to 6:30 PM."
    if individual_turn:
        return f"The individual {service_name} turn duration isn't separately listed in the approved information. {access}"
    return access


def is_h2o_playpark_question(text: str) -> bool:
    return isinstance(text, str) and bool(_H2O_PLAY_PARK_QUESTION.search(text))


def h2o_playpark_answer(language: str = "en") -> str:
    """Return the approved H2O Playpark access and inclusion summary only."""
    activities = ", ".join(_ACTIVITIES)
    if language == "hinglish":
        return (
            f"H2O Playpark full-day access 10:00 AM se 6:30 PM tak provide karta hai "
            f"aur isme {activities} shaamil hain. Playpark ki activities full-day "
            f"Playpark access ke andar included hain aur har activity din bhar nahi "
            f"chalti. Current availability, pricing, aur booking Entartica team se "
            f"confirm karni hogi. Please contact the Entartica team at +91 9429691418 "
            f"or sales@entartica.com."
        )
    if language == "hi":
        return (
            f"H2O Playpark 10:00 AM se 6:30 PM tak full-day access pradan karta hai "
            f"aur isme {activities} shaamil hain. Playpark ki gatividhiyan full-day "
            f"Playpark access mein shaamil hain aur har gatividhi poore din nahi "
            f"chalti. Vartaman uplabdhata, mulya nirdharan, aur booking ki pushti "
            f"Entartica team se karni hogi. Kripya Entartica team se +91 9429691418 "
            f"ya sales@entartica.com par sampark karein."
        )
    return (
        f"H2O Playpark provides full-day access from 10:00 AM to 6:30 PM and includes "
        f"{activities}. Individual activities in the Playpark are included under the "
        f"full-day Playpark access and do not each run all day. Current availability, "
        f"pricing, and booking must be confirmed with the Entartica team. Please "
        f"contact the Entartica team at +91 9429691418 or sales@entartica.com."
    )
