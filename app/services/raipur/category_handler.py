"""Deterministic approved-category handling shared by Raipur engines.

This module owns neither persistence nor outbound delivery.  It accepts active
service rows and returns a typed, customer-safe decision for its caller.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.services.raipur_services import approved_service_from_message


_BULLET = "\u2022"


@dataclass(frozen=True)
class RaipurCategoryHandlerResult:
    handled: bool = False
    route: str | None = None
    intent: str | None = None
    service_code: str | None = None
    topic: str | None = None
    answer_source: str | None = None
    response_text: str | None = None
    fallback_reason: str | None = None
    catalogue_type: str | None = None
    catalogue_source: str | None = None
    catalogue_filter: str | None = None
    catalogue_item_count: int = 0


_SERVICE_LIST_QUESTION = re.compile(
    r"\b(?:various|different|all|available|list|options?|show|tell\s+me)\b[^.?!]{0,40}\b(?:rides?|activities|services?)\b|"
    r"\b(?:rides?|activities|services?)\b[^.?!]{0,30}\b(?:available|list|options?|hain|hai|batao)\b|"
    r"\bwhat\s+(?:are\s+the\s+)?rides\b|\bhow\s+many\s+(?:rides|activities|services)\b|"
    r"\b(?:can\s+you\s+provide|show\s+me|any)\s+(?:other\s+)?(?:rides?|activities|services?)\b|"
    r"\bwhat\s+else\s+do\s+you\s+have\b|\b(?:aur\s+(?:kaun\s+si|kaun\s+kaun)\s+)?(?:rides?|activities)\s+(?:hain|hai|batao)\b|"
    r"\bdusri\s+rides?|baaki\s+rides?|aur\s+kya\s+hai\b|\b(?:share\s+)?water\s+activities(?:\s+info)?\b|"
    r"\bwhat\s+(?:activities|rides)\s+do\s+you\s+have\b|\b(?:list|show)\s+all\s+(?:activities|rides)\b|"
    r"\b(?:activities|rides)\s+batao\b|\bwater\s+activities\s+kaun\s+si\s+hai\b|"
    r"\bkya\s+kya\s+(?:activities|rides)\s+hai\b|\ball\s+(?:activities|rides)\b|\b(?:activity|ride)\s+list\b|\b"
    r"raipur\s+(ki|mein)\s+(activity|activities|services?)\s+(kya|hain|hai)\b|"
    r"^\s*(?:what\s+are\s+the\s+)?(?:activities|activity|rides|water\s+activities|adventure\s+(?:experience|experiences|activity|activities))\s*[?.!]*\s*$|"
    r"\bwhat\s+can\s+we\s+do\s+there\b|\badventure\s+(?:experience|experiences|activity|activities)(?:\s+batao)?\b|"
    r"\bwater\s+(?:sports?\s*)?(?:(?:rides?|activities)\s*){1,3}\b|"
    r"\b(?:water\s+fun(?:\s+(?:rides?|activities))?|fun\s+(?:water\s+)?(?:rides?|activities)|water\s+sports?|h2o\s+activities?)\b|"
    r"\brides?\s+(?:and|aur)\s+activities\b|\b(?:pani|paani)\s+wali\s+activit(?:y|ies)\b|"
    r"\bwater\s+(?:me|mein)\s+kya\s+(?:hai|activities)\b",
    re.I,
)
_KIDS_ACTIVITY_QUESTION = re.compile(
    r"\b(?:kids?|children|child|bachch\w*)\b[^.?!]{0,35}\b(?:water\s+)?(?:activities|rides?|boats?|options?)\b|"
    r"\b(?:water\s+)?(?:activities|rides?|boats?)\b[^.?!]{0,35}\b(?:for\s+kids?|for\s+children|kids?|children|bachch\w*)\b|"
    r"\b(?:kids?|children)\s+ke\s+liye\s+kya\s+hai\b|\b(?:boat|ride)\s+for\s+kids?\b|\bkids?\s+boats?\b",
    re.I,
)
_KIDS_ACTIVITY_SLUGS = frozenset({"kids-bumper-boat", "kids-paddle-boat", "zorbing-ball"})
_CELEBRATION_LIST_QUESTION = re.compile(
    r"\b(?:what|which|show|list|provide|tell\s+me|can\s+you\s+provide)\b[^.?!]{0,45}\b(?:celebrations?|parties)\b|"
    r"\b(?:celebrations?|parties)\s+(?:list|options?|packages?|services?|batao)\b|"
    r"\b(?:sab|all)\s+(?:celebrations?|parties)\s+(?:batao|list)?\b|"
    r"\b(?:celebration|party|birthday|anniversary)\b.*\b(options?|services?|activities|available|offer|book|package|boat|karna|chahiye)\b|"
    r"\b(?:celebration|party)\s+(?:options?|services?|package)\s*(?:kya|hain|hai|batao)\b|"
    r"\b(?:boat\s+pe|boat\s+par|on\s+boat)\s+(?:birthday|party|celebration)\b|\bparty\s+ke\s+liye\b|"
    r"\b(?:water\s+)?rides?\s+nahi\s+chahiye\b|\b(?:ride|water\s+activit(?:y|ies))\s+nahi\s+chahiye\b|"
    r"\bdont\s+want\s+water\s+activit(?:y|ies)\b|सेलिब्रेशन.*विकल्प",
    re.I,
)
_PACKAGE_LIST_QUESTION = re.compile(
    r"\b(?:combo|family|rides?|activity)\s+package\b|\bpackage\s+(?:options?|list)\b|\bi\s+want\s+(?:a\s+)?combo\b|^\s*packages?\s*[?.!]*\s*$",
    re.I,
)
_BIRTHDAY_CELEBRATION_REQUEST = re.compile(
    r"\b(?:celebrate|celebration|party)\b[^.?!]{0,35}\bbirthday\b|\bbirthday\b[^.?!]{0,35}\b(?:celebrate|celebration|party)\b",
    re.I,
)
_BARE_CELEBRATION_REQUEST = re.compile(r"^\s*celebrations?\s*[?.!]*\s*$", re.I)
_CELEBRATION_OCCASION = re.compile(
    r"^\s*(?:anniversary|birthday|engagement|wedding|retirement)(?:\s+celebration)?(?:\s+(?:karna|karvana)\s+hai)?\s*[?.!]*\s*$|"
    r"^\s*(?:corporate\s+(?:event|outing|function)|client\s+event|team\s+celebration|office\s+event)\s*[?.!]*\s*$|"
    r"^\s*(?:\u0938\u093e\u0932\u0917\u093f\u0930\u0939|\u091c\u0928\u094d\u092e\u0926\u093f\u0928|\u0936\u093e\u0926\u0940\s+\u0915\u0940\s+\u0938\u093e\u0932\u0917\u093f\u0930\u0939|\u0938\u093e\u0932\u0917\u093f\u0930\u0939\s+\u0915\u0940\s+\u092a\u093e\u0930\u094d\u091f\u0940)\s*[?.!]*\s*$",
    re.I,
)
_CATALOGUE_FOLLOWUP = re.compile(
    r"^\s*(?:show|give|send)(?:\s+me)?\s+(?:the\s+)?list\s*[?.!]*\s*$|"
    r"^\s*(?:share\s+options?|tell\s+me\s+all|what\s+options|list\s+please|show\s+me\s+all)\s*[?.!]*\s*$|"
    r"^\s*(?:kids?|children|adventure)?\s*(?:options?|activities?|rides?|list)\s*(?:batao|bhejo|please)?\s*[?.!]*\s*$|"
    r"^\s*(?:adventure|water\s+adventure|private|intimate|relaxed|lively|couple)\s*[?.!]*\s*$",
    re.I,
)
_CATALOGUE_TOPICS = {
    "activity_catalogue": "activity", "service_catalogue": "activity",
    "celebration_catalogue": "celebration", "package_catalogue": "package",
}

_ACTIVITY_PREFERENCE_FOLLOWUP = re.compile(
    r"^\s*(?:(?:i\s+(?:am|m)|im)\s+(?:looking\s+for|looking|want)|i\s+want(?:\s+something)?|something|kuch)?\s*"
    r"(?:good\s+and\s+)?(?:calm|relax(?:ed|ing)?|peaceful|easy(?:\s+and\s+relaxing)?|exciting|adventure|water\s+adventure)"
    r"(?:\s+(?:experience|activity|ride))?(?:\s+(?:chahiye|batao))?\s*[?.!]*\s*$|"
    r"^\s*(?:i\s+)?(?:do\s+not|don['’]?t)\s+want\s+adventure\s*[?.!]*\s*$|"
    r"^\s*bahut\s+fast\s+nahi\s*[?.!]*\s*$",
    re.I,
)


def is_activity_preference_followup(text: str) -> bool:
    """Recognize a natural preference only after activity context is known."""
    return bool(_ACTIVITY_PREFERENCE_FOLLOWUP.fullmatch(_normalize_category_text(text)))


def is_service_catalogue_request(text: str) -> bool:
    value = _normalize_category_text(text)
    asks_fact = bool(re.search(r"\b(?:how\s+long|duration|timings?|opening|closing|open|close)\b", value))
    return (
        bool(_SERVICE_LIST_QUESTION.search(value))
        and not asks_fact
        and approved_service_from_message(value) is None
        and not _is_inclusion_question(value)
    )


def is_celebration_category_request(text: str) -> bool:
    value = _normalize_category_text(text)
    return bool(_CELEBRATION_LIST_QUESTION.search(value) or _BARE_CELEBRATION_REQUEST.fullmatch(value)) and approved_service_from_message(value) is None


def is_package_category_request(text: str) -> bool:
    # A generic combo package can match an alias but still asks for options.
    return bool(_PACKAGE_LIST_QUESTION.search(_normalize_category_text(text)))


def catalogue_type_from_topic(topic: object) -> str | None:
    return _CATALOGUE_TOPICS.get(topic) if isinstance(topic, str) else None


def requested_catalogue_type(text: str, previous_catalogue_type: str | None = None) -> str | None:
    """Resolve an explicit approved catalogue or one short persisted follow-up."""

    normalized = _normalize_category_text(text)
    if _KIDS_ACTIVITY_QUESTION.search(normalized) and not re.search(r"\b(?:family|families|saath)\b", normalized):
        return "kids_activity"
    if is_celebration_category_request(normalized) or _BIRTHDAY_CELEBRATION_REQUEST.search(normalized):
        return "celebration"
    if previous_catalogue_type == "celebration" and _CELEBRATION_OCCASION.fullmatch(normalized):
        return "celebration"
    if is_package_category_request(normalized):
        return "package"
    if is_service_catalogue_request(normalized):
        return "activity"
    if previous_catalogue_type == "activity" and is_activity_preference_followup(normalized):
        return "activity"
    if previous_catalogue_type in {"activity", "celebration", "package"} and _CATALOGUE_FOLLOWUP.fullmatch(normalized):
        return previous_catalogue_type
    return None


def handle_raipur_category_request(
    text: str,
    language: str,
    active_services: list[dict[str, Any]],
    *,
    previous_catalogue_type: str | None = None,
    consume_pending_celebration_occasion: bool = False,
    force_celebration_catalogue: bool = False,
    celebration_followup: str | None = None,
) -> RaipurCategoryHandlerResult:
    """Return one approved catalogue/category answer, or an unhandled result."""
    normalized = _normalize_category_text(text)
    approved = [
        row for row in active_services
        if isinstance(row, dict) and approved_service_from_message(row.get("name")) is not None
    ]
    requested_type = (
        "celebration"
        if (consume_pending_celebration_occasion or force_celebration_catalogue) and normalized
        else requested_catalogue_type(normalized, previous_catalogue_type)
    )
    occasion_already_provided = bool(
        consume_pending_celebration_occasion
        or force_celebration_catalogue
        or (
            previous_catalogue_type == "celebration"
            and _CELEBRATION_OCCASION.fullmatch(normalized)
        )
    )
    if requested_type == "celebration":
        rows = [
            row for row in approved
            if getattr(approved_service_from_message(row.get("name")), "category", None) == "floating_celebration"
        ]
        if rows:
            return RaipurCategoryHandlerResult(
                handled=True, route="approved_celebration_catalogue", intent="celebration_service_list",
                answer_source="approved_celebration_catalogue",
                response_text=(
                    birthday_celebration_enquiry_answer(rows, language, followup=celebration_followup)
                    if _BIRTHDAY_CELEBRATION_REQUEST.search(normalized)
                    else celebration_service_list_answer(
                        rows, language, occasion_already_provided=occasion_already_provided,
                        followup=celebration_followup,
                    )
                ),
                catalogue_type="celebration", catalogue_source="active_raipur_services",
                catalogue_filter="location=raipur;active=true;approved_manifest=true;category=floating_celebration",
                catalogue_item_count=len(rows),
            )
    if requested_type == "package":
        rows = [
            row for row in approved
            if getattr(approved_service_from_message(row.get("name")), "category", None) in {"package", "staycation_daycation"}
        ]
        if rows:
            return RaipurCategoryHandlerResult(
                handled=True, route="approved_package_catalogue", intent="service_catalogue",
                answer_source="approved_package_catalogue",
                response_text=package_service_list_answer(rows, language),
                catalogue_type="package", catalogue_source="active_raipur_services",
                catalogue_filter="location=raipur;active=true;approved_manifest=true;category=staycation_daycation",
                catalogue_item_count=len(rows),
            )
    if requested_type == "kids_activity":
        rows = [
            row for row in approved
            if getattr(approved_service_from_message(row.get("name")), "slug", None) in _KIDS_ACTIVITY_SLUGS
        ]
        if rows:
            return RaipurCategoryHandlerResult(
                handled=True, route="approved_kids_activity_catalogue", intent="activity_service_list",
                answer_source="approved_kids_activity_catalogue",
                response_text=kids_activity_list_answer(rows, language),
                catalogue_type="activity", catalogue_source="active_raipur_services",
                catalogue_filter="location=raipur;active=true;approved_manifest=true;slug=kids-bumper-boat|kids-paddle-boat|zorbing-ball",
                catalogue_item_count=len(rows),
            )
    if requested_type == "activity" and approved:
        rows = [
            row for row in approved
            if getattr(approved_service_from_message(row.get("name")), "category", None) == "water_ride"
        ]
        if not rows:
            return RaipurCategoryHandlerResult()
        return RaipurCategoryHandlerResult(
            handled=True, route="approved_activity_catalogue", intent="service_catalogue",
            answer_source="approved_activity_catalogue",
            response_text=service_list_answer(rows, language),
            catalogue_type="activity", catalogue_source="active_raipur_services",
            catalogue_filter="location=raipur;active=true;approved_manifest=true;category=water_ride",
            catalogue_item_count=len(rows),
        )
    return RaipurCategoryHandlerResult()


def _is_inclusion_question(text: str) -> bool:
    return bool(re.search(r"\b(?:included|include|inclusion|comes\s+with|isme)\b", text, re.I))


def _normalize_category_text(text: str) -> str:
    """Correct only known harmless spelling variants before category matching."""

    value = text.casefold().strip()
    return re.sub(r"\b(?:celebartion|celibration|celeberation)\b", "celebration", value)


def service_list_answer(services: list[dict[str, Any]], language: str) -> str:
    names = _service_names(services)
    if language == "hinglish":
        return f"Raipur mein {', '.join(names)} aur anya activities available hain. Aap kis activity ke baare mein details chahte hain?"
    if language == "hi":
        return f"रायपुर में {', '.join(names)} और अन्य गतिविधियाँ उपलब्ध हैं। आप किस गतिविधि की जानकारी चाहते हैं?"
    return "*Activities at Entartica Sea World Raipur*\n\n" + "\n".join(f"{_BULLET} {name}" for name in names) + "\n\nTell me which activity you would like to know more about."


def kids_activity_list_answer(services: list[dict[str, Any]], language: str) -> str:
    names = _service_names(services)
    if language in {"hi", "hinglish"}:
        return f"Kids ke liye Entartica Raipur mein approved water activities hain: {', '.join(names)}."
    return "*Kids' Water Activities at Entartica Raipur*\n\n" + "\n".join(f"{_BULLET} {name}" for name in names)


def celebration_service_list_answer(
    services: list[dict[str, Any]],
    language: str,
    *,
    occasion_already_provided: bool = False,
    followup: str | None = None,
) -> str:
    names = _service_names(services)
    next_question = followup or (
        "Aapke saath approx kitne guests honge?" if language == "hinglish"
        else "Aapke saath lagbhag kitne guests honge?" if language == "hi"
        else "Approximately how many guests will join the celebration?"
    )
    if language == "hinglish":
        return f"Entartica Sea World, Raipur mein celebration options hain: {', '.join(names)}. {next_question}"
    if language == "hi":
        return f"Entartica Sea World, Raipur mein celebration options hain: {', '.join(names)}. {next_question}"
    return "*Celebrations at Entartica Sea World Raipur*\n\n" + "\n".join(f"{_BULLET} {name}" for name in names) + f"\n\n{next_question}"


def birthday_celebration_enquiry_answer(services: list[dict[str, Any]], language: str, *, followup: str | None = None) -> str:
    names = _service_names(services)
    return (
        "*Birthday Celebration at Entartica Raipur*\n\n"
        "You can explore these celebration options:\n\n"
        + "\n".join(f"{_BULLET} {name}" for name in names)
        + f"\n\n{followup or 'Approximately how many guests will join the celebration?'}"
    )


def package_service_list_answer(services: list[dict[str, Any]], language: str) -> str:
    names = _service_names(services)
    if language == "hinglish":
        return f"Raipur mein approved package options hain: {', '.join(names)}. Aap kis package ke baare mein details chahte hain? Current pricing aur availability team confirm karegi."
    return f"The approved Raipur package options include {', '.join(names)}. Which package would you like to know more about? Current pricing and availability must be confirmed by the Entartica team."


def _service_names(services: list[dict[str, Any]]) -> list[str]:
    return [row["name"].strip() for row in services if isinstance(row.get("name"), str) and row["name"].strip()]
