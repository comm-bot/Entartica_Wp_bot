"""Deterministic recognition for approved Entartica contact requests."""
from __future__ import annotations

import re


_CONTACT_REQUEST = re.compile(
    r"\b(?:contact|phone|mobile|whatsapp|customer\s*care|sales)\s*(?:contact|number|no\.?|details?|email(?:\s+address)?)\b"
    r"|\bemail\s+address\b"
    r"|\b(?:send|give)(?:\s+me)?\s+(?:(?:their|the|your)\s+)?(?:contact\s+)?number\b"
    r"|\b(?:can\s+you\s+)?send\s+(?:me\s+)?(?:(?:their|the|your)\s+)?number\b"
    r"|\b(?:their|unka|team\s+ka|sales\s+team\s+ka)\s+(?:contact\s+)?(?:number|no\.?|email)\b"
    r"|\bhow\s+can\s+i\s+contact\s+(?:you|entartica|them|the\s+team)\b"
    r"|\b(?:number|contact\s+number)\s+(?:bhejo|batao|send\s+karo|send\s+kro|do)\b"
    r"|\bcall\s+karne\s+ka\s+number\b"
    r"|\bgive\s+me\s+(?:their\s+)?contact\b",
    re.IGNORECASE,
)


def is_contact_information_request(message: str) -> bool:
    """Return true only for an explicit request for Entartica contact details."""
    return isinstance(message, str) and bool(_CONTACT_REQUEST.search(message.casefold().strip()))
