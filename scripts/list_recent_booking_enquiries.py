"""Local, read-only masked sales-team view; it never sends customer messages."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.supabase import get_supabase_client
from app.repositories.booking_enquiries import BookingEnquiryRepository
from app.repositories.customers import CustomerRepository
from app.repositories.services import ServiceRepository


def mask_phone(value: object) -> str:
    """Preserve at most the final four digits for the authorised local sales view."""

    digits = "".join(re.findall(r"\d", value)) if isinstance(value, str) else ""
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


def _safe_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, int) and 100 <= code <= 599:
        return str(code)
    if isinstance(code, str) and code.replace("_", "").isalnum() and len(code) <= 16:
        return code
    return "unknown"


def _error_reason(error: Exception) -> str:
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return "connection_failure"
    code = str(getattr(error, "code", ""))
    # Inspect error text only to classify it; never expose provider text.
    text = " ".join(str(getattr(error, key, "")) for key in ("message", "details", "hint")).casefold()
    if code in {"300", "PGRST201"} or "multiple relationships" in text or "ambiguous" in text:
        return "relationship_ambiguous"
    if code == "PGRST200" or "could not find a relationship" in text:
        return "relationship_not_found"
    if code == "42703":
        return "column_missing"
    if code in {"42501", "403"}:
        return "permission_denied"
    return "unexpected_database_error"


def _error_output(error: Exception) -> str:
    reason = _error_reason(error)
    return (
        f"sales_report_failed error_class={type(error).__name__} safe_error_code={_safe_error_code(error)} "
        f"safe_error_message={reason} safe_details=none safe_hint=none reason={reason}"
    )


def _id_values(rows: list[dict[str, Any]], field: str) -> list[str]:
    return list(dict.fromkeys(value for row in rows if isinstance((value := row.get(field)), str)))


def _format_row(row: dict[str, Any], customers: dict[str, dict[str, Any]], services: dict[str, dict[str, Any]]) -> str:
    customer = customers.get(row.get("customer_id"), {})
    service = services.get(row.get("requested_service_id"), {})
    availability_status = row.get("availability_status") or "verification_required"
    live_checked = availability_status in {"available", "limited", "not_available", "stale", "provider_error"}
    sales_verification = availability_status in {"verification_required", "stale", "provider_error"}
    return (
        "enquiry "
        f"reference={row.get('reference', 'unknown')} customer_name={customer.get('name') or 'unknown'} "
        f"phone={mask_phone(customer.get('whatsapp_number'))} matched_service={'true' if service.get('name') else 'false'} "
        f"matched_service_name={service.get('name') or 'unspecified'} activity={row.get('requested_service_text') or 'unspecified'} "
        f"preferred_date={row.get('preferred_date') or 'unspecified'} preferred_time={row.get('preferred_time') or 'unspecified'} "
        f"total_guests={row.get('total_guests') or 'unspecified'} availability_status={availability_status} live_availability_checked={'true' if live_checked else 'false'} sales_verification_required={'true' if sales_verification else 'false'} "
        f"enquiry_status={row.get('enquiry_status') or 'collecting_details'} assigned_salesperson={row.get('assigned_salesperson') or 'unassigned'} "
        f"notes_present={'yes' if row.get('special_requirements') else 'no'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="List recent booking enquiries with masked phone numbers.")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        print("sales_report_refused invalid_limit=true")
        return 2
    try:
        client = get_supabase_client()
        rows = BookingEnquiryRepository(client).list_recent_for_sales(args.limit)
        customer_ids = _id_values(rows, "customer_id")
        service_ids = _id_values(rows, "requested_service_id")
        customers = CustomerRepository(client).list_by_ids(customer_ids) if customer_ids else []
        services = ServiceRepository(client).list_active_by_ids(service_ids) if service_ids else []
    except Exception as error:
        print(_error_output(error))
        return 1
    customer_by_id = {row["id"]: row for row in customers if isinstance(row.get("id"), str)}
    service_by_id = {row["id"]: row for row in services if isinstance(row.get("id"), str)}
    for row in rows:
        print(_format_row(row, customer_by_id, service_by_id))
    print(f"sales_report_complete enquiry_count={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
