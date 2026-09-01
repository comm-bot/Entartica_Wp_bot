"""Bounded retry for transient provider-to-Supabase transport disconnects."""

from __future__ import annotations

import logging
from typing import Any

import httpx


logger = logging.getLogger("uvicorn.error")

_TRANSIENT_TRANSPORT_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.PoolTimeout,
)


def process_inbound_with_retry(service: Any, message: Any) -> Any:
    """Retry one transient persistence transport failure exactly once.

    The same provider message ID is reused. Database duplicate protection
    therefore remains authoritative if the first attempt reached Supabase.
    Business, validation, and database constraint errors are never retried.
    """

    try:
        return service.process(message)
    except _TRANSIENT_TRANSPORT_ERRORS as error:
        logger.warning(
            "inbound_persistence_retry attempt=2 max_attempts=2 error_category=%s",
            type(error).__name__,
        )
        return service.process(message)
