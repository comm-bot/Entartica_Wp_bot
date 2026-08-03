"""Opt-in, marker-bound live verification for approved Raipur service linking."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import secrets
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.repositories.booking_enquiries import BookingEnquiryRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.customers import CustomerRepository
from app.repositories.locations import LocationRepository
from app.repositories.services import ServiceRepository
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES
from scripts.list_recent_booking_enquiries import mask_phone


def _rows(response: object) -> list[dict[str, Any]]:
    data = getattr(response, "data", None) if response is not None else None
    return data if isinstance(data, list) else [data] if isinstance(data, dict) else []


def _marker() -> str:
    return f"local-controlled-service-link-test-{secrets.token_hex(8)}"


def _synthetic_phone() -> str:
    return f"+919001{secrets.randbelow(100_000_000):08d}"


def run_live(client: Any) -> dict[str, object]:
    marker, phone = _marker(), _synthetic_phone()
    customer_id: str | None = None
    conversation_id: str | None = None
    created_conversation = False
    outcome: dict[str, object] = {
        "schema_ready": False, "raipur_location_ready": False, "approved_service_ready": False,
        "controlled_customer_created": False, "controlled_conversation_created": False,
        "enquiry_created": False, "service_link_verified": False, "original_text_preserved": False,
        "duplicate_prevented": False, "sales_preview_verified": False, "cleanup_completed": False,
        "reason": "unexpected_database_error",
    }
    try:
        client.table("booking_enquiries").select("requested_service_id,requested_service_text,source,source_message_id").limit(0).execute()
        outcome["schema_ready"] = True
        location = LocationRepository(client).get_location_by_code("raipur")
        if not isinstance(location, dict) or not isinstance(location.get("id"), str):
            outcome["reason"] = "raipur_location_missing"; return outcome
        outcome["raipur_location_ready"] = True
        service = ServiceRepository(client).get_active_by_slug(location["id"], APPROVED_RAIPUR_SERVICES[0].slug)
        if not isinstance(service, dict) or not isinstance(service.get("id"), str):
            outcome["reason"] = "approved_service_missing"; return outcome
        outcome["approved_service_ready"] = True
        customer = CustomerRepository(client).get_or_create(phone, "Controlled Service Link Test")
        if not isinstance(customer.get("id"), str):
            outcome["reason"] = "controlled_customer_create_failed"; return outcome
        customer_id = customer["id"]; outcome["controlled_customer_created"] = True
        conversation = ConversationRepository(client).get_or_create_open(customer_id)
        if not isinstance(conversation.get("id"), str):
            outcome["reason"] = "controlled_conversation_create_failed"; return outcome
        conversation_id = conversation["id"]; created_conversation = True; outcome["controlled_conversation_created"] = True
        text = APPROVED_RAIPUR_SERVICES[0].name
        record = {"reference": f"ENQ-{date.today().strftime('%Y%m%d')}-{secrets.randbelow(1_000_000):06d}",
                  "customer_id": customer_id, "conversation_id": conversation_id, "location_id": location["id"],
                  "requested_service_id": service["id"], "requested_service_text": text,
                  "preferred_date": (date.today() + timedelta(days=30)).isoformat(), "preferred_time": "16:00:00",
                  "adult_count": 2, "child_count": 0, "guest_count": 2, "total_guests": 2,
                  "availability_status": "verification_required", "enquiry_status": "pending_sales_followup",
                  "source": "whatsapp", "source_message_id": marker}
        repo = BookingEnquiryRepository(client)
        stored, created = repo.create_idempotent(record); outcome["enquiry_created"] = created
        read = repo.get_by_source_message("whatsapp", marker)
        outcome["service_link_verified"] = isinstance(read, dict) and read.get("requested_service_id") == service["id"]
        outcome["original_text_preserved"] = isinstance(read, dict) and read.get("requested_service_text") == text
        _, created_again = repo.create_idempotent(record)
        matches = _rows(client.table("booking_enquiries").select("id").eq("source", "whatsapp").eq("source_message_id", marker).execute())
        outcome["duplicate_prevented"] = not created_again and len(matches) == 1
        preview = f"phone={mask_phone(phone)} matched_service=true approved_service_name={text} activity={text}"
        outcome["sales_preview_verified"] = "***" in preview and service["id"] not in preview and phone not in preview
        outcome["reason"] = "completed" if all(outcome[key] for key in ("enquiry_created", "service_link_verified", "original_text_preserved", "duplicate_prevented", "sales_preview_verified")) else "read_back_failed"
        return outcome
    except Exception as error:
        code = str(getattr(error, "code", ""))
        outcome["reason"] = "permission_failure" if code in {"42501", "403"} else "unexpected_database_error"
        return outcome
    finally:
        try:
            client.table("booking_enquiries").delete().eq("source", "whatsapp").eq("source_message_id", marker).execute()
            if created_conversation and conversation_id:
                client.table("conversations").delete().eq("id", conversation_id).execute()
            if customer_id:
                client.table("customers").delete().eq("id", customer_id).execute()
            outcome["cleanup_completed"] = not _rows(client.table("booking_enquiries").select("id").eq("source", "whatsapp").eq("source_message_id", marker).execute())
        except Exception:
            outcome["cleanup_completed"] = False


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--confirm-live-write", action="store_true")
    args = parser.parse_args()
    if not args.confirm_live_write:
        print("mode=dry_run live_write_performed=false whatsapp_sent=false exotel_called=false openai_called=false reason=dry_run")
        return 0
    settings = Settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        print("mode=live live_write_performed=false reason=configuration_missing")
        return 1
    outcome = run_live(get_supabase_client())
    values = {"mode": "live", **outcome, "whatsapp_sent": False, "exotel_called": False, "openai_called": False}
    print(" ".join(f"{key}={str(value).lower() if isinstance(value, bool) else value}" for key, value in values.items()))
    return 0 if outcome["reason"] == "completed" and outcome["cleanup_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
