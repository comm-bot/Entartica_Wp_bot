"""Inbound Exotel WhatsApp webhook endpoint."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.integrations.exotel import ExotelPayloadError, normalize_exotel_payload, validate_exotel_signature
from app.integrations.supabase import get_supabase_client
from app.services.inbound_messages import InboundMessageService


router = APIRouter(prefix="/webhooks/exotel", tags=["exotel"])
logger = logging.getLogger(__name__)


def get_inbound_message_service() -> InboundMessageService:
    """Create the service used by the inbound webhook."""

    return InboundMessageService(get_supabase_client())


@router.post("/inbound", status_code=200)
async def receive_inbound_message(request: Request) -> Response:
    """Validate, normalize, and persist one inbound Exotel message."""

    raw_body = await request.body()
    settings = get_settings()
    signature = request.headers.get("X-Exotel-Signature")
    secret = (
        settings.exotel_api_token.get_secret_value()
        if settings.exotel_api_token is not None
        else None
    )
    if not validate_exotel_signature(
        raw_body,
        signature,
        secret,
        enabled=settings.exotel_signature_validation_enabled,
    ):
        logger.warning("exotel_webhook_signature_rejected")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ExotelPayloadError("Webhook body must be an object.")
        messages = normalize_exotel_payload(payload)
    except json.JSONDecodeError:
        logger.warning("exotel_webhook_invalid_json")
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    except ExotelPayloadError:
        logger.warning("exotel_webhook_payload_rejected")
        raise HTTPException(status_code=422, detail="Invalid payload") from None

    if not messages:
        return Response(status_code=200)

    try:
        async with asyncio.timeout(4.5):
            service = get_inbound_message_service()
            for message in messages:
                await run_in_threadpool(service.process, message)
    except TimeoutError:
        logger.error("exotel_webhook_persistence_timed_out")
        raise HTTPException(status_code=503, detail="Unable to process webhook") from None
    except Exception:
        logger.error("exotel_webhook_persistence_failed")
        raise HTTPException(status_code=500, detail="Unable to process webhook") from None

    return Response(status_code=200)
