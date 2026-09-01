"""Exotel webhook input envelopes and provider-neutral message data."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExotelWhatsAppMessageInput(BaseModel):
    """One Exotel WhatsApp message from the confirmed dashboard envelope."""

    callback_type: str
    sid: str | None = None
    from_: str = Field(alias="from")
    to: str
    timestamp: datetime
    profile_name: str | None = None
    content: dict[str, Any]

    model_config = ConfigDict(extra="allow")


class ExotelWhatsAppPayload(BaseModel):
    """WhatsApp payload data, allowing additional provider fields."""

    messages: list[ExotelWhatsAppMessageInput]

    model_config = ConfigDict(extra="allow")


class ExotelWhatsAppEnvelope(BaseModel):
    """The confirmed ``whatsapp.messages`` Exotel webhook envelope."""

    whatsapp: ExotelWhatsAppPayload

    model_config = ConfigDict(extra="allow")


class NormalizedInboundMessage(BaseModel):
    """Provider-neutral inbound message used beyond the adapter layer."""

    external_provider: Literal["exotel", "echt_connect"] = "exotel"
    external_message_id: str
    customer_whatsapp_number: str
    business_whatsapp_number: str
    profile_name: str | None = None
    message_type: Literal[
        "text", "flow", "other"
    ]
    content: str | None = None
    form_response: dict[str, Any] | None = None
    received_at: datetime
