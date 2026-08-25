"""Engine-neutral deterministic resolution of approved Raipur services."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.raipur_services import (
    approved_primary_service_from_question,
    approved_service_alias_used,
    approved_service_from_message,
    knowledge_service_code,
)


@dataclass(frozen=True)
class ServiceResolution:
    matched: bool = False
    service_code: str | None = None
    service_name: str | None = None
    explicit_service: bool = False
    matched_alias: bool = False
    normalized_message: str = ""
    match_type: str | None = None
    ambiguity_reason: str | None = None
    context_service_used: bool = False
    service: Any | None = None


def resolve_service(
    message: object,
    *,
    context_service_code: str | None = None,
    context_service_name: str | None = None,
    allow_context: bool = False,
) -> ServiceResolution:
    """Resolve the current explicit service before an optional stored subject."""
    text = message.strip() if isinstance(message, str) else ""
    # Existing approved aliases remain authoritative; this is a narrow
    # WhatsApp spelling normalization before those same aliases are consulted.
    text = text.replace("bumber boat", "bumper boat")
    normalized = text.casefold()
    explicit = approved_primary_service_from_question(text)
    strict = approved_service_from_message(text)
    if explicit is not None:
        return ServiceResolution(
            matched=True,
            service_code=knowledge_service_code(explicit),
            service_name=explicit.name,
            explicit_service=True,
            matched_alias=approved_service_alias_used(text),
            normalized_message=normalized,
            match_type="alias" if strict is not None and approved_service_alias_used(text) else "official_name",
            service=explicit,
        )
    if allow_context and isinstance(context_service_code, str) and context_service_code.strip() and isinstance(context_service_name, str) and context_service_name.strip():
        return ServiceResolution(
            matched=True,
            service_code=context_service_code,
            service_name=context_service_name,
            normalized_message=normalized,
            match_type="context",
            context_service_used=True,
        )
    return ServiceResolution(normalized_message=normalized)
