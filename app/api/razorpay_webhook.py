"""Authenticated Razorpay webhook endpoint."""
from __future__ import annotations

import json
import logging
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.integrations.supabase import get_supabase_client
from app.services.razorpay_webhooks import RazorpayWebhookService, verify_razorpay_signature

router = APIRouter(prefix="/webhooks", tags=["razorpay"])
logger = logging.getLogger("uvicorn.error")


def generate_and_send_confirmation(booking_id: str) -> None:
    try:
        from app.services.coimbatore.booking_confirmation import BookingConfirmationService, S3ConfirmationStorage
        from app.services.coimbatore.confirmation_delivery import ExotelConfirmationDelivery
        settings, database = get_settings(), get_supabase_client()
        result = BookingConfirmationService(
            database, S3ConfirmationStorage(settings), ExotelConfirmationDelivery(database, settings),
            razorpay_mode=settings.razorpay_mode,
            storage_prefix=settings.coimbatore_confirmation_s3_prefix,
            font_path=settings.booking_confirmation_unicode_font_path,
        ).ensure_confirmation(booking_id)
        logger.info(
            "booking_confirmation_completed booking_id=%s completed=%s reason=%s reused_pdf=%s",
            booking_id, result.completed, result.reason, result.reused_pdf,
        )
    except Exception as error:
        # Payment truth is already committed. Keep webhook/background failures
        # isolated and observable without turning the successful 200 response
        # into an ASGI exception or falsely reversing the paid state.
        logger.exception(
            "booking_confirmation_background_failed booking_id=%s exception_class=%s",
            booking_id, type(error).__name__,
        )


@router.post("/razorpay")
async def razorpay_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, object]:
    settings = get_settings()
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature")
    event_id = request.headers.get("x-razorpay-event-id")
    secret = settings.razorpay_webhook_secret.get_secret_value() if settings.razorpay_webhook_secret else ""
    if not verify_razorpay_signature(raw_body, signature, secret):
        raise HTTPException(status_code=401, detail="invalid_webhook_signature")
    if not event_id:
        raise HTTPException(status_code=400, detail="missing_provider_event_id")
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid_json")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_payload")
    status, paid, booking_id = await run_in_threadpool(
        RazorpayWebhookService(get_supabase_client()).process, event_id, payload,
    )
    if paid and booking_id:
        background_tasks.add_task(generate_and_send_confirmation, booking_id)
    return {"accepted": True, "status": status, "payment_received": paid}
