"""Dedicated inbound/callback bridge for CRM-owned WhatsApp numbers."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.exotel_webhook import get_inbound_message_service, get_raipur_inbound_orchestrator
from app.config import get_settings
from app.integrations.echt_connect import (
    EchtConnectCallbackError,
    EchtConnectClient,
    EchtConnectConfigurationError,
    EchtConnectNumberCredentials,
    number_credentials,
    validate_signature,
)
from app.schemas.echt_connect import EchtConnectInbound, EchtConnectReply
from app.schemas.exotel_webhook import NormalizedInboundMessage


router = APIRouter(prefix="/webhooks/echt-connect", tags=["echt-connect"])
logger = logging.getLogger("uvicorn.error")
_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


def _phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if not 7 <= len(digits) <= 15:
        raise ValueError("invalid_phone")
    return f"+{digits}"


async def _conversation_lock(conversation_id: str) -> asyncio.Lock:
    async with _locks_guard:
        return _locks.setdefault(conversation_id, asyncio.Lock())


async def process_echt_connect_background(
    inbound: EchtConnectInbound,
    credentials: EchtConnectNumberCredentials,
    settings,
) -> None:
    """Persist, orchestrate and call CRM without entering Exotel outbound."""
    try:
        message = NormalizedInboundMessage(
            external_provider="echt_connect",
            external_message_id=inbound.message_id,
            customer_whatsapp_number=_phone(inbound.customer_phone),
            business_whatsapp_number=_phone(inbound.business_phone or credentials.business_phone),
            profile_name=inbound.customer_name,
            message_type="text" if inbound.message_type.casefold() == "text" else "other",
            content=inbound.message_text,
            received_at=inbound.timestamp,
        )
        lock = await _conversation_lock(inbound.conversation_id)
        async with lock:
            service = get_inbound_message_service()
            persisted = await run_in_threadpool(service.process, message)
            if persisted.duplicate:
                logger.info("echt_connect_duplicate_skipped number_id=%s", inbound.number_id)
                return
            if message.message_type != "text" or persisted.customer is None or persisted.conversation is None:
                logger.info("echt_connect_message_skipped reason=unsupported_type number_id=%s", inbound.number_id)
                return
            orchestrator = await run_in_threadpool(get_raipur_inbound_orchestrator)
            result = await run_in_threadpool(
                orchestrator.process,
                message,
                customer=persisted.customer,
                conversation=persisted.conversation,
                source_message_id=message.external_message_id,
            )
            response_valid = bool(getattr(result, "response_valid", True))
            handover = bool(result.human_handover_required) or not response_valid
            reason = result.reason_code if response_valid else "invalid_chatbot_response"
            reply_text = (
                result.draft_text
                if response_valid
                else "Our team will assist you shortly."
            )
            callback = EchtConnectReply(
                conversationId=inbound.conversation_id,
                inReplyToMessageId=inbound.message_id,
                reply=reply_text,
                handover=handover,
                handoverReason=reason,
            )
            await EchtConnectClient(
                timeout_seconds=float(getattr(settings, "echt_connect_callback_timeout_seconds", 10.0))
            ).send_reply(credentials, callback)
            logger.info(
                "echt_connect_callback_accepted number_id=%s mode=%s handover=%s",
                inbound.number_id, inbound.mode, handover,
            )
    except (EchtConnectCallbackError, EchtConnectConfigurationError):
        logger.exception("echt_connect_background_failed category=callback_or_configuration")
    except Exception:
        logger.exception("echt_connect_background_failed category=processing")


@router.post("/inbound", status_code=202)
async def receive_echt_connect(request: Request, background_tasks: BackgroundTasks) -> Response:
    """Authenticate one CRM request and acknowledge before slow processing."""
    settings = get_settings()
    if not bool(getattr(settings, "echt_connect_enabled", False)):
        raise HTTPException(status_code=503, detail="ECHT Connect integration disabled")
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
        inbound = EchtConnectInbound.model_validate(payload)
        credentials = number_credentials(settings, inbound.number_id)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    except ValidationError:
        raise HTTPException(status_code=422, detail="Invalid ECHT Connect payload") from None
    except EchtConnectConfigurationError:
        logger.warning("echt_connect_number_rejected reason=not_configured")
        raise HTTPException(status_code=401, detail="Unauthorized") from None
    if not validate_signature(
        raw_body,
        request.headers.get("X-Chatbot-Signature"),
        credentials.webhook_secret,
    ):
        logger.warning("echt_connect_signature_rejected number_id=%s", inbound.number_id)
        raise HTTPException(status_code=401, detail="Unauthorized")
    background_tasks.add_task(process_echt_connect_background, inbound, credentials, settings)
    logger.info("echt_connect_webhook_acknowledged number_id=%s mode=%s", inbound.number_id, inbound.mode)
    return Response(status_code=202)
