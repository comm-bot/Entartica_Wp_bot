"""Read-only Supabase data access for operations-maintained service availability."""

from __future__ import annotations

from datetime import date, time
from typing import Any

from supabase import Client


def _rows(response: object) -> list[dict[str, Any]]:
    data = getattr(response, "data", None) if response is not None else None
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else [data] if isinstance(data, dict) else []


class ServiceAvailabilityRepository:
    """Read slots only; operations tools own every insert or update."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_exact_slot(self, location_id: str, service_id: str, availability_date: date, start_time: time) -> dict[str, Any] | None:
        if not self._active_service_exists(location_id, service_id):
            return None
        response = (self._client.table("service_availability").select(
            "location_id,service_id,availability_date,start_time,end_time,total_capacity,available_capacity,operational_status,last_verified_at"
        ).eq("location_id", location_id).eq("service_id", service_id).eq("availability_date", availability_date.isoformat())
         .eq("start_time", start_time.isoformat()).limit(2).execute())
        rows = _rows(response)
        return rows[0] if len(rows) == 1 else None

    def list_slots_for_service_date(self, location_id: str, service_id: str, availability_date: date, *, limit: int = 20) -> list[dict[str, Any]]:
        if not self._active_service_exists(location_id, service_id):
            return []
        bounded = min(max(limit, 1), 20)
        response = (self._client.table("service_availability").select(
            "location_id,service_id,availability_date,start_time,end_time,total_capacity,available_capacity,operational_status,last_verified_at"
        ).eq("location_id", location_id).eq("service_id", service_id).eq("availability_date", availability_date.isoformat())
         .order("start_time").limit(bounded).execute())
        return _rows(response)

    def _active_service_exists(self, location_id: str, service_id: str) -> bool:
        response = (self._client.table("services").select("id").eq("id", service_id)
                    .eq("location_id", location_id).eq("is_active", True).limit(1).execute())
        return bool(_rows(response))
