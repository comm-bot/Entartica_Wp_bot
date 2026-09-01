"""Bounded retry for transient provider-to-Supabase transport disconnects."""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

import httpx


logger = logging.getLogger("uvicorn.error")

_TRANSIENT_TRANSPORT_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.PoolTimeout,
)

T = TypeVar("T")


def run_with_transient_retry(operation: Callable[[], T], *, operation_name: str) -> T:
    """Run one Supabase-backed operation with one transport-only retry."""

    try:
        return operation()
    except _TRANSIENT_TRANSPORT_ERRORS as error:
        logger.warning(
            "supabase_transport_retry operation=%s attempt=2 max_attempts=2 error_category=%s",
            operation_name,
            type(error).__name__,
        )
        return operation()


def process_inbound_with_retry(service: Any, message: Any) -> Any:
    """Retry one transient persistence transport failure exactly once.

    The same provider message ID is reused. Database duplicate protection
    therefore remains authoritative if the first attempt reached Supabase.
    Business, validation, and database constraint errors are never retried.
    """

    return run_with_transient_retry(
        lambda: service.process(message),
        operation_name="inbound_persistence",
    )
