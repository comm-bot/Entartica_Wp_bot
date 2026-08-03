"""Availability boundary: only an approved live provider may return a slot result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Literal, Protocol


AvailabilityStatus = Literal["available", "limited", "not_available", "verification_required", "stale", "provider_error"]


@dataclass(frozen=True)
class AvailabilityRequest:
    requested_service_text: str
    preferred_date: str
    preferred_time: str
    total_guests: int
    location_id: str | None = None
    service_id: str | None = None
    service_name: str | None = None


@dataclass(frozen=True)
class AvailabilityResult:
    status: AvailabilityStatus
    checked_at: datetime | None = None
    approved_alternatives: tuple[str, ...] = ()
    service_name: str | None = None
    normalized_date: str | None = None
    normalized_start_time: str | None = None
    normalized_end_time: str | None = None
    available_capacity: int | None = None
    operational_status: str | None = None
    safe_reason_code: str = "verification_required"


class AvailabilityProvider(Protocol):
    """Adapter contract for an approved operations-maintained live source."""

    def check(self, request: AvailabilityRequest) -> AvailabilityResult: ...


class UnavailableAvailabilityProvider:
    """Safe default until a live source is approved and configured."""

    def check(self, request: AvailabilityRequest) -> AvailabilityResult:
        del request
        return AvailabilityResult("verification_required")


class SupabaseAvailabilityProvider:
    """Read current, approved Raipur availability without reserving a slot."""

    def __init__(self, repository: object, *, maximum_age: timedelta = timedelta(minutes=30), now: Callable[[], datetime] | None = None) -> None:
        self._repository = repository
        self._maximum_age = maximum_age
        self._now = now or (lambda: datetime.now(timezone.utc))

    def check(self, request: AvailabilityRequest) -> AvailabilityResult:
        if not request.location_id or not request.service_id:
            return AvailabilityResult("verification_required", safe_reason_code="approved_service_required")
        try:
            requested_date = date.fromisoformat(request.preferred_date)
            requested_time = time.fromisoformat(request.preferred_time) if request.preferred_time else None
        except ValueError:
            return AvailabilityResult("verification_required", safe_reason_code="invalid_requested_time")
        try:
            if requested_time is not None:
                row = self._repository.get_exact_slot(request.location_id, request.service_id, requested_date, requested_time)
                return self._from_row(row, request)
            rows = self._repository.list_slots_for_service_date(request.location_id, request.service_id, requested_date, limit=20)
            alternatives = tuple(row["start_time"] for row in rows if self._eligible_alternative(row))[:3]
            return AvailabilityResult("verification_required", approved_alternatives=alternatives, service_name=request.service_name,
                                      normalized_date=requested_date.isoformat(), safe_reason_code="preferred_time_required" if alternatives else "slot_not_found")
        except Exception:
            return AvailabilityResult("provider_error", safe_reason_code="availability_provider_error")

    def _from_row(self, row: dict[str, object] | None, request: AvailabilityRequest) -> AvailabilityResult:
        if row is None:
            return AvailabilityResult("verification_required", service_name=request.service_name, normalized_date=request.preferred_date, safe_reason_code="slot_not_found")
        checked = _parse_timestamp(row.get("last_verified_at"))
        if checked is None or self._now() - checked > self._maximum_age:
            return AvailabilityResult("stale", checked_at=checked, service_name=request.service_name, normalized_date=request.preferred_date, safe_reason_code="slot_stale")
        status = str(row.get("operational_status", "verification_required"))
        capacity = row.get("available_capacity") if isinstance(row.get("available_capacity"), int) else None
        mapped: AvailabilityStatus
        if status == "available" and capacity is not None and capacity > 0: mapped = "available"
        elif status == "limited" and capacity is not None and capacity > 0: mapped = "limited"
        elif status in {"full", "closed", "maintenance"}: mapped = "not_available"
        elif status in {"weather_hold", "verification_required"}: mapped = "verification_required"
        else: mapped = "verification_required"
        return AvailabilityResult(mapped, checked, service_name=request.service_name, normalized_date=request.preferred_date,
                                  normalized_start_time=_safe_time(row.get("start_time")), normalized_end_time=_safe_time(row.get("end_time")),
                                  available_capacity=capacity, operational_status=status, safe_reason_code=f"operational_{status}")

    def _eligible_alternative(self, row: dict[str, object]) -> bool:
        checked = _parse_timestamp(row.get("last_verified_at"))
        return bool(checked and self._now() - checked <= self._maximum_age and row.get("operational_status") in {"available", "limited"} and isinstance(row.get("available_capacity"), int) and row["available_capacity"] > 0 and isinstance(row.get("start_time"), str))


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str): return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError: return None


def _safe_time(value: object) -> str | None:
    return value if isinstance(value, str) and len(value) <= 16 else None


def ensure_fresh(result: AvailabilityResult, *, maximum_age: timedelta, now: datetime | None = None) -> AvailabilityResult:
    """Never trust an otherwise positive/negative live result beyond its approved age."""

    if result.status in {"verification_required", "stale", "provider_error"} or result.checked_at is None:
        return result
    current = now or datetime.now(timezone.utc)
    checked_at = result.checked_at if result.checked_at.tzinfo else result.checked_at.replace(tzinfo=timezone.utc)
    if current - checked_at > maximum_age:
        return AvailabilityResult("stale")
    return result
