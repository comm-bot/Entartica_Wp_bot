"""Pure location/form decisions; no Exotel or database dependencies."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.services.raipur.response_models import ConversationContext
from app.services.raipur.customer_understanding import parse_planned_date_text


LOCATIONS = ("raipur", "coimbatore", "prayagraj", "rajsamand")
_LOCATION_ALIASES = {
    "1": "raipur", "location_raipur": "raipur", "raipur": "raipur",
    "2": "coimbatore", "location_coimbatore": "coimbatore", "coimbatore": "coimbatore",
    "3": "prayagraj", "location_prayagraj": "prayagraj", "prayagraj": "prayagraj", "allahabad": "prayagraj",
    "4": "rajsamand", "location_rajsamand": "rajsamand", "rajsamand": "rajsamand",
}
_CHANGE_LOCATION = re.compile(
    r"\b(?:change|switch|different|other)\s+(?:my\s+)?location\b|\blocation\s+(?:change|badal)\b|"
    r"\b(?:jagah|location)\s+badal(?:na|ni)?\b", re.I,
)


def requested_location(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    normalized = " ".join(text.casefold().strip().split())
    return _LOCATION_ALIASES.get(normalized)


def requests_location_change(text: object) -> bool:
    return isinstance(text, str) and bool(_CHANGE_LOCATION.search(text))


def infer_form_type(values: dict[str, Any]) -> str | None:
    explicit = values.get("flow_type") or values.get("form_type")
    if explicit in {"general_quote", "celebration", "pontoon_celebration"}:
        return str(explicit)
    keys = {str(key).casefold().replace(" ", "_") for key in values}
    if keys & {"balloon_colour", "cake_flavour", "put_on_cake", "hanging"}:
        return "celebration"
    if keys & {"check_in_date", "check_out_date", "adults", "kids", "kids_age"}:
        return "general_quote"
    return None


def merge_form_response(context: ConversationContext, values: dict[str, Any]) -> tuple[ConversationContext, tuple[str, ...]]:
    """Validate and merge known submitted fields; nulls never erase state."""
    form_type = infer_form_type(values)
    if form_type is None:
        return context, ("unknown_form",)
    errors: list[str] = []
    stored = dict(context.form_values or {})
    details = context.details

    def value(*keys: str) -> Any:
        for key in keys:
            if key in values and values[key] not in (None, ""):
                return values[key]
        return None

    def integer(raw: Any, field: str) -> int | None:
        if raw is None:
            return None
        try:
            parsed = int(str(raw).strip())
        except (TypeError, ValueError):
            errors.append(field); return None
        if parsed < 0:
            errors.append(field); return None
        return parsed

    def parsed_date(raw: Any, field: str) -> date | None:
        if raw is None:
            return None
        text = str(raw).strip()
        for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
        errors.append(field); return None

    if form_type == "general_quote":
        check_in = parsed_date(value("check_in_date", "check_in"), "check_in_date")
        check_out = parsed_date(value("check_out_date", "check_out"), "check_out_date")
        adults = integer(value("adults"), "adults")
        kids = integer(value("kids"), "kids")
        if check_in and check_out and check_out < check_in:
            errors.append("check_out_date")
        for key, parsed in (("check_in_date", check_in), ("check_out_date", check_out), ("adults", adults), ("kids", kids)):
            if parsed is not None:
                stored[key] = parsed.isoformat() if isinstance(parsed, date) else parsed
        ages = value("kids_age", "kids_ages")
        if ages is not None:
            parsed_ages = [int(item) for item in re.findall(r"\d+", str(ages))]
            if parsed_ages:
                stored["kids_ages"] = parsed_ages
            else:
                errors.append("kids_age")
        details = replace(
            details,
            preferred_date=check_in or details.preferred_date,
            adults_count=adults if adults is not None else details.adults_count,
            children_count=kids if kids is not None else details.children_count,
            total_guests=(adults + kids) if adults is not None and kids is not None else details.total_guests,
        )
    elif form_type == "pontoon_celebration":
        guests = integer(value("number_of_persons"), "number_of_persons")
        if value("number_of_persons") is None:
            errors.append("number_of_persons")
        if guests == 0:
            errors.append("number_of_persons")
            guests = None
        planned = parsed_date(value("event_date"), "event_date")
        if value("event_date") is None:
            errors.append("event_date")
        if planned is not None and planned < datetime.now(ZoneInfo("Asia/Kolkata")).date():
            errors.append("event_date")
            planned = None
        if guests is not None:
            stored["guest_count"] = guests
        if planned is not None:
            stored["planned_date"] = planned.isoformat()
        details = replace(
            details,
            total_guests=guests if guests is not None else details.total_guests,
            preferred_date=planned if planned is not None else details.preferred_date,
        )
    else:
        guests = integer(value("number_of_persons", "celebration_guests"), "number_of_persons")
        visiting = parsed_date(value("date_of_visiting", "celebration_date"), "date_of_visiting")
        name = value("name", "celebration_name")
        if name is not None:
            details = replace(details, customer_name=str(name).strip() or details.customer_name)
        details = replace(details, total_guests=guests if guests is not None else details.total_guests,
                          preferred_date=visiting or details.preferred_date)
        mapping = {
            "contact_number": ("contact_number",), "email": ("email", "email_id"),
            "balloon_colour": ("balloon_colour",), "hanging": ("hanging",),
            "cake_flavour": ("cake_flavour",), "cake_text": ("cake_text", "put_on_cake"),
            "time_slot": ("time_slot",), "customer_location": ("customer_location", "your_location"),
        }
        for target, aliases in mapping.items():
            raw = value(*aliases)
            if raw is not None and str(raw).strip():
                stored[target] = str(raw).strip()
    return replace(
        context, details=details, active_journey="celebration" if form_type in {"celebration", "pontoon_celebration"} else "visit_quote",
        active_form=form_type, form_status="in_progress" if errors else "submitted", form_values=stored or None,
    ), tuple(dict.fromkeys(errors))


def merge_natural_visit_details(context: ConversationContext, text: object) -> ConversationContext:
    """Merge explicit visit counts/ages from ordinary text without hijacking Q&A."""
    if not isinstance(text, str):
        return context
    lowered = text.casefold()
    qualification_pending = context.active_journey == "visit_qualification"
    if not qualification_pending and not re.search(r"\b(?:adults?|kids?|child|children|persons?|people|guests?|check[ -]?in|check[ -]?out|coming|visit)\b", lowered):
        return context
    adult_match = re.search(r"\b(\d+)\s*adults?\b", lowered)
    kids_match = re.search(r"\b(\d+)\s*(?:kids?|children|child)\b", lowered)
    guests_match = re.search(r"\b(\d+)\s*(?:persons?|people|guests?|log)\b", lowered)
    ages_match = re.search(r"\b(?:ages?|kids?\s+age)\s*[: -]?\s*([\d,\s]+(?:and\s+\d+)?)", lowered)
    adults = int(adult_match.group(1)) if adult_match else None
    kids = int(kids_match.group(1)) if kids_match else None
    guests = int(guests_match.group(1)) if guests_match else None
    stored = dict(context.form_values or {})
    if ages_match:
        ages = [int(item) for item in re.findall(r"\d+", ages_match.group(1))]
        if ages:
            stored["kids_ages"] = ages
    check_in_match = re.search(r"\bcheck[ -]?in(?:\s+(?:on|date))?\s+(.+?)(?=\s+(?:and\s+)?check[ -]?out\b|$)", lowered)
    check_out_match = re.search(r"\bcheck[ -]?out(?:\s+(?:on|date))?\s+(.+?)(?=$|[,.;])", lowered)
    coming_match = re.search(r"\bcoming\s+(?:on\s+)?(\d{1,2}\s+[a-z]+(?:\s+\d{4})?)", lowered)
    natural_date_match = re.search(r"\b(today|tomorrow|\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{4})?)\b", lowered, re.I)
    check_in = parse_planned_date_text(check_in_match.group(1).strip()) if check_in_match else (
        parse_planned_date_text(coming_match.group(1)) if coming_match else (
            parse_planned_date_text(natural_date_match.group(1)) if qualification_pending and natural_date_match else None
        )
    )
    check_out = parse_planned_date_text(check_out_match.group(1).strip()) if check_out_match else None
    if check_in:
        stored["check_in_date"] = check_in.isoformat()
    if check_out and (not check_in or check_out >= check_in):
        stored["check_out_date"] = check_out.isoformat()
    origin_match = re.search(r"\b(?:coming\s+)?from\s+([a-z][a-z .'-]{1,60}?)(?=$|[,.;!?])", text, re.I)
    if origin_match:
        stored["customer_location"] = origin_match.group(1).strip().title()
    elif qualification_pending:
        parts = [part.strip() for part in text.split(",")]
        if len(parts) >= 3 and re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,60}", parts[-1]):
            stored["customer_location"] = parts[-1].title()
    details = replace(
        context.details,
        preferred_date=check_in or context.details.preferred_date,
        adults_count=adults if adults is not None else context.details.adults_count,
        children_count=kids if kids is not None else context.details.children_count,
        total_guests=(adults + kids) if adults is not None and kids is not None else (guests if guests is not None else context.details.total_guests),
    )
    return replace(context, details=details, form_values=stored or context.form_values)


def qualification_reply(context: ConversationContext) -> str | None:
    """Ask only for missing post-selection facts; return None when no fact was captured."""
    if context.active_journey != "visit_qualification":
        return None
    missing_date = context.details.preferred_date is None
    missing_guests = context.details.total_guests is None
    missing_location = not (context.form_values or {}).get("customer_location")
    if missing_date and missing_guests and missing_location:
        return None
    if not missing_date and not missing_guests and not missing_location:
        return "Great 😊 I have your visit details. Would you like to explore water activities, family activities, or packages?"
    missing = []
    if missing_date:
        missing.append("which date you are planning for")
    if missing_guests:
        missing.append("how many persons will be visiting")
    if missing_location:
        missing.append("which city you are coming from")
    if len(missing) == 1:
        question = missing[0]
    else:
        question = f"{', '.join(missing[:-1])}, and {missing[-1]}"
    return f"Great 😊 Please also share {question}."
