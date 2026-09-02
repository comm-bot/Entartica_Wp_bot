"""Bounded retry for transient provider-to-Supabase transport disconnects."""

from __future__ import annotations

import logging
from dataclasses import replace
from time import sleep
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
    except Exception as error:
        if not _is_transient_supabase_error(error):
            raise
        logger.warning(
            "supabase_transport_retry operation=%s attempt=2 max_attempts=2 error_category=%s",
            operation_name,
            type(error).__name__,
        )
        if getattr(error, "code", None) == "PGRST303":
            sleep(0.25)
        return operation()


def _is_transient_supabase_error(error: Exception) -> bool:
    if isinstance(error, _TRANSIENT_TRANSPORT_ERRORS):
        return True
    return (
        getattr(error, "code", None) == "PGRST303"
        and "issued at future" in str(getattr(error, "message", error)).casefold()
    )


def process_inbound_with_retry(service: Any, message: Any) -> Any:
    """Retry one transient persistence transport failure exactly once.

    The same provider message ID is reused. Database duplicate protection
    therefore remains authoritative if the first attempt reached Supabase.
    Business, validation, and database constraint errors are never retried.
    """

    try:
        return service.process(message)
    except Exception as error:
        if not _is_transient_supabase_error(error):
            raise
        logger.warning(
            "supabase_transport_retry operation=inbound_persistence attempt=2 "
            "max_attempts=2 error_category=%s",
            type(error).__name__,
        )
        if getattr(error, "code", None) == "PGRST303":
            sleep(0.25)
        result = service.process(message)
        if getattr(result, "duplicate", False):
            return replace(result, recovered_after_transient_duplicate=True)
        return result
