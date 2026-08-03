"""Approved, deterministic Raipur service manifest and matching helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass


SOURCE_FILENAME = "raipur_services.docx"


@dataclass(frozen=True)
class ApprovedRaipurService:
    name: str
    slug: str
    category: str
    source_section: str


# These names are limited to the customer-facing offerings explicitly named in
# the approved services document.  Package inclusions and optional add-ons are
# intentionally not separate records.
APPROVED_RAIPUR_SERVICES: tuple[ApprovedRaipurService, ...] = (
    ApprovedRaipurService("Staycation Combo", "staycation-combo", "staycation_daycation", "Staycation and Daycation"),
    ApprovedRaipurService("Daycation Package", "daycation-package", "staycation_daycation", "Staycation and Daycation"),
    ApprovedRaipurService("Pontoon Boat", "pontoon-boat", "water_ride", "Water Ride Portfolio"),
    ApprovedRaipurService("Kayak", "kayak", "water_ride", "Water Ride Portfolio"),
    ApprovedRaipurService("Speed Boat", "speed-boat", "water_ride", "Water Ride Portfolio"),
    ApprovedRaipurService("Aqua Cycle", "aqua-cycle", "water_ride", "Water Ride Portfolio"),
    ApprovedRaipurService("Jet Ski", "jet-ski", "water_ride", "Water Ride Portfolio"),
    ApprovedRaipurService("Water Bike", "water-bike", "water_ride", "Water Ride Portfolio"),
    ApprovedRaipurService("Inflatable Sofa Ride", "inflatable-sofa-ride", "water_ride", "Water Ride Portfolio"),
    ApprovedRaipurService("Bumper Boat", "bumper-boat", "water_ride", "Water Ride Portfolio"),
    ApprovedRaipurService("Kids' Paddle Boat", "kids-paddle-boat", "water_ride", "Water Ride Portfolio"),
    ApprovedRaipurService("Pontoon Celebration", "pontoon-celebration", "floating_celebration", "Floating Celebration Services"),
    ApprovedRaipurService("Floating Gazebo", "floating-gazebo", "floating_celebration", "Floating Celebration Services"),
    ApprovedRaipurService("Jetty Gazebo", "jetty-gazebo", "floating_celebration", "Floating Celebration Services"),
    ApprovedRaipurService("Houseboat Celebration", "houseboat-celebration", "floating_celebration", "Floating Celebration Services"),
    ApprovedRaipurService("Party Boat Celebration", "party-boat-celebration", "floating_celebration", "Floating Celebration Services"),
)


def normalize_service_text(value: object) -> str | None:
    """Normalize only harmless casing, spacing, and punctuation variation."""

    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[^\w\u0900-\u097f]+", " ", value.casefold()).replace("_", " ").strip()
    normalized = re.sub(r"\bbuper\b", "bumper", normalized)
    normalized = re.sub(r"\b(bumper|pontoon|speed|party|house)\s+bot\b", r"\1 boat", normalized)
    normalized = re.sub(r"\b(speed)\s+baot\b", r"\1 boat", normalized)
    return normalized or None


def approved_service_by_slug(slug: object) -> ApprovedRaipurService | None:
    if not isinstance(slug, str):
        return None
    return next((item for item in APPROVED_RAIPUR_SERVICES if item.slug == slug.strip().casefold()), None)


def approved_service_by_name(value: object) -> ApprovedRaipurService | None:
    normalized = normalize_service_text(value)
    if normalized is None:
        return None
    matches = [item for item in APPROVED_RAIPUR_SERVICES if normalize_service_text(item.name) == normalized]
    return matches[0] if len(matches) == 1 else None


def approved_service_from_message(value: object) -> ApprovedRaipurService | None:
    """Extract exactly one approved service name or explicitly approved alias."""

    normalized = normalize_service_text(value)
    if normalized is None:
        return None
    padded = f" {normalized} "
    exact = [item for item in APPROVED_RAIPUR_SERVICES if f" {normalize_service_text(item.name)} " in padded]
    if len(exact) == 1:
        return exact[0]
    matches = [item for phrase, item in _SERVICE_ALIASES.items() if f" {phrase} " in padded]
    unique_matches = {item.slug: item for item in matches}
    return next(iter(unique_matches.values())) if len(unique_matches) == 1 else None


def approved_primary_service_from_question(value: object) -> ApprovedRaipurService | None:
    """Resolve a document for a full service question, including comparisons.

    The existing exact helper intentionally rejects ambiguous service mentions.
    A comparison still needs one exact service document as its primary grounded
    source, so use manifest order only after the strict helper finds no result.
    """

    resolved = approved_service_from_message(value)
    if resolved is not None:
        return resolved
    normalized = normalize_service_text(value)
    if normalized is None:
        return None
    padded = f" {normalized} "
    return next(
        (item for item in APPROVED_RAIPUR_SERVICES if f" {normalize_service_text(item.name)} " in padded),
        None,
    )


def approved_service_alias_used(value: object) -> bool:
    """Return true only when a non-canonical, explicit approved alias matched."""

    normalized = normalize_service_text(value)
    if normalized is None:
        return False
    padded = f" {normalized} "
    return not any(f" {normalize_service_text(item.name)} " in padded for item in APPROVED_RAIPUR_SERVICES) and any(
        f" {phrase} " in padded for phrase in _SERVICE_ALIASES
    )


def is_active_approved_service(service: object, approved: ApprovedRaipurService) -> bool:
    """Ensure an alias can only confirm an active database service in the approved manifest."""

    if not isinstance(service, dict) or service.get("is_active") is not True:
        return False
    return normalize_service_text(service.get("name")) == normalize_service_text(approved.name) or service.get("slug") == approved.slug


def knowledge_service_code(service: ApprovedRaipurService) -> str:
    """Return the stable RAG code without changing the database-facing slug."""

    return _KNOWLEDGE_CODES[service.slug]


_BY_SLUG = {item.slug: item for item in APPROVED_RAIPUR_SERVICES}
_KNOWLEDGE_CODES = {
    "staycation-combo": "staycation_combo", "daycation-package": "daycation_package",
    "pontoon-boat": "pontoon_boat_ride", "kayak": "kayaking", "speed-boat": "speed_boat_ride",
    "aqua-cycle": "aqua_cycle", "jet-ski": "jet_ski_ride", "water-bike": "water_bike",
    "inflatable-sofa-ride": "inflatable_sofa_ride", "bumper-boat": "bumper_boat",
    "kids-paddle-boat": "kids_paddle_boat", "pontoon-celebration": "pontoon_celebration",
    "floating-gazebo": "floating_gazebo", "jetty-gazebo": "jetty_gazebo",
    "houseboat-celebration": "houseboat_celebration", "party-boat-celebration": "party_boat_celebration",
}
_SERVICE_ALIASES = {
    "jet ski": _BY_SLUG["jet-ski"], "jetski": _BY_SLUG["jet-ski"], "jet skiing": _BY_SLUG["jet-ski"], "जेट स्की": _BY_SLUG["jet-ski"],
    "speed boat": _BY_SLUG["speed-boat"], "speedboat": _BY_SLUG["speed-boat"], "स्पीड बोट": _BY_SLUG["speed-boat"],
    "kayak": _BY_SLUG["kayak"], "kayaking": _BY_SLUG["kayak"], "कयाक": _BY_SLUG["kayak"],
    "pontoon": _BY_SLUG["pontoon-boat"], "pontoon boat": _BY_SLUG["pontoon-boat"], "पोंटून बोट": _BY_SLUG["pontoon-boat"],
    "aqua cycle": _BY_SLUG["aqua-cycle"], "water cycle": _BY_SLUG["aqua-cycle"],
    "water bike": _BY_SLUG["water-bike"], "sofa ride": _BY_SLUG["inflatable-sofa-ride"], "inflatable sofa": _BY_SLUG["inflatable-sofa-ride"],
    "bumper boat": _BY_SLUG["bumper-boat"], "kids paddle boat": _BY_SLUG["kids-paddle-boat"], "paddle boat": _BY_SLUG["kids-paddle-boat"],
    "floating gazebo": _BY_SLUG["floating-gazebo"], "jetty gazebo": _BY_SLUG["jetty-gazebo"],
    "houseboat celebration": _BY_SLUG["houseboat-celebration"], "party boat": _BY_SLUG["party-boat-celebration"], "celebration boat": _BY_SLUG["party-boat-celebration"],
    "staycation": _BY_SLUG["staycation-combo"], "daycation": _BY_SLUG["daycation-package"],
    "day package": _BY_SLUG["daycation-package"], "one day package": _BY_SLUG["daycation-package"],
    "same day package": _BY_SLUG["daycation-package"],
}
_SERVICE_ALIASES.update({"po toon boat": _BY_SLUG["pontoon-boat"], "pontoon bahot": _BY_SLUG["pontoon-boat"]})
