"""Exotel-specific webhook validation and payload normalization."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
import re
from typing import Any

from app.schemas.exotel_webhook import (
    NormalizedInboundMessage,
    ExotelWhatsAppEnvelope,
    ExotelWhatsAppMessageInput,
)


class ExotelPayloadError(ValueError):
    """Raised when an inbound Exotel payload cannot be normalized."""


class ExotelAccountSidError(ExotelPayloadError):
    """Raised when the payload does not belong to the configured account."""


def validate_exotel_signature(
    raw_body: bytes,
    signature: str | None,
    signing_secret: str | None,
    *,
    enabled: bool,
) -> bool:
    """Validate an HMAC-SHA256 signature when the account requires it."""

    if not enabled:
        return True
    if not signature or not signing_secret:
        return False

    expected = hmac.new(
        signing_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def normalize_exotel_payload(payload: dict[str, Any]) -> list[NormalizedInboundMessage]:
    """Normalize only incoming messages from the confirmed Exotel envelope."""

    try:
        envelope = ExotelWhatsAppEnvelope.model_validate(payload)
    except Exception as error:
        raise ExotelPayloadError("Unsupported Exotel payload envelope.") from error

    messages = envelope.whatsapp.messages
    return [
        _normalize_whatsapp_message(message)
        for message in messages
        if message.callback_type == "incoming_message"
    ]


def _normalize_whatsapp_message(
    message: ExotelWhatsAppMessageInput,
) -> NormalizedInboundMessage:
    """Normalize one confirmed Exotel WhatsApp message without retaining extras."""

    customer_number = _normalize_phone(message.from_)
    business_number = _normalize_phone(message.to)
    message_type = _message_type_from_content(message.content)
    content = _content_from_message(message.content, message_type)
    if message_type == "flow":
        _parse_flow_response_json(message.content)

    return NormalizedInboundMessage(
        external_message_id=message.sid
        or _fallback_message_id(
            callback_type=message.callback_type,
            customer_number=customer_number,
            business_number=business_number,
            received_at=message.timestamp,
            message_type=message_type,
            content=content,
        ),
        customer_whatsapp_number=customer_number,
        business_whatsapp_number=business_number,
        profile_name=message.profile_name,
        message_type=message_type,
        content=content,
        received_at=_as_utc(message.timestamp),
    )


def _normalize_phone(value: str) -> str:
    normalized = re.sub(r"[\s()\-]", "", value)
    if not re.fullmatch(r"\+?[1-9][0-9]{7,14}", normalized):
        raise ExotelPayloadError("Invalid WhatsApp number.")
    return normalized if normalized.startswith("+") else f"+{normalized}"


def _message_type_from_content(content: dict[str, Any]) -> str:
    value = content.get("type")
    if value == "text":
        return "text"
    if value == "interactive":
        interactive = content.get("interactive")
        if isinstance(interactive, dict) and interactive.get("type") == "flow":
            return "flow"
    return "other"


def _content_from_message(content: dict[str, Any], message_type: str) -> str | None:
    if message_type == "text":
        text = content.get("text")
        if isinstance(text, dict):
            body = text.get("body")
            return body if isinstance(body, str) else None
    if message_type == "flow":
        interactive = content.get("interactive")
        if isinstance(interactive, dict):
            nfm_reply = interactive.get("nfm_reply")
            if isinstance(nfm_reply, dict):
                body = nfm_reply.get("body")
                return body if isinstance(body, str) else None
    return None


def _parse_flow_response_json(content: dict[str, Any]) -> dict[str, Any] | None:
    """Validate a Flow response without persisting or logging its form values."""

    interactive = content.get("interactive")
    if not isinstance(interactive, dict):
        return None
    nfm_reply = interactive.get("nfm_reply")
    if not isinstance(nfm_reply, dict):
        return None
    value = nfm_reply.get("response_json")
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _fallback_message_id(
    *,
    callback_type: str,
    customer_number: str,
    business_number: str,
    received_at: datetime,
    message_type: str,
    content: str | None,
) -> str:
    """Build a deterministic ID from the minimum canonical message fields."""

    canonical = json.dumps(
        {
            "callback_type": callback_type,
            "from": customer_number,
            "to": business_number,
            "timestamp": _as_utc(received_at).isoformat(),
            "message_type": message_type,
            "content": content,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Return an aware timestamp in UTC."""

    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
