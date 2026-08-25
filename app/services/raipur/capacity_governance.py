"""Governed celebration-capacity facts approved for deterministic use."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class CapacityStatus(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class CelebrationCapacityRecord:
    service_code: str
    published_configuration_guests: int | None
    maximum_capacity: int | None
    minimum_capacity: int | None
    typical_group_min: int | None
    typical_group_max: int | None
    capacity_status: CapacityStatus
    source_reference: str
    effective_date: date | None
    verified_by_management: bool


@dataclass(frozen=True)
class CapacityCompatibility:
    service_code: str
    guest_count: int
    compatible: bool | None
    source_reference: str | None = None
    capacity_status: CapacityStatus | None = None


# Numeric values below preserve only the distinctions established by the
# approved local corpus audit. Configurations and typical ranges are never
# interpreted as structural maxima.
CELEBRATION_CAPACITY_RECORDS: tuple[CelebrationCapacityRecord, ...] = (
    CelebrationCapacityRecord(
        "floating_gazebo", 2, None, None, 6, 8, CapacityStatus.UNKNOWN,
        "approved Floating Gazebo Capacity section; active general Celebration Experiences",
        None, False,
    ),
    CelebrationCapacityRecord(
        "houseboat_celebration", 15, 15, None, None, None, CapacityStatus.VERIFIED,
        "approved Houseboat Celebration Capacity section", None, False,
    ),
    CelebrationCapacityRecord(
        "jetty_gazebo", 6, None, None, 15, 20, CapacityStatus.CONFLICT,
        "approved Jetty Gazebo Capacity section; active general Celebration Experiences",
        None, False,
    ),
    CelebrationCapacityRecord(
        "party_boat_celebration", None, None, None, None, None, CapacityStatus.CONFLICT,
        "approved Party Boat Celebration Capacity section (50 versus 60 unresolved)",
        None, False,
    ),
    CelebrationCapacityRecord(
        "pontoon_celebration", 6, None, None, 10, 15, CapacityStatus.CONFLICT,
        "approved Pontoon Celebration Capacity section; active general Celebration Experiences",
        None, False,
    ),
)

_BY_SERVICE_CODE = {record.service_code: record for record in CELEBRATION_CAPACITY_RECORDS}


def celebration_capacity_record(service_code: str) -> CelebrationCapacityRecord | None:
    return _BY_SERVICE_CODE.get(service_code)


def assess_capacity(service_code: str, guest_count: int | None) -> CapacityCompatibility | None:
    """Return a conclusion only for a verified explicit maximum."""

    if not isinstance(guest_count, int) or guest_count < 1:
        return None
    record = celebration_capacity_record(service_code)
    if record is None:
        return CapacityCompatibility(service_code, guest_count, None)
    if record.capacity_status is not CapacityStatus.VERIFIED or record.maximum_capacity is None:
        return CapacityCompatibility(service_code, guest_count, None, None, record.capacity_status)
    return CapacityCompatibility(
        service_code,
        guest_count,
        guest_count <= record.maximum_capacity,
        record.source_reference,
        record.capacity_status,
    )
