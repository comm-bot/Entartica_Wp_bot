"""Exotel WhatsApp delivery-status callback endpoint."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.integrations.exotel import (
    ExotelPayloadError,
    normalize_delivery_callbacks,
    validate_exotel_signature,
)
from app.integrations.supabase import get_supabase_client
from app.services.delivery_status import DeliveryStatusService
from app.services.latency import LatencyTrace


router = APIRouter(prefix="/webhooks/exotel", tags=["exotel"])
logger = logging.getLogger("uvicorn.error")


def get_delivery_status_service() -> DeliveryStatusService:
    """Create the delivery-status persistence service."""

    return DeliveryStatusService(get_supabase_client())


@router.post("/status", status_code=200)
async def receive_delivery_status(request: Request) -> Response:
    """Persist observed Exotel DLR callbacks without retaining raw payloads."""

    trace = LatencyTrace()
    logger.info("webhook_received request_id=%s endpoint=status", trace.request_id)
    raw_body = await request.body()
    settings = get_settings()
    secret = (
        settings.exotel_api_token.get_secret_value()
        if settings.exotel_api_token is not None
        else None
    )
    if not validate_exotel_signature(
        raw_body,
        request.headers.get("X-Exotel-Signature"),
        secret,
        enabled=settings.exotel_signature_validation_enabled,
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        with trace.stage("payload_validation"):
            payload = await _callback_payload(request, raw_body)
    except ValueError:
        logger.warning("exotel_webhook_body_malformed endpoint=status")
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    try:
        callbacks = normalize_delivery_callbacks(payload)
        if not callbacks:
            logger.info("exotel_event_skipped endpoint=status")
            return Response(status_code=200)
        service = get_delivery_status_service()
        for callback in callbacks:
            if not callback.provider_message_id:
                logger.info("exotel_event_skipped endpoint=status reason=missing_provider_identifier")
                continue
            with trace.stage("duplicate_check"):
                updated = await run_in_threadpool(service.process, callback)
            logger.info("exotel_status_callback_%s request_id=%s", "processed" if updated else "duplicate", trace.request_id)
    except Exception:
        logger.error("exotel_status_callback_processing_failed_safe request_id=%s", trace.request_id)
    trace.summary(intent="delivery_status", response_mode="callback", response_basis="none")
    return Response(status_code=200)


async def _callback_payload(request: Request, raw_body: bytes) -> dict:
    """Read JSON, form, or multipart callbacks without retaining their values."""

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type or not content_type:
        value = json.loads(raw_body)
        if not isinstance(value, dict):
            raise ValueError
        return value
    if "multipart/form-data" in content_type:
        values = _multipart_text_fields(raw_body, content_type)
        if "payload" in values:
            value = json.loads(values["payload"])
            if isinstance(value, dict):
                return value
        return values
    if "application/x-www-form-urlencoded" in content_type:
        values = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
        if "payload" in values:
            value = json.loads(values["payload"][0])
            if isinstance(value, dict):
                return value
        return {key: entries[0] for key, entries in values.items() if entries}
    raise ValueError


def _multipart_text_fields(raw_body: bytes, content_type: str) -> dict[str, str]:
    """Parse only ordinary multipart text fields; callbacks never need uploads."""

    boundary_match = re.search(r"boundary=([^;]+)", content_type, re.I)
    if boundary_match is None:
        raise ValueError
    boundary = boundary_match.group(1).strip().strip('"').encode("utf-8")
    values: dict[str, str] = {}
    for part in raw_body.split(b"--" + boundary):
        headers, separator, value = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        name_match = re.search(br'name="([^"\r\n]+)"', headers)
        if name_match is None:
            continue
        try:
            name = name_match.group(1).decode("utf-8")
            values[name] = value.rstrip(b"\r\n-").decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError from None
    return values
