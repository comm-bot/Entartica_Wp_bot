"""Local, source-grounded Raipur answer assembly with no WhatsApp dependency."""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any

@dataclass(frozen=True)
class RaipurAnswer:
    answer: str | None
    human_handover_required: bool
    confidence: float | None
    source_filenames: tuple[str, ...]


_METADATA_LABELS = {
    "document version", "version", "approval date", "status",
    "approved for chatbot ingestion", "document title", "source",
    "source file", "filename", "general", "location information",
    "service information", "services", "faq", "internal notes", "metadata",
}
_METADATA_PREFIX = re.compile(
    r"^(?:document\s+version|version|approval\s+date|status|document\s+title|source(?:\s+reference|\s+file)?|filename|internal\s+notes|metadata|intent|service|automatic\s+reply\s+allowed|human\s+handover\s+required|document|page|verification\s+status|customer\s+facing|catalogue\s+status|content\s+status|answer)\s*[:\-]",
    re.IGNORECASE,
)
_LOCATION = re.compile(r"\braipur\s*,\s*chhattisgarh\b", re.IGNORECASE)
_HINGLISH = re.compile(r"\b(kahan|kahaan|hai|kya|mein|ka|batao)\b", re.IGNORECASE)
_INTERNAL_RESPONSE_LABEL = re.compile(r"^(?:suggested|sample|example|expected)\s+(?:chatbot\s+)?response\s*:?$|^(?:when\s+a\s+guest\s+asks|customer\s+asks|the\s+chatbot\s+should)\s*:?.*$|^(?:internal\s+guidance|response\s+guidance|chatbot\s+instructions)\s*:?$", re.IGNORECASE)
_INTERNAL_RESPONSE_PHRASE = re.compile(r"(?:when\s+a\s+guest\s+asks|suggested\s+chatbot\s+response|sample\s+(?:chatbot\s+)?response|expected\s+response|internal\s+guidance|the\s+chatbot\s+should|customer\s+asks)", re.IGNORECASE)


def is_internal_example_section(heading: object) -> bool:
    return isinstance(heading, str) and bool(_INTERNAL_RESPONSE_PHRASE.search(heading))


def clean_customer_evidence(content: str) -> str:
    """Remove only document-authoring wrappers around approved factual text."""

    lines: list[str] = []
    for raw in content.replace("\r", "\n").split("\n"):
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", raw).strip()
        line = re.sub(r"^(?:\*\*|__|\*|_)+|(?:\*\*|__|\*|_)+$", "", line).strip()
        if not line or _INTERNAL_RESPONSE_LABEL.match(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def compose_customer_response(content: str, *, question: str = "", language: str | None = None) -> str | None:
    """Return concise approved facts only; never expose retrieval formatting or metadata."""

    if re.search(r"\b(price|pricing|payment|booking\s+confirmation|refund|cancel(?:lation)?|complaint|availability)\b|\bavailable\b.{0,50}\b(?:today|tomorrow|date|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", question, re.IGNORECASE):
        return None
    facts = _factual_lines(content)
    if not facts:
        return None
    intent = _intent(question)
    topic = _topic(question)
    if intent == "location":
        location = _location_fact(facts)
        if location is None:
            return None
        if language == "hi" or any("\u0900" <= char <= "\u097f" for char in question):
            return "हमारा स्थान रायपुर, छत्तीसगढ़ में है। कृपया बताएं कि आपको किस गतिविधि या सेवा की जानकारी चाहिए।"
        if language == "hinglish" or _HINGLISH.search(question):
            return "Hamari location Raipur, Chhattisgarh mein hai. Aap kis activity ya service ki information chahte hain?"
        return "Our location is in Raipur, Chhattisgarh. Please let me know which activity or service you would like information about."

    relevant = _relevant_facts(facts, intent, topic)
    if not relevant:
        return None
    return _sanitize_final_answer(_concise_text(relevant, intent=intent, topic=topic))


def compose_venue_overview(content: str) -> str | None:
    """Compose a venue introduction from approved general-document facts only."""

    facts = _factual_lines(content)
    safe = [
        fact for fact in facts
        if not re.search(r"\b(?:price|pricing|payment|booking|refund|cancel|availability|contact)\b", fact, re.I)
    ]
    identity = next(
        (
            fact for fact in safe
            if "entartica sea world" in fact.casefold()
            and any(term in fact.casefold() for term in ("destination", "activity", "celebration", "water-based", "water based"))
        ),
        None,
    )
    experiences = next(
        (
            fact for fact in safe
            if any(term in fact.casefold() for term in ("offers", "experiences", "water sports", "water activities", "celebration experiences"))
            and any(term in fact.casefold() for term in ("jet ski", "speed boat", "kayak", "celebration", "package"))
        ),
        None,
    )
    if identity is None or experiences is None:
        return None
    return _sanitize_final_answer(" ".join((identity, experiences)))


def _factual_lines(content: str) -> list[str]:
    if not isinstance(content, str):
        return []
    answer_block = _answer_block(content)
    if answer_block is not None:
        content = answer_block
    content = clean_customer_evidence(content)
    lines = [" ".join(line.split()) for line in content.replace("\r", "\n").split("\n")]
    facts: list[str] = []
    skip_next = False
    for line in lines:
        if not line:
            continue
        normalized = line.casefold().strip(":- ")
        if skip_next:
            skip_next = False
            continue
        if normalized in _METADATA_LABELS:
            # Labels such as "Document Version" are commonly followed by their value.
            skip_next = normalized not in {"general", "location information", "approved for chatbot ingestion"}
            continue
        if _METADATA_PREFIX.match(line) or "approved for chatbot ingestion" in normalized:
            continue
        if re.search(r"\b(source|filename|document\s+id|chunk\s+id|confidence|embedding|retrieval\s+score)\b", line, re.IGNORECASE):
            continue
        if re.search(r"\.(?:docx?|pdf)\b", line, re.IGNORECASE) or "/" in line or "\\" in line:
            continue
        # Evidence often arrives as one Markdown paragraph.  Preserve sentence
        # boundaries so a requested fact later in that paragraph can be ranked
        # before a generic introductory sentence.
        facts.extend(
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", line)
            if sentence.strip()
        )
    if len(facts) == 1 and facts[0].endswith("?"):
        return []
    return facts


def _answer_block(content: str) -> str | None:
    """Extract customer-facing text from structured FAQ content, never its metadata."""

    lines = content.replace("\r", "\n").split("\n")
    start = next((index for index, line in enumerate(lines) if re.match(r"^\s*answer\s*:\s*$", line, re.I)), None)
    if start is None:
        return None
    answer: list[str] = []
    for line in lines[start + 1:]:
        if re.match(r"^\s*(?:source(?:\s+reference|\s+file)?|document|page|verification\s+status|customer\s+facing|catalogue\s+status|content\s+status|intent|service|automatic\s+reply\s+allowed|human\s+handover\s+required)\s*:", line, re.I):
            break
        if line.strip(): answer.append(line.strip())
    return "\n".join(answer).strip()


def _intent(question: str) -> str:
    value = question.casefold()
    if any(term in value for term in ("activity", "activities", "service", "services", "ride", "boating", "staycation", "daycation")):
        return "services"
    if any(term in value for term in ("where", "located", "location", "address", "map", "raipur")):
        return "location"
    return "general"


def _location_fact(facts: list[str]) -> str | None:
    for fact in facts:
        if _LOCATION.search(fact):
            return "Raipur, Chhattisgarh"
    return None


def _topic(question: str) -> str:
    value = question.casefold()
    topics = {
        "capacity": ("capacity", "how many", "kitne", "people", "guests", "beth sakte"),
        "duration": ("duration", "how long", "kitna time", "minutes", "hours"),
        "inclusions": ("include", "included", "inclusion", "what is included"),
        "swimming": ("swimming", "swim"),
        "safety": ("safety", "safe", "life jacket", "pregnan", "medical"),
        "operating_hours": ("operating", "opening", "closing", "timing", "hours"),
        "more_details": ("more details", "tell me more", "aur batao", "more information"),
    }
    return next((name for name, terms in topics.items() if any(term in value for term in terms)), "overview")


def _relevant_facts(facts: list[str], intent: str, topic: str) -> list[str]:
    topic_terms = {
        "capacity": ("capacity", "people", "guest", "person", "participant", "seating", "accommodat", "up to", "log"),
        "duration": ("duration", "minute", "hour", "session", "time"),
        "inclusions": ("include", "included", "inclusion", "access", "voucher", "package"),
        "swimming": ("swimming", "swim"),
        "safety": ("safety", "safe", "life jacket", "pregnan", "medical", "restriction"),
        "operating_hours": ("operating", "opening", "closing", "timing", "hours"),
        "overview": ("definition", "overview", "experience", "service", "ride", "package", "staycation", "daycation"),
        "more_details": ("how it works", "feature", "suitable", "duration", "capacity", "included", "safety"),
    }
    if topic == "more_details":
        # The retriever has already ranked additional operational sections
        # ahead of definitions for follow-ups; preserve that approved order.
        return facts
    terms = topic_terms[topic]
    ranked = sorted(
        enumerate(facts),
        key=lambda item: (-sum(term in item[1].casefold() for term in terms), item[0]),
    )
    matching = [fact for _index, fact in ranked if any(term in fact.casefold() for term in terms)]
    if topic == "overview" and intent != "services":
        return facts
    return matching + [fact for fact in facts if fact not in matching]


def _concise_text(facts: list[str], *, intent: str, topic: str) -> str | None:
    text = " ".join(facts)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    sentences = [sentence for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
    sentence_limit = 5 if topic == "overview" and intent == "services" else 4 if topic != "overview" else 3
    character_limit = 1_000 if topic == "overview" and intent == "services" else 700
    return " ".join(sentences[:sentence_limit])[:character_limit].strip() or None


def _sanitize_final_answer(answer: str | None) -> str | None:
    if not isinstance(answer, str):
        return None
    cleaned = clean_customer_evidence(answer)
    return cleaned if cleaned and not _INTERNAL_RESPONSE_PHRASE.search(cleaned) else None

def generate_raipur_answer(result: dict[str, Any] | None, *, low_confidence: bool) -> RaipurAnswer:
    """Compose only sanitized approved facts; never expose raw retrieval chunks."""
    if low_confidence or not result or not isinstance(result.get("content"), str):
        return RaipurAnswer(None, True, None, ())
    source = result.get("source_filename")
    score = result.get("score")
    content = result["content"].strip()
    if not content or not isinstance(source, str) or not isinstance(score, (int, float)):
        return RaipurAnswer(None, True, None, ())
    answer = compose_customer_response(content, question=result.get("question", ""))
    if not answer:
        return RaipurAnswer(None, True, None, ())
    return RaipurAnswer(answer, False, float(score), (source,))
