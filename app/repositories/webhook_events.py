"""Atomic webhook-event idempotency backed by Postgres uniqueness."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from supabase import Client

from app.repositories.bookings import _one


def _is_unique_violation(error: Exception) -> bool:
    code = getattr(error, "code", None)
    if code is None and isinstance(getattr(error, "args", None), tuple) and error.args:
        details = error.args[0]
        code = details.get("code") if isinstance(details, dict) else None
    return code == "23505"


class WebhookEventRepository:
    """Claim external events once; never stores their sensitive raw payload."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def try_create_webhook_event(self, record: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        """Atomically insert an event, returning ``(row, created)`` on conflict."""

        values = dict(record)
        try:
            row = _one(self._client.table("webhook_events").insert(values).execute())
        except Exception as error:
            if not _is_unique_violation(error):
                raise
            existing = self.get_webhook_event(str(values["provider"]), str(values["provider_event_id"]))
            if existing is None:
                raise RuntimeError("Webhook event conflict row could not be read.") from error
            return existing, False
        if row is None:
            raise RuntimeError("Webhook event insert returned no row.")
        return row, True

    def get_webhook_event(self, provider: str, provider_event_id: str) -> dict[str, Any] | None:
        response = (
            self._client.table("webhook_events").select("*")
            .eq("provider", provider).eq("provider_event_id", provider_event_id)
            .maybe_single().execute()
        )
        return _one(response)

    def mark_webhook_event_processed(self, event_id: str) -> dict[str, Any] | None:
        processed_at = datetime.now(UTC).isoformat()
        return _one(
            self._client.table("webhook_events")
            .update({"status": "processed", "processed_at": processed_at, "error_code": None})
            .eq("id", event_id).execute()
        )

    def mark_webhook_event_failed(self, event_id: str, error_code: str) -> dict[str, Any] | None:
        processed_at = datetime.now(UTC).isoformat()
        return _one(
            self._client.table("webhook_events")
            .update({"status": "failed", "processed_at": processed_at, "error_code": error_code})
            .eq("id", event_id).execute()
        )

    def update_webhook_event(self, event_id: str, fields: Mapping[str, Any]) -> dict[str, Any] | None:
        return _one(self._client.table("webhook_events").update(dict(fields)).eq("id", event_id).execute())
