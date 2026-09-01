"""Validated ECHT Connect chatbot webhook and callback contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EchtConnectInbound(BaseModel):
    """One CRM-owned inbound WhatsApp message."""

    event: str
    mode: Literal["active", "shadow"]
    number_id: str = Field(alias="numberId", min_length=1)
    conversation_id: str = Field(alias="conversationId", min_length=1)
    message_id: str = Field(alias="messageId", min_length=1)
    customer_id: str = Field(alias="customerId", min_length=1)
    customer_phone: str = Field(alias="customerPhone", min_length=7)
    customer_name: str | None = Field(default=None, alias="customerName")
    business_phone: str | None = Field(default=None, alias="businessPhone")
    message_type: str = Field(alias="messageType")
    message_text: str | None = Field(default=None, alias="messageText")
    timestamp: datetime
    is_new_conversation: bool = Field(alias="isNewConversation")
    is_new_customer: bool = Field(alias="isNewCustomer")
    recent_history: list[dict[str, object]] | None = Field(default=None, alias="recentConversationHistory")
    bot_profile_id: str | None = Field(default=None, alias="botProfileId")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class EchtConnectReply(BaseModel):
    """Callback body accepted by the CRM per-number reply endpoint."""

    conversation_id: str = Field(alias="conversationId")
    in_reply_to_message_id: str = Field(alias="inReplyToMessageId")
    reply: str | None = None
    handover: bool = False
    handover_reason: str | None = Field(default=None, alias="handoverReason")

    model_config = ConfigDict(populate_by_name=True)
