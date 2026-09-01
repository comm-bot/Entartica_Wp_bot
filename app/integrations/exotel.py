"""Exotel-specific webhook validation and payload normalization."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
import logging
from time import perf_counter
import re
from typing import Any

import httpx
from pydantic import BaseModel

from app.schemas.exotel_webhook import (
    NormalizedInboundMessage,
    ExotelWhatsAppEnvelope,
    ExotelWhatsAppMessageInput,
)
from app.schemas.exotel_status import (
    ExotelDeliveryEnvelope,
    NormalizedDeliveryStatus,
)
from app.schemas.interactive_messages import InteractiveMessage
from app.schemas.template_messages import TemplateMessage
from app.services.latency import latency_stage


logger = logging.getLogger("uvicorn.error")


class ExotelPayloadError(ValueError):
    """Raised when an inbound Exotel payload cannot be normalized."""


class ExotelAccountSidError(ExotelPayloadError):
    """Raised when the payload does not belong to the configured account."""


class ExotelOutboundError(RuntimeError):
    """Base error for safe outbound Exotel failures."""

    code = "provider_failure"


class ExotelDefiniteRejectionError(ExotelOutboundError):
    """The provider returned a response that conclusively rejects the send."""


class ExotelAmbiguousOutcomeError(ExotelOutboundError):
    """The request may have reached Exotel, so it must be reconciled manually."""


class ExotelAuthenticationError(ExotelDefiniteRejectionError):
    code = "authentication_failed"


class ExotelValidationError(ExotelDefiniteRejectionError):
    code = "validation_failed"


class ExotelTimeoutError(ExotelAmbiguousOutcomeError):
    code = "timeout"


class ExotelConnectionError(ExotelAmbiguousOutcomeError):
    code = "connection_failed"


class ExotelProviderResponseError(ExotelAmbiguousOutcomeError):
    code = "provider_response_failed"


class ExotelAcceptedMessage(BaseModel):
    """Minimal safe result from an accepted Exotel outbound request."""

    provider_message_id: str
    http_status_code: int = 202


class ExotelClient:
    """Async Exotel WhatsApp client for the configured Exotel API region."""

    def __init__(
        self,
        *,
        account_sid: str,
        api_key: str,
        api_token: str,
        whatsapp_from: str,
        api_base_url: str = "https://api.exotel.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._account_sid = account_sid
        self._api_key = api_key
        self._api_token = api_token
        self._whatsapp_from = whatsapp_from
        self._api_base_url = api_base_url.rstrip("/")
        self._transport = transport
        self._http_client: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        """Reuse one keep-alive HTTP client for this configured Exotel client."""

        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                auth=httpx.BasicAuth(self._api_key, self._api_token),
                transport=self._transport,
            )
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def send_text_message(
        self,
        to_number: str,
        text: str,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> ExotelAcceptedMessage:
        """Submit a text message and return only the accepted provider SID."""

        safe_preview = text[:48] if isinstance(text, str) else ""
        logger.info(
            "event=outbound_unicode_trace response_repr=%r contains_mojibake=%s contains_unicode_bullet=%s",
            safe_preview,
            "\u00e2\u20ac\u00a2" in text if isinstance(text, str) else False,
            "\u2022" in text if isinstance(text, str) else False,
        )
        payload = self.build_text_payload(
            to_number=to_number,
            text=text,
            status_callback=status_callback,
            custom_data=custom_data,
        )
        return await self._submit_payload(payload)

    async def send_interactive_message(
        self,
        to_number: str,
        interactive: InteractiveMessage,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> ExotelAcceptedMessage:
        """Submit one validated list/Flow message through the normal endpoint."""
        with latency_stage("Exotel_request_prepare"):
            payload = self.build_interactive_payload(
                to_number=to_number, interactive=interactive,
                status_callback=status_callback, custom_data=custom_data,
            )
        return await self._submit_payload(payload)

    async def send_image_message(
        self,
        to_number: str,
        image_url: str,
        caption: str,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> ExotelAcceptedMessage:
        """Submit one approved remote image through the normal endpoint."""
        payload = self.build_image_payload(
            to_number=to_number, image_url=image_url, caption=caption,
            status_callback=status_callback, custom_data=custom_data,
        )
        return await self._submit_payload(payload)

    async def send_video_message(
        self,
        to_number: str,
        video_url: str,
        caption: str,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> ExotelAcceptedMessage:
        """Submit one approved remote video through the normal endpoint."""
        payload = self.build_video_payload(
            to_number=to_number, video_url=video_url, caption=caption,
            status_callback=status_callback, custom_data=custom_data,
        )
        return await self._submit_payload(payload)

    async def send_document_message(
        self, to_number: str, document_url: str, caption: str, filename: str,
        status_callback: str | None = None, custom_data: str | None = None,
    ) -> ExotelAcceptedMessage:
        """Submit one remote PDF document through the normal endpoint."""
        payload = self.build_document_payload(
            to_number=to_number, document_url=document_url, caption=caption, filename=filename,
            status_callback=status_callback, custom_data=custom_data,
        )
        return await self._submit_payload(payload)

    async def send_template_message(
        self,
        to_number: str,
        template: TemplateMessage,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> ExotelAcceptedMessage:
        """Submit one pre-approved WhatsApp template through the normal endpoint."""
        payload = self.build_template_payload(
            to_number=to_number, template=template,
            status_callback=status_callback, custom_data=custom_data,
        )
        return await self._submit_payload(payload)

    async def _submit_payload(self, payload: dict[str, Any]) -> ExotelAcceptedMessage:
        """Use identical acceptance/error semantics for text and interactive sends."""
        started = perf_counter()
        logger.info("exotel_send_started operation=exotel_send")
        try:
            with latency_stage("Exotel_HTTP_request"):
                response = await self._client().post(self._endpoint_url(), json=payload)
        except httpx.TimeoutException as error:
            _log_transport_failure(payload, self._endpoint_url(), bool(self._api_key and self._api_token))
            raise ExotelTimeoutError from error
        except httpx.RequestError as error:
            _log_transport_failure(payload, self._endpoint_url(), bool(self._api_key and self._api_token))
            raise ExotelConnectionError from error

        if response.status_code in (401, 403):
            _log_rejected_send(response, payload, endpoint_url=self._endpoint_url(), authentication_present=bool(self._api_key and self._api_token), outcome_category="definite_rejection")
            raise ExotelAuthenticationError
        if response.status_code == 400:
            _log_rejected_send(response, payload, endpoint_url=self._endpoint_url(), authentication_present=bool(self._api_key and self._api_token), outcome_category="definite_rejection")
            raise ExotelValidationError
        if response.status_code != 202:
            _log_rejected_send(response, payload, endpoint_url=self._endpoint_url(), authentication_present=bool(self._api_key and self._api_token), outcome_category="ambiguous_provider_outcome")
            raise ExotelProviderResponseError

        try:
            provider_message_id = parse_accepted_message_id(response)
        except ExotelProviderResponseError as error:
            _log_rejected_send(response, payload, endpoint_url=self._endpoint_url(), authentication_present=bool(self._api_key and self._api_token), outcome_category="ambiguous_provider_outcome")
            raise ExotelProviderResponseError from error
        response_schema, message_entry_keys, data_keys = _accepted_response_shape(response)
        logger.info(
            "exotel_send_accepted operation=exotel_send http_status=202 "
            "provider_identifier_present=true response_schema=%s message_entry_keys=%s data_keys=%s",
            response_schema,
            message_entry_keys,
            data_keys,
        )
        logger.info(
            "exotel_send_completed duration_ms=%.3f http_status=202 provider_sid_present=true status=provider_accepted",
            (perf_counter() - started) * 1000,
        )
        return ExotelAcceptedMessage(provider_message_id=provider_message_id)

    def build_interactive_payload(
        self,
        *,
        to_number: str,
        interactive: InteractiveMessage,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> dict[str, Any]:
        if interactive.kind == "buttons":
            if not 1 <= len(interactive.options) <= 3:
                raise ExotelValidationError("interactive_buttons_require_one_to_three_options")
            provider_interactive = {
                "type": "button", "body": {"text": interactive.body},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": option.id, "title": option.title}}
                    for option in interactive.options
                ]},
            }
        elif interactive.kind == "list":
            if not interactive.options:
                raise ExotelValidationError("interactive_list_requires_options")
            provider_interactive: dict[str, Any] = {
                "type": "list",
                "body": {"text": interactive.body},
                "action": {
                    "button": interactive.button_label,
                    "sections": [{
                        "title": interactive.button_label,
                        "rows": [
                            {key: value for key, value in {
                                "id": option.id, "title": option.title, "description": option.description,
                            }.items() if value is not None}
                            for option in interactive.options
                        ],
                    }],
                },
            }
        elif interactive.kind == "flow" and interactive.flow_id:
            provider_interactive = {
                "type": "flow",
                "body": {"text": interactive.body},
                "action": {
                    "name": "flow",
                    "parameters": {
                        "mode": "published",
                        "flow_message_version": "3",
                        "flow_token": interactive.flow_token or "entartica_flow",
                        "flow_id": interactive.flow_id,
                        "flow_cta": interactive.flow_cta or interactive.button_label,
                        "flow_action": "navigate",
                        **(
                            {"flow_action_payload": {"screen": interactive.flow_screen_id}}
                            if interactive.flow_screen_id
                            else {}
                        ),
                    },
                },
            }
        else:
            raise ExotelValidationError("interactive_flow_configuration_missing")
        if interactive.header_image_url is not None:
            if not interactive.header_image_url.startswith("https://"):
                raise ExotelValidationError("interactive_image_requires_https_url")
            provider_interactive["header"] = {
                "type": "image", "image": {"link": interactive.header_image_url},
            }
        message: dict[str, Any] = {
            "from": self._whatsapp_from, "to": to_number,
            "content": {"type": "interactive", "interactive": provider_interactive},
        }
        if custom_data is not None:
            message["custom_data"] = custom_data
        payload: dict[str, Any] = {"whatsapp": {"messages": [message]}}
        if status_callback is not None:
            payload["status_callback"] = status_callback
        logger.info(
            "provider_payload_has_body=%s provider_payload_has_media=%s provider_payload_action_count=%s "
            "package_interactive_type=%s",
            bool(interactive.body.strip()), interactive.header_image_url is not None,
            len(interactive.options), interactive.kind,
        )
        return payload

    def build_text_payload(
        self,
        *,
        to_number: str,
        text: str,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> dict[str, Any]:
        """Build the current documented text payload without sending it."""

        message: dict[str, Any] = {"from": self._whatsapp_from, "to": to_number, "content": {"type": "text", "text": {"body": text}}}
        payload: dict[str, Any] = {"whatsapp": {"messages": [message]}}
        if status_callback is not None:
            payload["status_callback"] = status_callback
        if custom_data is not None:
            message["custom_data"] = custom_data
        return payload

    def build_image_payload(
        self,
        *,
        to_number: str,
        image_url: str,
        caption: str,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(image_url, str) or not image_url.startswith("https://"):
            raise ExotelValidationError("image_requires_https_url")
        if not isinstance(caption, str) or not caption.strip():
            raise ExotelValidationError("image_requires_caption")
        message: dict[str, Any] = {
            "from": self._whatsapp_from, "to": to_number,
            "content": {"type": "image", "image": {"link": image_url, "caption": caption}},
        }
        if custom_data is not None:
            message["custom_data"] = custom_data
        payload: dict[str, Any] = {"whatsapp": {"messages": [message]}}
        if status_callback is not None:
            payload["status_callback"] = status_callback
        return payload

    def build_video_payload(
        self,
        *,
        to_number: str,
        video_url: str,
        caption: str,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(video_url, str) or not video_url.startswith("https://"):
            raise ExotelValidationError("video_requires_https_url")
        if not isinstance(caption, str) or not caption.strip():
            raise ExotelValidationError("video_requires_caption")
        message: dict[str, Any] = {
            "from": self._whatsapp_from, "to": to_number,
            "content": {"type": "video", "video": {"link": video_url, "caption": caption}},
        }
        if custom_data is not None:
            message["custom_data"] = custom_data
        payload: dict[str, Any] = {"whatsapp": {"messages": [message]}}
        if status_callback is not None:
            payload["status_callback"] = status_callback
        return payload

    def build_document_payload(
        self, *, to_number: str, document_url: str, caption: str, filename: str,
        status_callback: str | None = None, custom_data: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(document_url, str) or not document_url.startswith("https://"):
            raise ExotelValidationError("document_requires_https_url")
        if not isinstance(caption, str) or not caption.strip():
            raise ExotelValidationError("document_requires_caption")
        if not isinstance(filename, str) or not filename.lower().endswith(".pdf"):
            raise ExotelValidationError("document_requires_pdf_filename")
        message: dict[str, Any] = {
            "from": self._whatsapp_from, "to": to_number,
            "content": {"type":"document", "document":{
                "link":document_url, "caption":caption, "filename":filename,
            }},
        }
        if custom_data is not None: message["custom_data"] = custom_data
        payload: dict[str, Any] = {"whatsapp":{"messages":[message]}}
        if status_callback is not None: payload["status_callback"] = status_callback
        return payload

    def build_template_payload(
        self,
        *,
        to_number: str,
        template: TemplateMessage,
        status_callback: str | None = None,
        custom_data: str | None = None,
    ) -> dict[str, Any]:
        if not template.name.strip() or not template.language.strip():
            raise ExotelValidationError("template_identity_required")
        if not template.header_image_url.startswith("https://"):
            raise ExotelValidationError("template_image_requires_https_url")
        if not template.approved_package or template.service_code != "pontoon_celebration":
            raise ExotelValidationError("template_not_approved_for_service")
        message: dict[str, Any] = {
            "from": self._whatsapp_from,
            "to": to_number,
            "content": {
                "recipient_type": "individual",
                "type": "template",
                "template": {
                    "name": template.name,
                    "language": {"code": template.language, "policy": "deterministic"},
                    "components": [{
                        "type": "header",
                        "parameters": [{
                            "type": "image", "image": {"link": template.header_image_url},
                        }],
                    }],
                },
            },
        }
        if custom_data is not None:
            message["custom_data"] = custom_data
        payload: dict[str, Any] = {"whatsapp": {"messages": [message]}}
        if status_callback is not None:
            payload["status_callback"] = status_callback
        return payload

    def endpoint_pattern(self) -> str:
        """Return the safe endpoint pattern without exposing the account SID."""

        return f"{self._api_base_url}/v2/accounts/{{account_sid}}/messages"

    def _endpoint_url(self) -> str:
        return f"{self._api_base_url}/v2/accounts/{self._account_sid}/messages"


def parse_accepted_message_id(response: httpx.Response) -> str:
    """Extract only the explicit Exotel SID from a documented successful response."""

    if response.status_code != 202:
        raise ExotelProviderResponseError
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        raise ExotelProviderResponseError from None
    root = payload.get("response") if isinstance(payload, dict) and isinstance(payload.get("response"), dict) else payload
    whatsapp = root.get("whatsapp") if isinstance(root, dict) else None
    messages = whatsapp.get("messages") if isinstance(whatsapp, dict) else None
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict):
        raise ExotelProviderResponseError
    entry = messages[0]
    if str(entry.get("status", "")).casefold() not in {"success", "accepted"}:
        raise ExotelProviderResponseError
    if str(entry.get("code", "")) not in {"202", "200", "accepted"}:
        raise ExotelProviderResponseError
    data = entry.get("data")
    provider_message_id = data.get("sid") if isinstance(data, dict) else None
    if not isinstance(provider_message_id, str) or not provider_message_id.strip():
        raise ExotelProviderResponseError
    return provider_message_id.strip()


def _accepted_response_shape(response: httpx.Response) -> tuple[str, str, str]:
    """Return response-shape diagnostics without including provider values."""

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return "unknown", "none", "none"
    root = payload.get("response") if isinstance(payload, dict) and isinstance(payload.get("response"), dict) else payload
    whatsapp = root.get("whatsapp") if isinstance(root, dict) else None
    messages = whatsapp.get("messages") if isinstance(whatsapp, dict) else None
    entry = messages[0] if isinstance(messages, list) and messages and isinstance(messages[0], dict) else {}
    data = entry.get("data") if isinstance(entry, dict) else None
    return (
        "response.whatsapp" if isinstance(payload, dict) and isinstance(payload.get("response"), dict) else "whatsapp",
        ",".join(sorted(key for key in entry if isinstance(key, str))) or "none",
        ",".join(sorted(key for key in data if isinstance(data, dict) and isinstance(key, str))) or "none",
    )


def _log_rejected_send(response: httpx.Response, payload: dict[str, Any], *, endpoint_url: str, authentication_present: bool, outcome_category: str) -> None:
    """Log schema-safe Exotel rejection diagnostics without request values."""

    metadata = _safe_rejection_metadata(response)
    message = _outbound_message_for_diagnostics(payload)
    from_number = message.get("from")
    to_number = message.get("to")
    content = message.get("content")
    text = content.get("text") if isinstance(content, dict) else None
    body = text.get("body") if isinstance(text, dict) else None
    status_callback = payload.get("status_callback")
    logger.error(
        "exotel_send_rejected operation=exotel_send outcome_category=%s request_started=true http_status=%s provider_http_code=%s "
        "provider_message_code=%s provider_status=%s provider_field=%s response_content_type=%s "
        "request_id=%s response_schema=%s rest_exception_status=%s error_category=%s "
        "response_top_keys=%s response_nested_keys=%s response_value_types=%s "
        "error_data_type=%s error_data_keys=%s error_data_nested_keys=%s error_data_safe_scalars=%s "
        "provider_application_code=%s provider_error_category=%s provider_error_field=%s "
        "from_present=%s from_e164_valid=%s to_present=%s to_e164_valid=%s "
        "content_type=%s message_body_present=%s message_length=%s recipient_type=%s "
        "status_callback_present=%s status_callback_https=%s request_url_shape_valid=%s authentication_present=%s sender_present=%s recipient_present=%s callback_present=%s payload_schema=%s",
        outcome_category,
        response.status_code,
        metadata["http_code"],
        metadata["message_code"],
        metadata["status"],
        metadata["field"],
        response.headers.get("content-type", "unknown").split(";", 1)[0],
        _redact_identifier(_request_id(response)),
        metadata["schema"],
        metadata["rest_status"],
        metadata["error_category"],
        metadata["top_keys"],
        metadata["nested_keys"],
        metadata["value_types"],
        metadata["error_data_type"],
        metadata["error_data_keys"],
        metadata["error_data_nested_keys"],
        metadata["error_data_scalars"],
        metadata["application_code"],
        metadata["provider_error_category"],
        metadata["provider_error_field"],
        isinstance(from_number, str) and bool(from_number),
        _is_e164(from_number),
        isinstance(to_number, str) and bool(to_number),
        _is_e164(to_number),
        content.get("type") if isinstance(content, dict) else "unknown",
        isinstance(body, str) and bool(body),
        len(body) if isinstance(body, str) else 0,
        content.get("recipient_type") if isinstance(content, dict) else "unknown",
        isinstance(status_callback, str) and bool(status_callback),
        isinstance(status_callback, str) and status_callback.startswith("https://"),
        endpoint_url.startswith("https://api.exotel.com/v2/accounts/") and endpoint_url.endswith("/messages"),
        authentication_present,
        isinstance(from_number, str) and bool(from_number),
        isinstance(to_number, str) and bool(to_number),
        isinstance(status_callback, str) and bool(status_callback),
        "whatsapp.messages.text" if isinstance(content, dict) and content.get("type") == "text" else "unknown",
    )


def _log_transport_failure(payload: dict[str, Any], endpoint_url: str, authentication_present: bool) -> None:
    """Emit only request shape diagnostics when no provider response exists."""
    message = _outbound_message_for_diagnostics(payload)
    content = message.get("content") if isinstance(message, dict) else None
    callback = payload.get("status_callback")
    logger.error(
        "exotel_send_failed operation=exotel_send outcome_category=ambiguous_provider_outcome request_started=true request_url_shape_valid=%s authentication_present=%s sender_present=%s recipient_present=%s callback_present=%s payload_schema=%s http_status=unknown provider_http_code=unknown provider_message_code=unknown provider_status=unknown provider_field=unknown error_category=connection_or_timeout response_schema=unknown",
        endpoint_url.startswith("https://api.exotel.com/v2/accounts/") and endpoint_url.endswith("/messages"),
        authentication_present,
        isinstance(message.get("from"), str) and bool(message.get("from")),
        isinstance(message.get("to"), str) and bool(message.get("to")),
        isinstance(callback, str) and bool(callback),
        "whatsapp.messages.text" if isinstance(content, dict) and content.get("type") == "text" else "unknown",
    )


def _outbound_message_for_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the first nested message, with legacy flat payload compatibility."""
    whatsapp = payload.get("whatsapp")
    messages = whatsapp.get("messages") if isinstance(whatsapp, dict) else None
    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
        return messages[0]
    return payload


def _safe_rejection_metadata(response: httpx.Response) -> dict[str, str]:
    """Extract only safe response codes, status values, and field names."""

    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    response_container = payload.get("response")
    response_data = response_container if isinstance(response_container, dict) else {}
    whatsapp = payload.get("whatsapp") or response_data.get("whatsapp")
    message: dict[str, Any] = {}
    if isinstance(whatsapp, dict):
        messages = whatsapp.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            message = messages[0]
    data = message.get("data") if isinstance(message.get("data"), dict) else {}
    error_data = message.get("error_data")
    rest_exception = payload.get("RestException")
    rest_data = rest_exception if isinstance(rest_exception, dict) else {}
    generic_error_data = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    errors = payload.get("errors")
    errors_data = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    category = _error_category(rest_data.get("Message"))
    field = _safe_field_name(
        message, data, payload, response_data, rest_data, generic_error_data, errors_data
    )
    if field == "unknown":
        field = _field_from_category(category)
    application_code = _provider_application_code(error_data)
    provider_category = _provider_error_category(application_code, error_data)
    provider_field = _safe_field_name(
        error_data if isinstance(error_data, dict) else {}
    )
    if provider_field == "unknown":
        provider_field = _field_from_category(provider_category)
    return {
        "http_code": _safe_identifier(payload.get("http_code") or rest_data.get("Status")),
        "message_code": _safe_identifier(message.get("code") or data.get("code")),
        "status": _safe_identifier(message.get("status") or data.get("status")),
        "field": field,
        "schema": _response_schema(payload, response_data),
        "rest_status": _safe_identifier(rest_data.get("Status")),
        "error_category": category,
        "top_keys": _safe_key_names(payload),
        "nested_keys": _nested_key_names(payload, response_data, whatsapp),
        "value_types": _value_types(payload, response_data, whatsapp),
        "error_data_type": type(error_data).__name__,
        "error_data_keys": _safe_key_names(error_data) if isinstance(error_data, dict) else "none",
        "error_data_nested_keys": _error_data_nested_keys(error_data),
        "error_data_scalars": _safe_error_data_scalars(error_data),
        "application_code": application_code,
        "provider_error_category": provider_category,
        "provider_error_field": provider_field,
    }


def _error_data_nested_keys(error_data: Any) -> str:
    if not isinstance(error_data, dict):
        return "none"
    entries: list[str] = []
    for key, value in error_data.items():
        safe_key = _safe_identifier(key)
        if safe_key == "unknown":
            continue
        if isinstance(value, dict):
            entries.append(f"{safe_key}:{_safe_key_names(value)}")
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            entries.append(f"{safe_key}:{_safe_key_names(value[0])}")
    return ";".join(entries) if entries else "none"


def _safe_error_data_scalars(error_data: Any) -> str:
    if not isinstance(error_data, dict):
        return "none"
    allowed = {"code", "error_code", "subcode", "status", "type", "field", "param", "parameter", "category", "name"}
    values = []
    for key, value in error_data.items():
        if key in allowed:
            values.append(f"{key}:{_safe_error_scalar(key, value)}")
    return ",".join(values) if values else "none"


def _safe_error_scalar(key: str, value: Any) -> str:
    if key in {"code", "error_code", "subcode"}:
        if isinstance(value, int) and 0 <= value < 100_000_000:
            return str(value)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,31}", value):
            return value
        return "unknown"
    if key in {"field", "param", "parameter"}:
        return value if value in {"from", "to", "content", "status_callback", "recipient_type"} else "unknown"
    if key in {"status", "type", "category", "name"}:
        return value if value in {"failure", "failed", "error", "validation", "validation_error"} else "unknown"
    return "unknown"


def _provider_application_code(error_data: Any) -> str:
    if not isinstance(error_data, dict):
        return "unknown"
    for key in ("error_code", "code", "subcode"):
        value = _safe_error_scalar(key, error_data.get(key))
        if value != "unknown":
            return value
    for value in error_data.values():
        if isinstance(value, dict):
            for key in ("error_code", "code", "subcode"):
                safe = _safe_error_scalar(key, value.get(key))
                if safe != "unknown":
                    return safe
    return "unknown"


def _provider_error_category(application_code: str, error_data: Any) -> str:
    """Classify known numeric provider codes before inspecting error text."""

    numeric_code_categories = {
        "1000": "insufficient_balance",
        "1001": "whatsapp_not_enabled",
        "1002": "sender_not_registered",
        "1003": "waba_not_connected",
    }
    if application_code in numeric_code_categories:
        return numeric_code_categories[application_code]
    return _error_category(_error_text(error_data))


def _error_text(error_data: Any) -> str | None:
    if not isinstance(error_data, dict):
        return None
    for key in ("message", "description", "details", "reason", "error"):
        value = error_data.get(key)
        if isinstance(value, str):
            return value
    for value in error_data.values():
        if isinstance(value, dict):
            nested = _error_text(value)
            if nested is not None:
                return nested
    return None


def _response_schema(payload: dict[str, Any], response_data: dict[str, Any]) -> str:
    if isinstance(payload.get("RestException"), dict):
        return "RestException"
    if isinstance(payload.get("error"), dict):
        return "error"
    if isinstance(payload.get("errors"), list):
        return "errors"
    if isinstance(response_data.get("whatsapp"), dict):
        return "response.whatsapp"
    if isinstance(payload.get("whatsapp"), dict):
        return "whatsapp"
    return "unknown"


def _safe_key_names(container: dict[str, Any]) -> str:
    keys = [_safe_identifier(key) for key in container]
    safe = sorted(key for key in keys if key != "unknown")
    return ",".join(safe) if safe else "none"


def _nested_key_names(
    payload: dict[str, Any], response_data: dict[str, Any], whatsapp: Any
) -> str:
    entries: list[str] = []
    for name, value in (
        ("RestException", payload.get("RestException")),
        ("error", payload.get("error")),
        ("errors", payload.get("errors")),
        ("response", payload.get("response")),
        ("whatsapp", whatsapp),
    ):
        if isinstance(value, dict):
            entries.append(f"{name}:{_safe_key_names(value)}")
        if name == "errors" and isinstance(value, list) and value and isinstance(value[0], dict):
            entries.append(f"errors:{_safe_key_names(value[0])}")
    messages = whatsapp.get("messages") if isinstance(whatsapp, dict) else None
    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
        entries.append(f"messages:{_safe_key_names(messages[0])}")
    return ";".join(entries) if entries else "none"


def _value_types(
    payload: dict[str, Any], response_data: dict[str, Any], whatsapp: Any
) -> str:
    entries: list[str] = []
    for name, container in (
        ("top", payload),
        ("response", response_data),
        ("whatsapp", whatsapp if isinstance(whatsapp, dict) else {}),
    ):
        for key, value in container.items():
            safe_key = _safe_identifier(key)
            if safe_key != "unknown":
                entries.append(f"{name}.{safe_key}:{type(value).__name__}")
    return ",".join(entries) if entries else "none"


def _error_category(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown_validation_error"
    message = value.lower()
    if "template" in message:
        return "template_required"
    if "whatsapp" in message and ("enabled" in message or "enable" in message):
        return "whatsapp_not_enabled"
    if "session" in message or "24 hour" in message:
        return "session_closed"
    if "not registered" in message and ("sender" in message or "from" in message):
        return "sender_not_registered"
    if "sender" in message or "from" in message:
        return "invalid_sender"
    if "not allowed" in message and ("recipient" in message or "destination" in message or " to " in message):
        return "recipient_not_allowed"
    if "recipient" in message or "destination" in message or " to " in message:
        return "invalid_recipient"
    if "missing" in message or "required" in message:
        return "missing_parameter"
    if "parameter" in message and "invalid" in message:
        return "invalid_parameter"
    if "callback" in message or "webhook" in message or "url" in message:
        return "invalid_callback"
    if "account" in message or "auth" in message or "api key" in message:
        return "invalid_account"
    if "content" in message or "message" in message or "body" in message:
        return "invalid_content"
    return "unknown_validation_error"


def _field_from_category(category: str) -> str:
    return {
        "invalid_sender": "from",
        "sender_not_registered": "from",
        "invalid_recipient": "to",
        "recipient_not_allowed": "to",
        "invalid_content": "content",
        "invalid_callback": "status_callback",
    }.get(category, "unknown")


def _safe_field_name(*containers: dict[str, Any]) -> str:
    for container in containers:
        for key in ("field", "validation_field", "parameter"):
            value = _safe_identifier(container.get(key))
            if value != "unknown":
                return value
        errors = container.get("errors")
        if isinstance(errors, dict):
            for key in errors:
                value = _safe_identifier(key)
                if value != "unknown":
                    return value
    return "unknown"


def _safe_identifier(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
        return value
    return "unknown"


def _request_id(response: httpx.Response) -> str | None:
    for header in ("x-request-id", "request-id", "x-exotel-request-id"):
        value = response.headers.get(header)
        if value:
            return value
    return None


def _redact_identifier(value: str | None) -> str:
    if not value:
        return "unknown"
    return f"{value[:4]}…{value[-4:]}" if len(value) > 8 else "[redacted]"


def _is_e164(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"\+[1-9][0-9]{7,14}", value))


def normalize_delivery_callbacks(payload: dict[str, Any]) -> list[NormalizedDeliveryStatus]:
    """Tolerantly normalize nested and flat Exotel delivery callbacks."""

    entries: list[dict[str, Any]] = []
    whatsapp = payload.get("whatsapp") if isinstance(payload, dict) else None
    messages = whatsapp.get("messages") if isinstance(whatsapp, dict) else None
    if isinstance(messages, list):
        entries.extend(item for item in messages if isinstance(item, dict))
    elif isinstance(payload, dict):
        entries.append(payload)
    callbacks: list[NormalizedDeliveryStatus] = []
    for entry in entries:
        if str(entry.get("callback_type", "")).casefold() != "dlr":
            continue
        sid = _first_string(entry, "message_sid", "sms_sid", "sid", "provider_message_id")
        status = _callback_status(entry)
        if status is None:
            continue
        occurred_at = _as_utc(entry["timestamp"]) if isinstance(entry.get("timestamp"), datetime) else None
        callbacks.append(NormalizedDeliveryStatus(
            provider_message_id=sid,
            internal_message_id=_first_string(entry, "custom_data", "client_sid"),
            status=status,
            occurred_at=occurred_at,
            failure_code=_first_string(entry, "exo_status_code", "error_code") if status == "failed" else None,
            failure_description="provider_delivery_failed" if status == "failed" else None,
        ))
    return callbacks


def is_exotel_event_envelope(payload: object) -> bool:
    """Return true for valid non-incoming Exotel events that must be acknowledged."""

    if not isinstance(payload, dict):
        return False
    whatsapp = payload.get("whatsapp")
    messages = whatsapp.get("messages") if isinstance(whatsapp, dict) else None
    return isinstance(messages, list) and all(isinstance(item, dict) for item in messages)


def _first_string(entry: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _callback_status(entry: dict[str, Any]) -> str | None:
    value = entry.get("exo_detailed_status") or entry.get("status")
    if isinstance(value, str):
        mapped = {
            "accepted": "accepted", "sent": "sent", "ex_message_sent": "sent",
            "delivered": "delivered", "ex_message_delivered": "delivered",
            "read": "read", "seen": "read", "ex_message_seen": "read",
            "failed": "failed", "failure": "failed",
        }.get(value.casefold())
        if mapped:
            return mapped
    return _status_from_exotel_code(_first_string(entry, "exo_status_code"))


def _normalize_delivery_callback(
    message: Any,
) -> NormalizedDeliveryStatus:
    status = _status_from_exotel_code(message.exo_status_code)
    occurred_at = _as_utc(message.timestamp) if message.timestamp is not None else None
    failure_code = message.exo_status_code if status == "failed" else None
    return NormalizedDeliveryStatus(
        provider_message_id=message.message_sid,
        internal_message_id=message.custom_data,
        status=status,
        occurred_at=occurred_at,
        failure_code=failure_code,
        failure_description="provider_delivery_failed" if status == "failed" else None,
    )


def _status_from_exotel_code(code: str | None) -> str | None:
    if code == "30001":
        return "sent"
    if code == "30002":
        return "delivered"
    if code == "30003":
        return "read"
    if code is not None and code.isdigit() and 30004 <= int(code) <= 30041:
        return "failed"
    return None


def validate_exotel_signature(
    raw_body: bytes,
    signature: str | None,
    signing_secret: str | None,
    *,
    enabled: bool,
) -> bool:
    """Validate an HMAC-SHA256 signature when the account requires it."""

    if not enabled:
        return True
    if not signature or not signing_secret:
        return False

    expected = hmac.new(
        signing_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def normalize_exotel_payload(payload: dict[str, Any]) -> list[NormalizedInboundMessage]:
    """Normalize only incoming messages from the confirmed Exotel envelope."""

    try:
        envelope = ExotelWhatsAppEnvelope.model_validate(payload)
    except Exception as error:
        raise ExotelPayloadError("Unsupported Exotel payload envelope.") from error

    messages = envelope.whatsapp.messages
    return [
        _normalize_whatsapp_message(message)
        for message in messages
        if message.callback_type == "incoming_message"
    ]


def _normalize_whatsapp_message(
    message: ExotelWhatsAppMessageInput,
) -> NormalizedInboundMessage:
    """Normalize one confirmed Exotel WhatsApp message without retaining extras."""

    customer_number = _normalize_phone(message.from_)
    business_number = _normalize_phone(message.to)
    message_type = _message_type_from_content(message.content)
    content = _content_from_message(message.content, message_type)
    interactive = message.content.get("interactive")
    interactive_reply = bool(
        message.content.get("type") == "interactive"
        and isinstance(interactive, dict)
        and interactive.get("type") in {"list_reply", "button_reply"}
    )
    form_response = _parse_flow_response_json(message.content) if message_type == "flow" else None

    return NormalizedInboundMessage(
        external_message_id=message.sid
        or _fallback_message_id(
            callback_type=message.callback_type,
            customer_number=customer_number,
            business_number=business_number,
            received_at=message.timestamp,
            message_type=message_type,
            content=content,
        ),
        customer_whatsapp_number=customer_number,
        business_whatsapp_number=business_number,
        profile_name=message.profile_name,
        message_type=message_type,
        content=content,
        interactive_reply=interactive_reply,
        form_response=form_response,
        received_at=_as_utc(message.timestamp),
    )


def _normalize_phone(value: str) -> str:
    normalized = re.sub(r"[\s()\-]", "", value)
    if not re.fullmatch(r"\+?[1-9][0-9]{7,14}", normalized):
        raise ExotelPayloadError("Invalid WhatsApp number.")
    return normalized if normalized.startswith("+") else f"+{normalized}"


def _message_type_from_content(content: dict[str, Any]) -> str:
    value = content.get("type")
    if value == "text":
        return "text"
    if value == "interactive":
        interactive = content.get("interactive")
        if isinstance(interactive, dict):
            if interactive.get("type") in {"flow", "nfm_reply"}:
                return "flow"
            if interactive.get("type") in {"list_reply", "button_reply"}:
                return "text"
    return "other"


def _content_from_message(content: dict[str, Any], message_type: str) -> str | None:
    if message_type == "text":
        text = content.get("text")
        if isinstance(text, dict):
            body = text.get("body")
            return body if isinstance(body, str) else None
        interactive = content.get("interactive")
        if isinstance(interactive, dict):
            reply = interactive.get(interactive.get("type"))
            if isinstance(reply, dict):
                identifier = reply.get("id")
                title = reply.get("title")
                if isinstance(identifier, str) and identifier.strip():
                    canonical_selections = {
                        "celebration_floating_gazebo": "Floating Gazebo",
                        "celebration_houseboat": "Houseboat Celebration",
                        "celebration_jetty_gazebo": "Jetty Gazebo",
                        "celebration_party_boat": "Party Boat Celebration",
                        "celebration_pontoon": "Pontoon Boat Celebration",
                    }
                    return canonical_selections.get(identifier.strip().casefold(), identifier)
                return title if isinstance(title, str) else None
    if message_type == "flow":
        interactive = content.get("interactive")
        if isinstance(interactive, dict):
            nfm_reply = interactive.get("nfm_reply")
            if isinstance(nfm_reply, dict):
                body = nfm_reply.get("body")
                return body if isinstance(body, str) else None
    return None


def _parse_flow_response_json(content: dict[str, Any]) -> dict[str, Any] | None:
    """Validate a Flow response without persisting or logging its form values."""

    interactive = content.get("interactive")
    if not isinstance(interactive, dict):
        return None
    nfm_reply = interactive.get("nfm_reply")
    if not isinstance(nfm_reply, dict):
        return None
    value = nfm_reply.get("response_json")
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _fallback_message_id(
    *,
    callback_type: str,
    customer_number: str,
    business_number: str,
    received_at: datetime,
    message_type: str,
    content: str | None,
) -> str:
    """Build a deterministic ID from the minimum canonical message fields."""

    canonical = json.dumps(
        {
            "callback_type": callback_type,
            "from": customer_number,
            "to": business_number,
            "timestamp": _as_utc(received_at).isoformat(),
            "message_type": message_type,
            "content": content,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Return an aware timestamp in UTC."""

    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
