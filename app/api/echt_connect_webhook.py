"""Dedicated inbound/callback bridge for CRM-owned WhatsApp numbers."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.exotel_webhook import (
    get_inbound_message_service,
    get_raipur_draft_sender,
    get_raipur_inbound_orchestrator,
)
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
from app.services.coimbatore.customer_details import customer_details_complete
from app.integrations.supabase import get_supabase_client
from app.repositories.outbound_drafts import OutboundDraftRepository
from app.services.raipur_automatic_replies import attempt_automatic_reply
from app.services.raipur_draft_integration import create_draft_after_orchestration


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


async def send_echt_orchestration_via_exotel(
    *, inbound_message, customer, conversation, message,
    orchestration, settings, orchestrator,
) -> bool:
    """Send one CRM-originated bot result through the durable Exotel pipeline."""
    repository = OutboundDraftRepository(get_supabase_client())
    draft_result = await run_in_threadpool(
        create_draft_after_orchestration,
        settings=settings,
        inbound_message=inbound_message,
        customer=customer,
        conversation=conversation,
        orchestration=orchestration,
        repository_factory=lambda: repository,
    )
    if not draft_result.draft_saved or not isinstance(inbound_message, dict):
        logger.warning(
            "echt_connect_exotel_send_skipped reason=%s draft_saved=%s",
            draft_result.reason_code, draft_result.draft_saved,
        )
        return False
    draft = await run_in_threadpool(
        repository.find_draft_for_inbound_message,
        inbound_message.get("id", ""),
    )
    automatic = await attempt_automatic_reply(
        settings=settings,
        orchestration=orchestration,
        draft=draft,
        recipient=message.customer_whatsapp_number,
        repository=repository,
        sender_factory=lambda: get_raipur_draft_sender(repository, settings),
    )
    if automatic.response_sent and hasattr(orchestrator, "confirm_standard_package_presented"):
        try:
            await run_in_threadpool(
                orchestrator.confirm_standard_package_presented,
                orchestration,
                customer["id"],
                conversation["id"],
            )
        except Exception:
            logger.exception(
                "echt_connect_package_acceptance_state_failed message_id=%s",
                message.external_message_id,
            )
    logger.info(
        "echt_connect_exotel_reply_completed attempted=%s response_sent=%s reason=%s",
        automatic.attempted, automatic.response_sent, automatic.reason,
    )
    return automatic.response_sent


async def process_echt_connect_background(
    inbound: EchtConnectInbound,
    credentials: EchtConnectNumberCredentials,
    settings,
) -> None:
    """Persist CRM inbound, send bot output via Exotel, and notify handover."""
    try:
        supported_text_type = inbound.message_type.casefold() in {
            "text", "button", "button_reply", "interactive", "list_reply",
        }
        message = NormalizedInboundMessage(
            external_provider="echt_connect",
            external_message_id=inbound.message_id,
            customer_whatsapp_number=_phone(inbound.customer_phone),
            business_whatsapp_number=_phone(inbound.business_phone or credentials.business_phone),
            profile_name=inbound.customer_name,
            message_type="text" if supported_text_type and inbound.message_text else "other",
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
            # Exotel owns the native customer-details Flow because the current
            # CRM callback accepts only text/handover. Suppress the CRM reply
            # until that Flow has persisted the customer's completed details.
            if persisted.customer is not None and not customer_details_complete(persisted.customer):
                logger.info(
                    "echt_connect_reply_suppressed reason=customer_details_incomplete number_id=%s",
                    inbound.number_id,
                )
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
            if inbound.mode != "active":
                logger.info(
                    "echt_connect_outbound_suppressed reason=shadow_mode number_id=%s",
                    inbound.number_id,
                )
                return
            response_valid = bool(getattr(result, "response_valid", True))
            handover = bool(result.human_handover_required) or not response_valid
            await send_echt_orchestration_via_exotel(
                inbound_message=persisted.inbound_message,
                customer=persisted.customer,
                conversation=persisted.conversation,
                message=message,
                orchestration=result,
                settings=settings,
                orchestrator=orchestrator,
            )
            if handover:
                reason = result.reason_code if response_valid else "invalid_chatbot_response"
                callback = EchtConnectReply(
                    conversationId=inbound.conversation_id,
                    inReplyToMessageId=inbound.message_id,
                    handover=True,
                    handoverReason=reason,
                )
                await EchtConnectClient(
                    timeout_seconds=float(getattr(settings, "echt_connect_callback_timeout_seconds", 10.0))
                ).send_reply(credentials, callback)
                logger.info(
                    "echt_connect_handover_callback_accepted number_id=%s mode=%s",
                    inbound.number_id, inbound.mode,
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
