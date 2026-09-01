"""Inbound Exotel WhatsApp webhook endpoint."""

from __future__ import annotations

import json
import logging
import asyncio
import subprocess
import inspect
from time import perf_counter
from functools import lru_cache

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.integrations.exotel import ExotelPayloadError, is_exotel_event_envelope, normalize_exotel_payload, validate_exotel_signature
from app.integrations.supabase import get_supabase_client
from app.services.inbound_messages import InboundMessageService
from app.services.raipur_inbound_orchestrator import RaipurInboundOrchestrator
from app.services.coimbatore.inbound_orchestrator import CoimbatoreInboundOrchestrator
from app.repositories.outbound_drafts import OutboundDraftRepository
from app.services.raipur_draft_integration import create_draft_after_orchestration
from app.services.raipur_automatic_replies import attempt_automatic_reply
from app.services.latency import LatencyTrace, latency_stage, use_latency_trace
from app.services.coimbatore.customer_details import customer_details_complete
from app.services.coimbatore.pontoon_package import action_id as coimbatore_package_action_id
from app.integrations.lead_email import SmtpLeadEmailNotifier, lead_email_from_context


router = APIRouter(prefix="/webhooks/exotel", tags=["exotel"])
logger = logging.getLogger("uvicorn.error")
_conversation_locks: dict[str, asyncio.Lock] = {}
_conversation_locks_guard = asyncio.Lock()


@lru_cache(maxsize=1)
def _runtime_git_commit() -> str:
    """Return a safe local revision marker; never fail inbound processing."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True,
            text=True, timeout=1, check=True,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _safe_response_preview(value: object) -> str:
    if not isinstance(value, str):
        return "none"
    return " ".join(value.split())[:80] or "none"


async def _lock_for_inbound(message) -> asyncio.Lock:
    """Return the bounded, process-local lock for one customer conversation.

    The sender number is used only as an opaque in-memory key.  It is never
    logged or persisted by this helper; distinct customers remain concurrent.
    """
    key = getattr(message, "customer_whatsapp_number", "")
    async with _conversation_locks_guard:
        lock = _conversation_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _conversation_locks[key] = lock
        return lock


def get_inbound_message_service() -> InboundMessageService:
    """Create the service used by the inbound webhook."""

    return InboundMessageService(get_supabase_client())


@lru_cache(maxsize=1)
def get_raipur_inbound_orchestrator() -> RaipurInboundOrchestrator:
    """Compatibility-named factory selecting the configured active runtime."""
    client, settings = get_supabase_client(), get_settings()
    if getattr(settings, "active_location", None) == "coimbatore":
        return CoimbatoreInboundOrchestrator(client, settings)
    from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
    return RaipurInboundOrchestrator(client, settings, knowledge_provider=RaipurKnowledgeProvider(client, settings))


@lru_cache(maxsize=1)
def _reusable_exotel_client(account_sid: str, api_key: str, api_token: str, whatsapp_from: str, api_base_url: str):
    from app.integrations.exotel import ExotelClient
    return ExotelClient(account_sid=account_sid, api_key=api_key, api_token=api_token, whatsapp_from=whatsapp_from, api_base_url=api_base_url)


def get_raipur_draft_sender(repository: OutboundDraftRepository, settings):
    """Construct the existing sender only after an automatic reply is eligible."""
    from app.services.raipur_draft_sender import RaipurDraftSender
    values = (settings.exotel_account_sid, settings.exotel_api_key, settings.exotel_api_token, settings.exotel_whatsapp_from)
    if any(value is None for value in values): raise RuntimeError("sender_configuration_unavailable")
    exotel = _reusable_exotel_client(settings.exotel_account_sid, settings.exotel_api_key.get_secret_value(), settings.exotel_api_token.get_secret_value(), settings.exotel_whatsapp_from, settings.exotel_api_base_url)
    return RaipurDraftSender(repository, settings, exotel)


async def process_inbound_messages_background(messages, settings, trace: LatencyTrace | None = None) -> None:
    """Run slow persistence/orchestration after Exotel has received its acknowledgement."""

    trace = trace or LatencyTrace()
    trace.stages_ms["background_task_start_delay"] = trace.total_ms()
    with use_latency_trace(trace):
        trace.mark("background_task_started", event="background_task_started")
        try:
            service = get_inbound_message_service()
        except Exception:
            logger.error("exotel_inbound_background_failed operation=service_initialization request_id=%s", trace.request_id)
            trace.summary()
            return

        for message in messages:
          try:
            lock = await _lock_for_inbound(message)
            lock_wait_started = perf_counter()
            async with lock:
             trace.stages_ms["customer_lock_wait"] = trace.stages_ms.get("customer_lock_wait", 0.0) + (perf_counter() - lock_wait_started) * 1000
             trace.event("customer_lock_wait_complete", duration_ms=trace.value("customer_lock_wait"))
             await _process_one_inbound_message(service, message, settings, trace)
          except Exception:
            # Never turn a later database/RAG failure into an Exotel webhook error.
            logger.error("exotel_inbound_background_failed operation=inbound_persistence request_id=%s", trace.request_id)
            trace.summary()


async def _process_one_inbound_message(service, message, settings, trace: LatencyTrace) -> None:
    """Run the full persistence-to-reply lifecycle under one conversation lock."""
    result = await run_in_threadpool(service.process, message)
    trace.event("inbound_message_saved")
    if result.duplicate:
                logger.info("orchestration_skipped request_id=%s reason=duplicate_inbound", trace.request_id)
                trace.summary(intent="duplicate", response_mode="duplicate", response_basis="none")
                return
    if not getattr(settings, "raipur_inbound_orchestrator_enabled", False):
                logger.info("orchestration_skipped request_id=%s reason=feature_disabled", trace.request_id)
                trace.summary(intent="feature_disabled", response_mode="none", response_basis="none")
                return
    if message.message_type not in {"text", "flow"} or result.customer is None or result.conversation is None:
                logger.info("orchestration_skipped reason=unsupported_inbound_type")
                return
    # When CRM/ECHT owns this number, Exotel remains responsible only for the
    # native customer-details Flow. After details are complete, normal text is
    # orchestrated from the ECHT inbound event and sent once through the durable
    # Exotel draft pipeline, so this copy must never create a second reply.
    if (
        bool(getattr(settings, "echt_connect_enabled", False))
        and message.message_type == "text"
        and customer_details_complete(result.customer)
        and not (
            message.interactive_reply
            and coimbatore_package_action_id(message.content) is not None
        )
    ):
                logger.info(
                    "orchestration_skipped reason=echt_connect_owns_completed_customer_text"
                )
                return

    try:
                logger.info("orchestration_started request_id=%s", trace.request_id)
                with latency_stage("orchestrator_initialization"):
                    orchestrator = await run_in_threadpool(get_raipur_inbound_orchestrator)
                trace.event("orchestrator_initialization_complete", duration_ms=trace.value("orchestrator_initialization"))
                with latency_stage("total_orchestration"), latency_stage("deterministic_routing"):
                    orchestration = await run_in_threadpool(
                        orchestrator.process,
                        message,
                        customer=result.customer,
                        conversation=result.conversation,
                        source_message_id=message.external_message_id,
                    )
                package_action = (
                    coimbatore_package_action_id(message.content)
                    if message.interactive_reply else None
                )
                lead = lead_email_from_context(
                    package_action or "", result.customer, getattr(orchestration, "context", None),
                )
                if lead is not None:
                    try:
                        sent = await run_in_threadpool(
                            SmtpLeadEmailNotifier(settings).send, lead,
                        )
                        logger.info(
                            "coimbatore_lead_email_completed action=%s sent=%s",
                            package_action, sent,
                        )
                    except Exception as error:
                        logger.error(
                            "coimbatore_lead_email_failed action=%s error_category=%s",
                            package_action, type(error).__name__,
                        )
                trace.event("routing_complete", duration_ms=trace.value("total_orchestration"))
                trace.stages_ms["reply_ready"] = trace.total_ms()
                trace.mark("reply_ready", event="reply_ready")
                repository = OutboundDraftRepository(get_supabase_client())
                with latency_stage("draft_creation"), latency_stage("draft_or_message_persistence"):
                    draft_result = await run_in_threadpool(
                        create_draft_after_orchestration,
                        settings=settings,
                        inbound_message=result.inbound_message,
                        customer=result.customer,
                        conversation=result.conversation,
                        orchestration=orchestration,
                        repository_factory=lambda: repository,
                    )
                response_sent = False
                if draft_result.draft_saved and isinstance(result.inbound_message, dict):
                    draft = await run_in_threadpool(
                        repository.find_draft_for_inbound_message,
                        result.inbound_message.get("id", ""),
                    )
                    automatic = await attempt_automatic_reply(
                        settings=settings,
                        orchestration=orchestration,
                        draft=draft,
                        recipient=message.customer_whatsapp_number,
                        repository=repository,
                        sender_factory=lambda: get_raipur_draft_sender(repository, settings),
                    )
                    response_sent = automatic.response_sent
                    if response_sent and hasattr(orchestrator, "confirm_standard_package_presented"):
                        try:
                            with latency_stage("package_state_commit"):
                                committed = await run_in_threadpool(
                                    orchestrator.confirm_standard_package_presented,
                                    orchestration,
                                    result.customer["id"],
                                    result.conversation["id"],
                                )
                            logger.info("package_presented_committed message_id=%s committed=%s", message.external_message_id, committed)
                        except Exception:
                            logger.exception("standard_package_acceptance_state_failed message_id=%s", message.external_message_id)
                    logger.info(
                        "automatic_reply_completed attempted=%s response_sent=%s response_mode=%s reason=%s",
                        automatic.attempted,
                        automatic.response_sent,
                        automatic.response_mode or "none",
                        automatic.reason,
                    )
                    metadata = getattr(orchestration, "safe_metadata", {})
                    logger.info(
                        "raipur_path_automatic_reply router_revision=%s langgraph_enabled=%s active_engine=%s "
                        "message_id=%s normalized_message=%s selected_route=%s intent=%s service_code=%s topic=%s "
                        "used_previous_service=%s answer_source=%s source_filename=%s automatic_reply_eligible=%s "
                        "automatic_reply_rejection_reason=%s",
                        metadata.get("router_revision", "local") if isinstance(metadata, dict) else "local",
                        metadata.get("langgraph_enabled", False) if isinstance(metadata, dict) else False,
                        metadata.get("active_engine", "legacy") if isinstance(metadata, dict) else "legacy",
                        message.external_message_id,
                        message.content.casefold().strip() if isinstance(message.content, str) else "",
                        metadata.get("graph_answer_source", orchestration.reason_code) if isinstance(metadata, dict) else orchestration.reason_code,
                        orchestration.detected_intent,
                        metadata.get("service_code", "none") if isinstance(metadata, dict) else "none",
                        metadata.get("topic", "none") if isinstance(metadata, dict) else "none",
                        metadata.get("context_service_used", False) if isinstance(metadata, dict) else False,
                        metadata.get("answer_source", "none") if isinstance(metadata, dict) else "none",
                        metadata.get("source_filename", "none") if isinstance(metadata, dict) else "none",
                        automatic.eligible,
                        automatic.reason,
                    )
                logger.info(
                    "orchestration_completed request_id=%s action=%s reason=%s response_sent=%s draft_saved=%s",
                    trace.request_id,
                    orchestration.action,
                    draft_result.reason_code,
                    response_sent,
                    draft_result.draft_saved,
                )
                metadata = getattr(orchestration, "safe_metadata", {})
                logger.info(
                    "raipur_runtime_trace git_commit=%s module_path=%s orchestrator_class=%s "
                    "selected_route=%s intent=%s service_code=%s topic=%s answer_source=%s shared_handler_used=%s "
                    "catalogue_type=%s catalogue_source=%s catalogue_filter=%s catalogue_item_count=%s "
                    "fallback_reason=%s response_character_count=%s",
                    _runtime_git_commit(),
                    inspect.getfile(RaipurInboundOrchestrator),
                    RaipurInboundOrchestrator.__name__,
                    metadata.get("graph_answer_source", "none") if isinstance(metadata, dict) else "none",
                    getattr(orchestration, "detected_intent", "unknown"),
                    metadata.get("service_code", "none") if isinstance(metadata, dict) else "none",
                    metadata.get("topic", "none") if isinstance(metadata, dict) else "none",
                    metadata.get("answer_source", "none") if isinstance(metadata, dict) else "none",
                    metadata.get("shared_handler_used", False) if isinstance(metadata, dict) else False,
                    metadata.get("catalogue_type", "none") if isinstance(metadata, dict) else "none",
                    metadata.get("catalogue_source", "none") if isinstance(metadata, dict) else "none",
                    metadata.get("catalogue_filter", "none") if isinstance(metadata, dict) else "none",
                    metadata.get("catalogue_item_count", 0) if isinstance(metadata, dict) else 0,
                    metadata.get("fallback_reason") if isinstance(metadata, dict) else None,
                    len(getattr(orchestration, "draft_text", "")) if isinstance(getattr(orchestration, "draft_text", None), str) else 0,
                )
                trace.summary(
                    intent=getattr(orchestration, "detected_intent", None),
                    response_mode=metadata.get("response_mode") if isinstance(metadata, dict) else None,
                    response_basis=metadata.get("response_basis") if isinstance(metadata, dict) else None,
                    route=metadata.get("graph_answer_source") if isinstance(metadata, dict) else None,
                    conversation_id=result.conversation.get("id") if isinstance(result.conversation, dict) else None,
                    service_code=metadata.get("service_code") if isinstance(metadata, dict) else None,
                    topic=metadata.get("topic") if isinstance(metadata, dict) else None,
                    answer_source=metadata.get("answer_source") if isinstance(metadata, dict) else None,
                    cache_hit=metadata.get("knowledge_cache_hit", False) if isinstance(metadata, dict) else False,
                )
                trace.event("turn_complete")
    except Exception:
                logger.exception(
                    "exotel_inbound_background_failed operation=orchestration request_id=%s",
                    trace.request_id,
                )
                trace.summary()


@router.post("/inbound", status_code=200)
async def receive_inbound_message(request: Request, background_tasks: BackgroundTasks) -> Response:
    """Validate and normalize promptly, then schedule all slow inbound work."""

    trace = LatencyTrace()
    trace.stages_ms["webhook_received"] = 0.0
    trace.mark("webhook_received", event="webhook_received")
    logger.info("webhook_received request_id=%s", trace.request_id)
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
        with trace.stage("payload_validation"):
            payload = json.loads(raw_body)
            if not isinstance(payload, dict):
                raise ExotelPayloadError("Webhook body must be an object.")
            messages = normalize_exotel_payload(payload)
    except json.JSONDecodeError:
        logger.warning("exotel_webhook_invalid_json")
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    except ExotelPayloadError:
        if is_exotel_event_envelope(payload):
            logger.info("exotel_event_skipped endpoint=inbound")
            return Response(status_code=200)
        logger.warning("exotel_webhook_payload_rejected")
        raise HTTPException(status_code=400, detail="Invalid payload") from None

    if not messages:
        return Response(status_code=200)
    background_tasks.add_task(process_inbound_messages_background, messages, settings, trace)
    trace.stages_ms["webhook_ack"] = trace.total_ms()
    logger.info("webhook_acknowledged request_id=%s payload_validation_ms=%s", trace.request_id, trace.value("payload_validation"))
    return Response(status_code=200)
