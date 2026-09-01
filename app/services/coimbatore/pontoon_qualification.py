"""Deterministic qualification for the Coimbatore Pontoon MVP."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.services.raipur.customer_understanding import parse_planned_date_text
from app.services.raipur.response_models import ConversationContext, ConversationResult
from app.services.raipur.sales_state import SalesStage


FIRST_MESSAGE = """Hi 👋 Welcome to Entartica Coimbatore.

I'll help you plan your Pontoon Celebration 🎉

How many guests will be visiting, and what date are you planning for?

💡 eg. 7 , 26/08/2026"""

_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE_RE = re.compile(
    rf"\b(today|tomorrow|(?:this|next)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    rf"\d{{1,2}}(?:st|nd|rd|th)?(?:/\d{{1,2}}(?:/\d{{2,4}})?|-\d{{1,2}}-\d{{2,4}}|\s+{_MONTH}(?:\s+\d{{4}})?)|"
    rf"{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?)\b",
    re.I,
)
_GUEST_RE = re.compile(
    r"\b(?:we\s+are\s+(\d{1,3})(?!\s*(?:/|-))|family\s+of\s+(\d{1,3})|make\s+it\s+(\d{1,3})|(?:hum\s+)?(\d{1,3})\s*(?:guests?|people|persons?|pax|log|members?))\b",
    re.I,
)
_COUPLE_RE = re.compile(
    r"\b(?:we\s+are\s+(?:a\s+)?couple|(?:just\s+)?me\s+and\s+my\s+(?:wife|husband)|two\s+of\s+us|only\s+both\s+of\s+us|couple)\b",
    re.I,
)
_WORD_GUEST_RE = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen)\s+(?:guests?|people|persons?|members?)\b",
    re.I,
)
_WORD_NUMBERS = {word: number for number, word in enumerate(
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen")
)}
_DATE_UNDECIDED_RE = re.compile(
    r"\b(?:"
    r"(?:(?:i|we|they)\s+)?(?:(?:am|are|'m|'re)\s+)?(?:still\s+)?not\s+sure\s+(?:about\s+)?(?:the\s+)?date|"
    r"(?:(?:i|we|they)\s+)?(?:have\s+not|haven't|did\s+not|didn't|still\s+not)\s+"
    r"(?:decided|fixed|confirmed|finali[sz]ed)(?:\s+(?:the|a))?\s+date|"
    r"date\s+(?:is\s+)?(?:not\s+(?:decided|fixed|confirmed|finali[sz]ed)|undecided)|"
    r"no\s+date\s+yet|(?:i\s+)?(?:do\s+not|don't)\s+know\s+(?:the\s+)?date"
    r")\b",
    re.I,
)


def is_enabled(settings: Any, context: ConversationContext | None) -> bool:
    """Select only the explicitly configured or already-active Coimbatore MVP."""
    return (
        getattr(settings, "mvp_default_location_code", None) == "coimbatore"
        or getattr(context, "selected_location", None) == "coimbatore"
    )


def qualify(
    text: object,
    context: ConversationContext,
    *,
    timezone_name: str = "Asia/Kolkata",
    today: date | None = None,
) -> ConversationResult:
    """Merge explicit date/guest facts and ask for only unresolved fields."""
    content = text.strip() if isinstance(text, str) else ""
    local_today = today or date.today()
    if today is None:
        from datetime import datetime
        local_today = datetime.now(ZoneInfo(timezone_name)).date()

    guest_count = _guest_count(content, context)
    date_undecided = _date_is_undecided(content)
    date_text = _date_text(content)
    planned_date = parse_planned_date_text(date_text, today=local_today)
    past_date = False
    if date_text and planned_date is not None:
        # A day/month already elapsed this year is treated as past, matching the
        # qualification rule rather than silently assuming the following year.
        has_year = bool(re.search(r"\b\d{4}\b", date_text))
        if not has_year and planned_date.year > local_today.year and not re.search(r"today|tomorrow|this\s+", date_text, re.I):
            past_date = True
        elif planned_date < local_today:
            past_date = True
    elif date_text:
        past_date = True

    details = context.details
    changed = False
    if guest_count is not None:
        changed = guest_count != details.total_guests
        details = replace(details, total_guests=guest_count)
    if planned_date is not None and not past_date:
        changed = changed or planned_date != details.preferred_date
        details = replace(details, preferred_date=planned_date)

    values = dict(context.form_values or {})
    if planned_date is not None and not past_date:
        values.pop("date_undecided", None)
    elif date_undecided:
        details = replace(details, preferred_date=None)
        values["date_undecided"] = True
    # Do not clear provider-accepted presentation state when qualification
    # details are corrected. Automatic presentation is once per journey;
    # explicit customer resend remains available separately.

    complete = details.preferred_date is not None and details.total_guests is not None
    package_ready = details.total_guests is not None and (
        details.preferred_date is not None or bool(values.get("date_undecided"))
    )
    values["qualification_missing_fields"] = [
        field for field, missing in (
            ("preferred_date", details.preferred_date is None and not values.get("date_undecided")),
            ("total_guests", details.total_guests is None),
        ) if missing
    ]
    merged = replace(
        context,
        details=details,
        form_values=values,
        selected_location="coimbatore",
        last_service_code="pontoon_celebration",
        last_service_name="Pontoon Boat Celebration",
        active_journey="pontoon_qualification",
        sales_stage=SalesStage.QUALIFIED if complete else SalesStage.LEAD,
        pending_field=None if package_ready else ("preferred_date" if details.preferred_date is None else "total_guests"),
    )

    if past_date:
        noted = f"I've noted {details.total_guests} guests 😊\n" if guest_count is not None else ""
        shown = f"{planned_date.day} {planned_date.strftime('%B %Y')}" if planned_date is not None else date_text
        reply = f"{noted}{shown} has already passed. Which future date are you planning for?"
    elif complete:
        reply = "Great 🎉 I have your celebration date and number of guests."
    elif package_ready:
        reply = "No problem 😊 You can decide the date later. Here are the package details."
    elif details.preferred_date is not None:
        reply = "How many guests will be joining? 👥"
    elif details.total_guests is not None:
        reply = "Please share your celebration date 📅"
    else:
        reply = FIRST_MESSAGE
    return ConversationResult(
        action="answer_information", draft_text=reply, reason_code="coimbatore_pontoon_qualification",
        detected_intent="visit_qualification", detected_location="coimbatore", response_language="en",
        human_handover_required=False, context=merged,
        safe_metadata={"response_mode": "deterministic_interactive", "response_basis": "deterministic",
                       "answer_source": "structured_grounding", "structured_grounding": True,
                       "customer_response_sanitized": True, "service_code": "pontoon_celebration",
                       "coimbatore_pontoon_mvp": True},
    )


def _date_text(text: str) -> str | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    value = match.group(1)
    month_first = re.fullmatch(rf"({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", value, re.I)
    if month_first:
        month, day, year = month_first.groups()
        return f"{day} {month}{f' {year}' if year else ''}"
    return value


def _date_is_undecided(text: str) -> bool:
    return bool(_DATE_UNDECIDED_RE.search(text))


def package_qualification_ready(context: ConversationContext) -> bool:
    """Return whether pricing can be shown with a known or undecided date."""
    return context.details.total_guests is not None and (
        context.details.preferred_date is not None
        or bool((context.form_values or {}).get("date_undecided"))
    )


def _guest_count(text: str, context: ConversationContext) -> int | None:
    if _COUPLE_RE.search(text):
        return 2
    match = _GUEST_RE.search(text)
    if match:
        value = int(next(group for group in match.groups() if group is not None))
        return value if value > 0 else None
    word_match = _WORD_GUEST_RE.search(text)
    if word_match:
        return _WORD_NUMBERS[word_match.group(1).casefold()]
    if context.pending_field in {"guest_count", "total_guests"}:
        word = re.fullmatch(r"\s*(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen)\s*", text, re.I)
        if word:
            return _WORD_NUMBERS[word.group(1).casefold()]
    # A second bare number alongside an explicit date is the requested group
    # size (for example ``30/08/2026,5``). Removing the date first keeps FAQ
    # quantities such as "2 pyros" outside this form-field path.
    date_match = _DATE_RE.search(text)
    if context.details.total_guests is None and date_match:
        remainder = f"{text[:date_match.start()]} {text[date_match.end():]}"
        separator = r"(?:[,.;:-]|\band\b)?"
        bare = re.fullmatch(
            rf"\s*{separator}\s*(\d{{1,3}})\s*{separator}\s*(?:guests?|people|persons?|pax)?\s*",
            remainder,
            re.I,
        )
        if bare and int(bare.group(1)) > 0:
            return int(bare.group(1))
    # After an over-capacity typo, accept a bare in-capacity number as an
    # explicit correction even though the previous turn completed the form.
    # This remains narrow enough not to reinterpret FAQ quantities such as
    # "2 pyros" as a guest count.
    correcting_over_capacity = (
        isinstance(context.details.total_guests, int)
        and context.details.total_guests > 10
    )
    if (context.details.total_guests is None or correcting_over_capacity) and not _DATE_RE.search(text):
        bare = re.fullmatch(r"\s*(\d{1,3})\s*", text)
        if bare and 1 <= int(bare.group(1)) <= 10:
            return int(bare.group(1))
    return None


def has_qualification_update(text: object, context: ConversationContext) -> bool:
    """Recognize form answers without treating incidental FAQ numbers as guests."""
    if not isinstance(text, str):
        return False
    if re.search(r"\b(?:available|availability|slot|open)\b", text, re.I):
        return False
    if (_DATE_RE.search(text) or _date_is_undecided(text) or _COUPLE_RE.search(text)
            or _GUEST_RE.search(text) or _WORD_GUEST_RE.search(text)):
        return True
    if context.pending_field in {"guest_count", "total_guests"} and re.fullmatch(
        r"\s*(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen)\s*", text, re.I
    ):
        return True
    if (
        isinstance(context.details.total_guests, int)
        and context.details.total_guests > 10
        and re.fullmatch(r"\s*(?:10|[1-9])\s*", text)
    ):
        return True
    return False
