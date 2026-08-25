"""Central, presentation-only formatter for approved WhatsApp replies."""
from __future__ import annotations

import re
from app.rag.customer_ready_knowledge import contains_governance_language


_INTERNAL = re.compile(r"\b(?:source filename|section heading|knowledge document|retrieval|rag|chunk|embedding|internal guidance|suggested chatbot response)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_TOPIC_LABELS = {
    "duration": "Duration", "capacity": "Capacity", "swimming": "Swimming Requirement",
    "swimming_requirement": "Swimming Requirement", "how_it_works": "How It Works",
    "safety": "Safety Information", "eligibility": "Participation Information",
    "inclusions": "What's Included", "operating_hours": "Operating Hours",
}
_MOJIBAKE_REPAIRS = {
    "\u00e2\u20ac\u00a2": "\u2022",
    "\u00e2\u20ac\u2122": "\u2019",
    "\u00e2\u20ac\u0153": "\u201c",
    "\u00e2\u20ac\u009d": "\u201d",
    "\u00e2\u20ac\u201c": "\u2013",
    "\u00e2\u20ac\u201d": "\u2014",
    "\u00e2\u201a\u00b9": "\u20b9",
}


def repair_known_mojibake(text: str) -> str:
    """Repair only documented UTF-8-as-Latin-1 artifacts at the final boundary."""

    value = text
    for corrupted, intended in _MOJIBAKE_REPAIRS.items():
        value = value.replace(corrupted, intended)
    return value


def validate_whatsapp_response(text: str) -> tuple[bool, tuple[str, ...]]:
    """Validate presentation without deciding whether facts are approved."""
    errors: list[str] = []
    if not isinstance(text, str) or not text.strip(): errors.append("empty")
    if "|" in text and "\n" in text: errors.append("markdown_table")
    if _INTERNAL.search(text): errors.append("internal_reference")
    if contains_governance_language(text): errors.append("governance_language")
    if text.count("•") > 5: errors.append("excessive_bullets")
    if text.count("*") % 2: errors.append("malformed_bold")
    if any(len(line) > 360 for line in text.splitlines()): errors.append("overlong_line")
    return not errors, tuple(errors)


def _display_name(service_display_name: str | None, service_code: str | None) -> str | None:
    if isinstance(service_display_name, str) and service_display_name.strip(): return service_display_name.strip()
    if isinstance(service_code, str) and service_code.strip(): return service_code.replace("_", " ").title()
    return None


def _sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    values = [item.strip(" •\t") for item in _SENTENCE.split(clean) if item.strip(" •\t")]
    # Existing line-separated facts are already more reliable than splitting.
    lines = [item.strip(" •\t") for item in text.splitlines() if item.strip(" •\t")]
    return lines if len(lines) > 1 else values


def format_whatsapp_response(*, text: str, intent: str | None, response_mode: str | None,
                             service_code: str | None, service_display_name: str | None,
                             topic: str | None, language: str | None,
                             requires_handover: bool = False) -> str:
    """Render already-approved text into a compact WhatsApp message.

    This function never retrieves evidence, creates facts, or changes route
    decisions.  If text cannot safely become bullets it stays concise prose.
    """
    value = repair_known_mojibake(text.strip()) if isinstance(text, str) else ""
    if not value: return value
    lowered = value.casefold()
    if intent == "greeting":
        return value.splitlines()[0].strip()
    if any(token in lowered for token in ("youâ€™re welcome", "you're welcome", "happy to help", "aapka swagat")):
        return value.splitlines()[0].strip()
    if requires_handover or response_mode == "human_handover":
        # Existing handover wording and contact details are approved; only add
        # a compact heading when it is absent.
        if value.startswith("*"): return value
        heading = "*Price & Booking*" if intent in {"pricing", "booking", "availability", "payment"} else "*Entartica Team Assistance*"
        return f"{heading}\n\n{value}"
    if intent == "location" and "Google Maps:" in value and " is located at " in value:
        name, remainder = value.split(" is located at ", 1)
        address, maps = remainder.split("Google Maps:", 1)
        name, address, maps = name.strip(), address.strip().rstrip("."), maps.strip()
        if name and address and maps:
            return f"*{name}*\n\n📍 {address}\n\n🗺️ Google Maps: {maps}"
    if _INTERNAL.search(value) or contains_governance_language(value):
        # Defensive fail-closed display; routing retains its original safe
        # fallback rather than exposing authoring instructions.
        return "I can help with the approved overview, duration, timings, inclusions, or suitability for this experience. What would you like to know?"
    facts = _sentences(value)
    if len(facts) < 2 or len(facts) > 5:
        return value
    service = _display_name(service_display_name, service_code)
    label = _TOPIC_LABELS.get(topic or "")
    if topic == "how_it_works" and service:
        heading = f"*How the {service} Works*"
    elif label and service and topic == "duration":
        heading = f"*{service} {label}*"
    elif label:
        heading = f"*{label}*"
    elif service:
        heading = f"*{service}*"
    else:
        return value
    rendered = f"{heading}\n\n" + "\n".join(f"• {fact}" for fact in facts[:5])
    valid, _ = validate_whatsapp_response(rendered)
    return rendered if valid else value
