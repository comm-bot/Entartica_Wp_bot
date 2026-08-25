"""Trusted boundary for Pontoon package facts retrieved from the canonical KB."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo

from app.services.raipur.response_models import ConversationContext


PONTOON_PACKAGE_SOURCE_FILE = "active/services/pontoon_celebration.md"


@dataclass(frozen=True)
class ApprovedPontoonPackage:
    content: str
    image_url: str
    source_file: str = PONTOON_PACKAGE_SOURCE_FILE


def render_pontoon_package(sections: dict[str, str], *, source_file: str) -> ApprovedPontoonPackage | None:
    """Render only exact, required sections from the approved Pontoon document."""
    required = (
        "Approved Pontoon Boat Celebration Package", "Inclusions", "Current Approved Offer",
        "Booking Token", "Cancellation / Refund", "Offer Validity", "Approved Sales Media",
    )
    if source_file != PONTOON_PACKAGE_SOURCE_FILE or any(not sections.get(name, "").strip() for name in required):
        return None
    media_match = re.search(r"https://[^\s]+", sections["Approved Sales Media"])
    if media_match is None:
        return None
    inclusions = re.sub(r"(?m)^-\s*", "• ", sections["Inclusions"].strip())
    content = "\n\n".join((
        sections["Approved Pontoon Boat Celebration Package"].strip(),
        f"Inclusions:\n{inclusions}",
        sections["Current Approved Offer"].strip(),
        sections["Booking Token"].strip(),
        sections["Cancellation / Refund"].strip(),
        sections["Offer Validity"].strip(),
    ))
    return ApprovedPontoonPackage(content=content, image_url=media_match.group(0), source_file=source_file)


def pontoon_package_configured(package: ApprovedPontoonPackage | None) -> bool:
    return bool(package and package.content.strip() and package.image_url.startswith("https://"))


def pontoon_media_message(package: ApprovedPontoonPackage) -> dict[str, str]:
    return {"type": "image", "url": package.image_url, "caption": package.content}


def pontoon_date_is_past(value: date) -> bool:
    return value < datetime.now(ZoneInfo("Asia/Kolkata")).date()


def pontoon_missing_details_question(context: ConversationContext) -> str | None:
    missing_date = context.details.preferred_date is None
    missing_guests = context.details.total_guests is None
    if missing_date and missing_guests:
        return "What date are you planning the celebration for, and approximately how many persons will be attending?"
    if missing_date:
        return "What date are you planning the celebration for?"
    if missing_guests:
        return "Approximately how many persons will be joining?"
    return None


def pontoon_selection_response(context: ConversationContext, package: ApprovedPontoonPackage | None) -> str:
    opening = package.content if package else "I can help you plan a Pontoon Celebration enquiry."
    question = pontoon_missing_details_question(context)
    return f"{opening}\n\n{question}" if question else opening


def pontoon_package_question_response(context: ConversationContext, package: ApprovedPontoonPackage | None) -> str:
    opening = package.content if package else "Our team will share the approved Pontoon Celebration package details with you."
    question = pontoon_missing_details_question(context)
    return f"{opening}\n\n{question}" if question else opening


def pontoon_post_qualification_response(
    context: ConversationContext, *, past_date_rejected: bool = False,
) -> str:
    if past_date_rejected:
        return "That date has already passed. Please share a future date for the celebration."
    question = pontoon_missing_details_question(context)
    if question:
        return question
    planned = context.details.preferred_date
    return (
        f"Great — I have {planned.strftime('%d %B')} for {context.details.total_guests} guests for your Pontoon Celebration 🎉\n"
        "You can ask me anything about the package, inclusions or arrangements."
    )
