"""Validated provider-neutral delivery-status callback data."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ExotelDeliveryCallbackMessage(BaseModel):
    """Confirmed Exotel WhatsApp DLR callback message."""

    callback_type: str
    message_sid: str | None = None
    client_sid: str | None = None
    exo_status_code: str | None = None
    exo_detailed_status: str | None = None
    description: str | None = None
    timestamp: datetime | None = None
    custom_data: str | None = None

    model_config = ConfigDict(extra="allow")


class ExotelDeliveryEnvelopeData(BaseModel):
    """The WhatsApp delivery callback collection."""

    messages: list[ExotelDeliveryCallbackMessage]

    model_config = ConfigDict(extra="allow")


class ExotelDeliveryEnvelope(BaseModel):
    """The observed Exotel ``whatsapp.messages`` callback envelope."""

    whatsapp: ExotelDeliveryEnvelopeData

    model_config = ConfigDict(extra="allow")


class NormalizedDeliveryStatus(BaseModel):
    """Safe delivery-status data used by persistence code."""

    provider_message_id: str | None = None
    internal_message_id: str | None = None
    status: Literal["sent", "delivered", "read", "failed"] | None = None
    occurred_at: datetime | None = None
    failure_code: str | None = None
    failure_description: str | None = None
