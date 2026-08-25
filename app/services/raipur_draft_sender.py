"""Explicit-only approved-draft sender; approval itself never calls this service."""

from __future__ import annotations

import secrets
import asyncio
import logging
from dataclasses import dataclass, replace
from typing import Any

from app.integrations.exotel import (
    ExotelAmbiguousOutcomeError,
    ExotelClient,
    ExotelDefiniteRejectionError,
    ExotelOutboundError,
)
from app.services.latency import current_latency_trace, latency_stage
from app.schemas.interactive_messages import InteractiveMessage, InteractiveOption
from app.schemas.template_messages import TemplateMessage

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ApprovedDraftSendResult:
 attempted:bool;accepted:bool;sid_recorded:bool;duplicate_prevented:bool;reason:str

class RaipurDraftSender:
    def __init__(self, repository: Any, settings: Any, exotel: ExotelClient):
        self._repo, self._settings, self._exotel = repository, settings, exotel

    async def send(self, draft_id: str, to: str, *, confirmed: bool) -> ApprovedDraftSendResult:
        if not confirmed:
            return ApprovedDraftSendResult(False, False, False, False, "confirmation_required")
        if not self._settings.exotel_outbound_enabled or not self._settings.raipur_approved_draft_send_enabled:
            return ApprovedDraftSendResult(False, False, False, False, "send_feature_disabled")
        # The allowlist is a development/staging guard. In production the
        # recipient is the normalized customer number from the inbound
        # webhook, while EXOTEL_WHATSAPP_FROM remains the business sender.
        environment = str(getattr(self._settings, "app_env", "development")).strip().casefold()
        if environment != "production" and to not in self._settings.raipur_outbound_test_recipients:
            return ApprovedDraftSendResult(False, False, False, False, "recipient_not_allowlisted")

        draft = await asyncio.to_thread(self._repo.get_draft_by_id, draft_id)
        metadata = draft.get("draft_metadata") if isinstance(draft, dict) and isinstance(draft.get("draft_metadata"), dict) else {}
        package_id = metadata.get("package_id") if isinstance(metadata.get("package_id"), str) else None
        if not isinstance(draft, dict) or draft.get("draft_status") == "sent" or draft.get("sent_at") or draft.get("external_message_id"):
            return ApprovedDraftSendResult(False, False, False, True, "duplicate_send_prevented")
        if draft.get("send_attempt_state") in {"claimed", "provider_failed", "reconciliation_required"}:
            return ApprovedDraftSendResult(False, False, False, True, "duplicate_send_prevented")
        if draft.get("draft_status") != "approved" or not metadata.get("response_valid") or not isinstance(draft.get("content"), str) or not draft["content"].strip():
            return ApprovedDraftSendResult(False, False, False, False, "local_validation_failure")

        claim_token = secrets.token_urlsafe(24)
        with latency_stage("outbound_claim"):
            claim = await asyncio.to_thread(self._repo.claim_send, draft_id, claim_token)
        if claim in {"already_claimed", "already_sent", "provider_failed", "reconciliation_required"}:
            return ApprovedDraftSendResult(False, False, False, True, "duplicate_send_prevented")
        if claim != "claim_acquired":
            return ApprovedDraftSendResult(False, False, False, False, "local_validation_failure")
        if (trace := current_latency_trace()) is not None: trace.event("send_claimed")

        accepted_any = False
        try:
            with latency_stage("Exotel_outbound_api"):
                if (trace := current_latency_trace()) is not None: trace.mark("exotel_request_start", event="exotel_request_start")
                try:
                    template = _template_from_metadata(metadata.get("template_message"))
                    media = _media_from_metadata(metadata.get("media_message"))
                    media_sequence = _media_sequence_from_metadata(metadata.get("media_sequence"))
                    document = _document_from_metadata(metadata.get("document_message"))
                    interactive = _interactive_from_metadata(metadata.get("interactive_message"))
                    if document is not None:
                        document_url, caption, filename = document
                        accepted = await self._exotel.send_document_message(
                            to, document_url, caption, filename,
                            self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}-document",
                        )
                    elif media_sequence is not None:
                        accepted = None
                        for index, item in enumerate(media_sequence, start=1):
                            media_type, url, caption = item
                            custom = f"draft-{draft_id[:8]}-media-{index}"
                            if media_type == "image":
                                accepted = await self._exotel.send_image_message(
                                    to, url, caption, self._settings.exotel_status_callback_url, custom
                                )
                            else:
                                accepted = await self._exotel.send_video_message(
                                    to, url, caption, self._settings.exotel_status_callback_url, custom
                                )
                            accepted_any = True
                        if accepted is None:
                            raise ValueError("empty_media_sequence")
                        if interactive is not None:
                            accepted = await self._exotel.send_interactive_message(
                                to, interactive, self._settings.exotel_status_callback_url,
                                f"draft-{draft_id[:8]}-post-media-cta",
                            )
                    elif template is not None:
                        accepted = await self._exotel.send_template_message(
                            to, template, self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}"
                        )
                    elif media is not None:
                        image_url, caption = media
                        combined = (
                            interactive is not None
                            and interactive.header_image_url == image_url
                            and interactive.body == caption
                        )
                        if combined:
                            if package_id: logger.info("package_send_started package_id=%s sequence=single_interactive_media", package_id)
                            try:
                                accepted = await self._exotel.send_interactive_message(
                                    to, interactive, self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}"
                                )
                            except ExotelDefiniteRejectionError:
                                # Preserve full body plus every action in one safe
                                # interactive fallback if image headers are rejected.
                                logger.warning("package_interactive_media_rejected fallback=interactive_without_header draft_id_prefix=%s", draft_id[:8])
                                accepted = await self._exotel.send_interactive_message(
                                    to, replace(interactive, header_image_url=None),
                                    self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}-fallback"
                                )
                            if package_id:
                                logger.info("package_send_result package_id=%s result=provider_accepted transport=%s action_count=%s", package_id, interactive.kind, len(interactive.options))
                        else:
                            try:
                                await self._exotel.send_image_message(
                                    to, image_url, caption, self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}"
                                )
                                accepted_any = True
                            except ExotelDefiniteRejectionError:
                                await self._exotel.send_text_message(
                                    to, caption, self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}-fallback"
                                )
                                accepted_any = True
                            if interactive is not None:
                                accepted = await self._exotel.send_interactive_message(
                                    to, interactive, self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}"
                                )
                            else:
                                accepted = await self._exotel.send_text_message(
                                    to, draft["content"], self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}"
                                )
                    elif interactive is not None:
                        accepted = await self._exotel.send_interactive_message(
                            to, interactive, self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}"
                        )
                    else:
                        accepted = await self._exotel.send_text_message(
                            to, draft["content"], self._settings.exotel_status_callback_url, f"draft-{draft_id[:8]}"
                        )
                finally:
                    if (trace := current_latency_trace()) is not None: trace.mark("exotel_request_complete", event="exotel_request_complete")
        except ExotelDefiniteRejectionError:
            if accepted_any:
                await asyncio.to_thread(self._repo.mark_claim_reconciliation_required, draft_id, claim_token)
                return ApprovedDraftSendResult(True, False, False, False, "reconciliation_required")
            await asyncio.to_thread(self._repo.mark_claim_provider_failed, draft_id, claim_token)
            return ApprovedDraftSendResult(True, False, False, False, "provider_rejected")
        except (ExotelAmbiguousOutcomeError, ExotelOutboundError):
            await asyncio.to_thread(self._repo.mark_claim_reconciliation_required, draft_id, claim_token)
            return ApprovedDraftSendResult(True, False, False, False, "reconciliation_required")
        except Exception:
            # An unknown post-claim error is treated conservatively: Exotel may have accepted.
            await asyncio.to_thread(self._repo.mark_claim_reconciliation_required, draft_id, claim_token)
            return ApprovedDraftSendResult(True, False, False, False, "reconciliation_required")

        with latency_stage("send_completion_persistence"):
            completed = await asyncio.to_thread(self._repo.complete_send_claim, draft_id, claim_token, accepted.provider_message_id)
        if (trace := current_latency_trace()) is not None: trace.event("send_state_persisted", duration_ms=trace.value("send_completion_persistence"))
        if completed:
            if package_id: logger.info("package_send_result package_id=%s result=completed", package_id)
            return ApprovedDraftSendResult(True, True, True, False, "completed")

        await asyncio.to_thread(self._repo.mark_claim_reconciliation_required, draft_id, claim_token)
        return ApprovedDraftSendResult(True, False, False, False, "reconciliation_required")


def _interactive_from_metadata(value: object) -> InteractiveMessage | None:
    """Rebuild only the provider-neutral, allowlisted interactive model."""
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    if kind not in {"list", "flow", "buttons"}:
        return None
    try:
        options = tuple(
            InteractiveOption(str(item["id"]), str(item["title"]), str(item["description"]) if item.get("description") else None)
            for item in value.get("options", ()) if isinstance(item, dict) and item.get("id") and item.get("title")
        )
        return InteractiveMessage(
            kind=kind, body=str(value["body"]), fallback_text=str(value["fallback_text"]),
            button_label=str(value["button_label"]), options=options,
            flow_id=str(value["flow_id"]) if value.get("flow_id") else None,
            flow_token=str(value["flow_token"]) if value.get("flow_token") else None,
            flow_cta=str(value["flow_cta"]) if value.get("flow_cta") else None,
            flow_screen_id=str(value["flow_screen_id"]) if value.get("flow_screen_id") else None,
            flow_type=value.get("flow_type") if value.get("flow_type") in {"general_quote", "celebration", "pontoon_celebration", "customer_details"} else None,
            header_image_url=str(value["header_image_url"]) if value.get("header_image_url") else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _media_from_metadata(value: object) -> tuple[str, str] | None:
    """Return only the allowlisted remote-image fields stored with the draft."""
    if not isinstance(value, dict) or value.get("type") != "image":
        return None
    url, caption = value.get("url"), value.get("caption")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    if not isinstance(caption, str) or not caption.strip():
        return None
    return url, caption


def _document_from_metadata(value: object) -> tuple[str, str, str] | None:
    if not isinstance(value, dict) or value.get("type") != "document": return None
    url, caption, filename = value.get("url"), value.get("caption"), value.get("filename")
    if not isinstance(url, str) or not url.startswith("https://"): return None
    if not isinstance(caption, str) or not caption.strip(): return None
    if not isinstance(filename, str) or not filename.lower().endswith(".pdf"): return None
    return url, caption, filename


def _media_sequence_from_metadata(value: object) -> tuple[tuple[str, str, str], ...] | None:
    """Validate the narrowly scoped two-image/one-video action sequence."""
    if not isinstance(value, list) or len(value) != 3:
        return None
    result: list[tuple[str, str, str]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("type") not in {"image", "video"}:
            return None
        url, caption = item.get("url"), item.get("caption")
        if not isinstance(url, str) or not url.startswith("https://"):
            return None
        if not isinstance(caption, str) or not caption.strip():
            return None
        result.append((str(item["type"]), url, caption))
    if [item[0] for item in result] != ["image", "image", "video"]:
        return None
    return tuple(result)


def _template_from_metadata(value: object) -> TemplateMessage | None:
    """Rebuild only the narrowly approved Pontoon template model."""
    if not isinstance(value, dict):
        return None
    try:
        template = TemplateMessage(
            name=str(value["name"]), language=str(value["language"]),
            header_image_url=str(value["header_image_url"]), flow_id=str(value["flow_id"]),
            flow_cta=str(value["flow_cta"]), service_code=str(value["service_code"]),
            package_source_file=str(value["package_source_file"]),
            approved_package=value.get("approved_package") is True,
        )
    except (KeyError, TypeError, ValueError):
        return None
    if (
        not template.name.strip() or not template.flow_id.strip()
        or not template.header_image_url.startswith("https://")
        or template.flow_cta != "Share Event Details"
        or template.service_code != "pontoon_celebration"
        or template.package_source_file != "active/services/pontoon_celebration.md"
        or not template.approved_package
    ):
        return None
    return template
