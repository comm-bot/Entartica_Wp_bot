"""Local-only booking-enquiry workflow with safe availability and sales handover."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import secrets
from typing import Literal

from app.repositories.booking_enquiries import BookingEnquiryRepository
from app.repositories.services import ServiceRepository
from app.services.availability import (
    AvailabilityProvider,
    AvailabilityRequest,
    AvailabilityResult,
    UnavailableAvailabilityProvider,
    ensure_fresh,
)


EnquiryState = Literal[
    "collecting_details", "pending_availability_check", "availability_found",
    "availability_not_found", "pending_sales_followup", "contacted", "closed",
]


@dataclass(frozen=True)
class BookingDetails:
    customer_name: str | None
    requested_service_text: str | None
    preferred_date: date | None
    preferred_time: time | None
    adults_count: int | None
    children_count: int | None
    total_guests: int | None
    special_requirements: str | None = None
    special_requirements_collected: bool = True
    requested_service_id: str | None = None


@dataclass(frozen=True)
class BookingWorkflowResult:
    enquiry_state: EnquiryState
    availability_status: str
    human_followup_required: bool
    next_required_field: str | None = None
    enquiry_reference: str | None = None
    created: bool = False
    pricing_status: str | None = None


_REQUIRED_FIELDS = (
    "customer_name", "requested_service_text", "preferred_date", "preferred_time",
    "adults_count", "children_count", "total_guests",
)


class BookingEnquiryService:
    """Collect and persist enquiries; it does not send messages or confirm bookings."""

    def __init__(
        self,
        repository: BookingEnquiryRepository,
        availability_provider: AvailabilityProvider | None = None,
        service_repository: ServiceRepository | None = None,
        *,
        availability_max_age: timedelta = timedelta(minutes=15),
    ) -> None:
        self._repository = repository
        self._availability_provider = availability_provider or UnavailableAvailabilityProvider()
        self._availability_max_age = availability_max_age
        self._service_repository = service_repository

    @staticmethod
    def next_missing_field(details: BookingDetails) -> str | None:
        for field in _REQUIRED_FIELDS:
            value = getattr(details, field)
            if value is None or (isinstance(value, str) and not value.strip()):
                return field
        if details.adults_count is not None and details.children_count is not None and details.total_guests is not None:
            if details.adults_count + details.children_count != details.total_guests:
                return "total_guests"
        if not details.special_requirements_collected:
            return "special_requirements"
        return None

    def submit(
        self,
        details: BookingDetails,
        *,
        customer_id: str,
        conversation_id: str,
        location_id: str,
        source_message_id: str,
        now: datetime | None = None,
    ) -> BookingWorkflowResult:
        """Check only the provider and create one enquiry for a complete inbound message."""

        missing = self.next_missing_field(details)
        if missing:
            return BookingWorkflowResult("collecting_details", "verification_required", True, next_required_field=missing)

        availability, matched_service_id = self.check_availability(details, location_id=location_id, now=now)
        state: EnquiryState
        if availability.status == "available":
            state = "availability_found"
        elif availability.status == "not_available":
            state = "availability_not_found"
        else:
            state = "pending_availability_check"

        record = {
            "reference": _reference(now),
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "location_id": location_id,
            "requested_service_id": matched_service_id,
            "requested_service_text": details.requested_service_text,
            "preferred_date": details.preferred_date.isoformat() if details.preferred_date else None,
            "preferred_time": details.preferred_time.isoformat() if details.preferred_time else None,
            "adult_count": details.adults_count,
            "child_count": details.children_count,
            "guest_count": details.total_guests,
            "total_guests": details.total_guests,
            "special_requirements": details.special_requirements,
            "availability_status": availability.status,
            "enquiry_status": state,
            "source": "whatsapp",
            "source_message_id": source_message_id,
        }
        stored, created = self._repository.create_idempotent(record)
        return BookingWorkflowResult(
            state,
            availability.status,
            True,
            enquiry_reference=stored.get("reference") if isinstance(stored.get("reference"), str) else None,
            created=created,
        )

    def check_availability(self, details: BookingDetails, *, location_id: str, now: datetime | None = None) -> tuple[AvailabilityResult, str | None]:
        """Check an exact approved service/date/time without creating an enquiry."""
        matched_service_id = details.requested_service_id
        matched_service_name: str | None = None
        if self._service_repository is not None:
            matched = self._service_repository.find_active_by_customer_text(location_id, details.requested_service_text)
            matched_service_id = matched.get("id") if isinstance(matched, dict) and isinstance(matched.get("id"), str) else None
            matched_service_name = matched.get("name") if isinstance(matched, dict) and isinstance(matched.get("name"), str) else None
        if details.preferred_date is None or details.preferred_time is None:
            return AvailabilityResult("verification_required", safe_reason_code="availability_details_required"), matched_service_id
        request = AvailabilityRequest(details.requested_service_text or "", details.preferred_date.isoformat(), details.preferred_time.isoformat(), details.total_guests or 0, location_id, matched_service_id, matched_service_name)
        result = ensure_fresh(self._availability_provider.check(request), maximum_age=self._availability_max_age, now=now)
        return result, matched_service_id

    def pricing_handover(self, details: BookingDetails, **context: str) -> BookingWorkflowResult:
        """Persist a complete relevant enquiry, but never quote, pay, or confirm."""

        result = self.submit(details, **context)
        return BookingWorkflowResult(
            result.enquiry_state,
            result.availability_status,
            True,
            result.next_required_field,
            result.enquiry_reference,
            result.created,
            pricing_status="human_quotation_required",
        )


def _reference(now: datetime | None) -> str:
    value = now or datetime.now()
    return f"ENQ-{value.strftime('%Y%m%d')}-{secrets.randbelow(1_000_000):06d}"
