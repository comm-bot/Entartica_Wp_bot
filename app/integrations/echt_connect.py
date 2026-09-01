"""Authentication and callback transport for ECHT Connect."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx

from app.schemas.echt_connect import EchtConnectReply


class EchtConnectConfigurationError(RuntimeError):
    """The requested CRM number has no complete credential set."""


class EchtConnectCallbackError(RuntimeError):
    """The CRM callback did not accept the chatbot result."""


@dataclass(frozen=True)
class EchtConnectNumberCredentials:
    number_id: str
    webhook_secret: str
    api_key: str
    callback_url: str
    business_phone: str


def number_credentials(settings: Any, number_id: str) -> EchtConnectNumberCredentials:
    secret = getattr(settings, "echt_connect_numbers_json", None)
    raw = secret.get_secret_value() if secret is not None else ""
    try:
        values = json.loads(raw)
        row = values[number_id]
        credentials = EchtConnectNumberCredentials(
            number_id=number_id,
            webhook_secret=str(row["webhook_secret"]),
            api_key=str(row["api_key"]),
            callback_url=str(row["callback_url"]),
            business_phone=str(row["business_phone"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise EchtConnectConfigurationError("echt_connect_number_not_configured") from error
    if (
        not credentials.webhook_secret
        or not credentials.api_key
        or not credentials.callback_url.startswith("https://")
        or not credentials.business_phone.startswith("+")
    ):
        raise EchtConnectConfigurationError("echt_connect_number_configuration_invalid")
    return credentials


def validate_signature(raw_body: bytes, signature: str | None, secret: str) -> bool:
    """Verify the documented ``sha256=<hex>`` signature in constant time."""
    if not signature or not signature.startswith("sha256="):
        return False
    supplied = signature.removeprefix("sha256=").strip().casefold()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


class EchtConnectClient:
    def __init__(self, *, timeout_seconds: float = 10.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._timeout = timeout_seconds
        self._transport = transport

    async def send_reply(
        self,
        credentials: EchtConnectNumberCredentials,
        reply: EchtConnectReply,
    ) -> None:
        headers = {"Authorization": f"Bearer {credentials.api_key}"}
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        credentials.callback_url,
                        headers=headers,
                        json=reply.model_dump(by_alias=True, exclude_none=True),
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as error:
                    if attempt == 2:
                        raise EchtConnectCallbackError("echt_connect_callback_transport_failed") from error
                else:
                    if response.status_code in {200, 201, 202}:
                        return
                    if response.status_code != 429 and response.status_code < 500:
                        raise EchtConnectCallbackError(f"echt_connect_callback_http_{response.status_code}")
                    if attempt == 2:
                        raise EchtConnectCallbackError(f"echt_connect_callback_http_{response.status_code}")
                await asyncio.sleep(0.25 * (2 ** attempt))
