"""Server-side token mapping for the Coimbatore customer-details form."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def _row(response: object) -> dict[str, Any] | None:
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


class CustomerDetailFormRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, *, customer_id: str, conversation_id: str, token_digest: str,
               ttl_minutes: int) -> dict[str, Any]:
        expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        response = self._client.table("customer_detail_forms").insert({
            "customer_id": customer_id, "conversation_id": conversation_id,
            "token_digest": token_digest, "source": "whatsapp", "status": "pending",
            "expires_at": expires_at.isoformat(),
        }).execute()
        row = _row(response)
        if row is None:
            raise RuntimeError("customer_details_form_create_failed")
        return row

    def get_by_digest(self, token_digest: str) -> dict[str, Any] | None:
        response = (self._client.table("customer_detail_forms").select("*")
                    .eq("token_digest", token_digest).maybe_single().execute())
        return _row(response)

    def complete(self, form_id: str) -> bool:
        response = (self._client.table("customer_detail_forms").update({
            "status": "completed", "completed_at": datetime.now(UTC).isoformat(),
        }).eq("id", form_id).eq("status", "pending").execute())
        return _row(response) is not None
