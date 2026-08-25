"""Structural customer-ready projection for approved service knowledge."""
from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.raipur.capacity_governance import CapacityStatus, celebration_capacity_record
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, knowledge_service_code
from app.services.raipur.h2o_handler import is_h2o_service_code


_CELEBRATION_CODES = {
    knowledge_service_code(item) for item in APPROVED_RAIPUR_SERVICES
    if item.category == "floating_celebration"
}
_SECTIONS_BY_MODE = {
    "overview": ("experience overview",),
    "more_details": ("what makes this experience special", "what guests can expect", "best for", "customisation options", "how it works"),
    "suitable_for": ("best for",),
    "key_characteristics": ("what makes this experience special", "experience highlights"),
    "duration": ("duration", "package duration"),
    "operating_hours": ("operating hours",),
    "capacity": ("capacity", "guest limit", "guest configuration"),
    "inclusions": ("celebration inclusions", "package inclusions", "inclusions"),
    "safety": ("safety information",),
    "eligibility": ("participation requirements",),
    "how_it_works": ("how it works", "general experience", "what guests can expect"),
    "swimming": ("swimming requirement",),
}
_GENERIC_SECTIONS_BY_MODE = {
    "overview": ("definition", "overview", "experience overview", "service summary", "general experience", "experience type", "ride experience"),
    "more_details": ("what makes this experience special", "what guests can expect", "best for", "suitable for", "how it generally works", "how it works", "key characteristics", "safety and participation"),
    "duration": ("duration", "package duration", "session duration", "ride duration", "experience duration", "activity duration", "access period"),
    "operating_hours": ("operating hours", "opening hours", "timings", "schedule", "staycation package"),
    "capacity": ("capacity", "guest capacity", "guest limit", "guest configuration", "seating capacity", "group size", "number of guests", "participants"),
    "inclusions": ("inclusions", "package inclusions", "celebration inclusions", "what is included", "what is typically included", "typically included", "club room day access", "accommodation", "breakfast", "unlimited h2o play park access", "one time boat house access", "food voucher", "aqua roller activity under h2o play park access"),
    "how_it_works": ("how it works", "how it generally works", "general experience", "what guests can expect", "ride experience"),
    "safety": ("safety", "safety information", "safety and participation"),
    "swimming": ("swimming requirement",),
    "eligibility": ("age requirement", "eligibility", "participation requirements", "suitable for"),
    "suitable_for": ("suitable for", "best for", "ideal for", "recommended for"),
}
_GOVERNANCE_SENTENCE = re.compile(
    r"\b(?:published\s+(?:configuration|as\s+available)|production\s+value|should\s+not\s+be\s+assumed|"
    r"not\s+established|knowledge\s+document|current\s+entartica\s+pages?|different\s+(?:party\s+boat\s+)?durations?|"
    r"conflicting\s+sources?|source\s+discrepancy|facts\s+to\s+verify|pending\s+verification|"
    r"approved\s+source\s+conflict|evidence\s+status|internal\s+note|governance)\b",
    re.I,
)
_AUTHORING_SENTENCE = re.compile(
    r"\b(?:suggested|sample)\s+chatbot\s+response\b|\b(?:when\s+a\s+guest|customer)\s+asks?\b|"
    r"\bcurrent\s+(?:inclusions|pricing|availability).{0,120}\bshould\s+be\s+confirmed\b",
    re.I,
)


@dataclass(frozen=True)
class CustomerReadyKnowledge:
    text: str | None
    section_headings: tuple[str, ...] = ()


def normalized_heading(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip() if isinstance(value, str) else ""


def is_customer_ready_section(service_code: str | None, heading: object, detail_mode: str) -> bool:
    """Apply strict section contracts to celebration services only."""
    if service_code not in _CELEBRATION_CODES:
        if detail_mode == "overview":
            return True
        allowed = _GENERIC_SECTIONS_BY_MODE.get(detail_mode)
        return allowed is None or normalized_heading(heading) in allowed
    allowed = _SECTIONS_BY_MODE.get(detail_mode, ())
    return normalized_heading(heading) in allowed


def is_celebration_service_code(service_code: object) -> bool:
    return isinstance(service_code, str) and service_code in _CELEBRATION_CODES


def contains_governance_language(text: object) -> bool:
    return isinstance(text, str) and bool(_GOVERNANCE_SENTENCE.search(text) or _AUTHORING_SENTENCE.search(text))


def build_customer_ready_service_answer(
    sections: list[tuple[str, str]],
    *,
    service_name: str,
    service_code: str,
    detail_mode: str,
) -> CustomerReadyKnowledge:
    """Compose customer prose only from sections authorized for this topic."""
    accepted = [
        (heading, content) for heading, content in sections
        if is_customer_ready_section(service_code, heading, detail_mode)
        and isinstance(content, str) and content.strip()
    ]
    if not accepted:
        return CustomerReadyKnowledge(None)
    headings = tuple(dict.fromkeys(heading for heading, _content in accepted))
    if detail_mode == "duration":
        if is_h2o_service_code(service_code):
            return CustomerReadyKnowledge(
                f"{service_name} is included with H2O Play Park full-day access from 10:00 AM to 6:30 PM.", headings
            )
        if service_code == "daycation_package":
            return CustomerReadyKnowledge("Daycation lasts 4 hours, from 2:00 PM to 6:00 PM.", headings)
        if service_code == "staycation_combo":
            return CustomerReadyKnowledge("Staycation runs from 2:00 PM on check-in day to 12:00 PM the next day.", headings)
        value = _first_duration(accepted[0][1])
        if value is None:
            return CustomerReadyKnowledge(None)
        if service_code in _CELEBRATION_CODES:
            return CustomerReadyKnowledge(f"{service_name} has a starting duration of {value}. Extensions may be possible after confirmation.", headings)
        qualifier = "approximately " if re.search(r"\b(?:approximately|around)\b", accepted[0][1], re.I) else ""
        return CustomerReadyKnowledge(f"{service_name} lasts {qualifier}{value}.", headings)
    if detail_mode == "operating_hours":
        if service_code == "staycation_combo":
            return CustomerReadyKnowledge("Staycation package timings are 2:00 PM on check-in day to 12:00 PM the next day.", headings)
        value = _first_time_range(accepted[0][1])
        if value is None:
            return CustomerReadyKnowledge(None)
        return CustomerReadyKnowledge(
            f"{service_name} operating hours are {value}. Timings remain subject to weather and operational conditions.",
            headings,
        )
    if detail_mode == "capacity":
        record = celebration_capacity_record(service_code)
        if record and record.capacity_status is CapacityStatus.VERIFIED and record.maximum_capacity is not None:
            return CustomerReadyKnowledge(f"{service_name} can accommodate up to {record.maximum_capacity} guests.", headings)
        if service_code in _CELEBRATION_CODES:
            return CustomerReadyKnowledge(f"Please share your guest count, and the Entartica team can confirm the suitable {service_name} setup.", headings)
        facts = _customer_facts(accepted)
        return CustomerReadyKnowledge(" ".join(facts[:2]) if facts else None, headings)
    facts = _customer_facts(accepted)
    if not facts:
        return CustomerReadyKnowledge(None)
    if detail_mode == "overview":
        body = " ".join(facts[:2])
        return CustomerReadyKnowledge(
            f"{body}\n\nWould you like to know its duration, timings, or highlights?",
            headings,
        )
    if detail_mode == "more_details":
        body = "\n".join(f"• {fact}" for fact in facts[:4])
        return CustomerReadyKnowledge(
            f"Here are a few more details about {service_name}:\n\n{body}\n\nWould you like to know its duration or timings?",
            headings,
        )
    if detail_mode == "inclusions":
        return CustomerReadyKnowledge(" ".join(facts[:8]), headings)
    return CustomerReadyKnowledge(" ".join(facts[:4]), headings)


def _customer_facts(sections: list[tuple[str, str]]) -> list[str]:
    facts: list[str] = []
    for _heading, content in sections:
        for raw in content.replace("\r", "\n").splitlines():
            line = re.sub(r"^\s{0,3}#{1,6}\s*", "", raw).strip()
            line = re.sub(r"^[-*•]\s*", "", line).strip()
            line = line.strip("*_ ")
            if not line or line.endswith(":"):
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", line):
                sentence = sentence.strip()
                if sentence and not contains_governance_language(sentence):
                    sentence = re.sub(r"\b(?:currently\s+)?published\s+", "", sentence, flags=re.I)
                    facts.append(sentence)
    return list(dict.fromkeys(facts))


def _first_duration(content: str) -> str | None:
    match = re.search(r"\b(\d+(?:\.\d+)?(?:\s*(?:to|-|–)\s*\d+(?:\.\d+)?)?)\s*(minutes?|hours?)\b", content, re.I)
    if not match:
        return None
    value = re.sub(r"\s*(?:-|–)\s*", " to ", match.group(1))
    return f"{value} {match.group(2).casefold()}"


def _first_time_range(content: str) -> str | None:
    between = re.search(r"\b(\d{1,2}:\d{2}\s*[AP]M)\s+and\s+(\d{1,2}:\d{2}\s*[AP]M)\b", content, re.I)
    if between:
        return f"{between.group(1).upper()} to {between.group(2).upper()}"
    match = re.search(r"\b(\d{1,2}:\d{2}\s*[AP]M)\s*(?:to|-|–)\s*(\d{1,2}:\d{2}\s*[AP]M)\b", content, re.I)
    return f"{match.group(1).upper()} to {match.group(2).upper()}" if match else None
