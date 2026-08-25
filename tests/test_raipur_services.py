"""Tests for the approved-only Raipur service seed and linking workflow."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
import sys
from unittest.mock import MagicMock

from app.repositories.services import ServiceRepository
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, SOURCE_FILENAME, normalize_service_text
from scripts import test_live_raipur_service_linking as live_script
from scripts import verify_raipur_services as verify_script


ROOT = Path(__file__).resolve().parents[1]


class _Response:
    def __init__(self, data=None): self.data = data


class _Query:
    def __init__(self, data): self.data = data
    def select(self, *_args): return self
    def eq(self, *_args): return self
    def order(self, *_args, **_kwargs): return self
    def maybe_single(self): return self
    def execute(self): return _Response(self.data)


class _Client:
    def __init__(self, locations, services): self.locations, self.services = locations, services
    def table(self, name): return _Query(self.locations if name == "locations" else self.services)


def _location() -> dict[str, object]:
    return {"id": "raipur-id", "slug": "raipur", "is_active": True}


def _approved_rows(*, active: bool = True) -> list[dict[str, object]]:
    return [{"id": f"service-{index}", "name": item.name, "slug": item.slug, "is_active": active}
            for index, item in enumerate(APPROVED_RAIPUR_SERVICES)]


def test_manifest_contains_only_safe_approved_service_fields() -> None:
    assert len(APPROVED_RAIPUR_SERVICES) == 19
    assert {item.slug for item in APPROVED_RAIPUR_SERVICES} == {item.slug for item in APPROVED_RAIPUR_SERVICES}
    assert SOURCE_FILENAME == "raipur_services.docx"
    assert all(not any(word in item.name.casefold() for word in ("price", "payment", "availability")) for item in APPROVED_RAIPUR_SERVICES)


def test_verifier_reports_missing_active_inactive_duplicate_and_unexpected_services() -> None:
    missing = verify_script.inspect_raipur_services(_Client([_location()], []))
    assert missing["reason"] == "approved_services_missing" and missing["missing_approved_services"] == 19
    ready = verify_script.inspect_raipur_services(_Client([_location()], _approved_rows()))
    assert ready["reason"] == "ready" and ready["active_matching_services"] == 19
    inactive = verify_script.inspect_raipur_services(_Client([_location()], _approved_rows(active=False)))
    assert inactive["inactive_matching_services"] == 19
    duplicate_rows = _approved_rows() + [{"id": "duplicate", "name": APPROVED_RAIPUR_SERVICES[0].name, "slug": APPROVED_RAIPUR_SERVICES[0].slug, "is_active": True}]
    duplicate = verify_script.inspect_raipur_services(_Client([_location()], duplicate_rows))
    assert duplicate["reason"] == "duplicate_raipur_services_require_review"
    unexpected = verify_script.inspect_raipur_services(_Client([_location()], _approved_rows() + [{"id": "x", "name": "Other", "slug": "other", "is_active": True}]))
    assert unexpected["reason"] == "unexpected_raipur_service_requires_review"


def test_verifier_refuses_missing_or_duplicate_raipur_location() -> None:
    assert verify_script.inspect_raipur_services(_Client([], []))["reason"] == "raipur_location_missing"
    assert verify_script.inspect_raipur_services(_Client([_location(), _location() | {"id": "two"}], []))["reason"] == "duplicate_raipur_locations_require_review"


def test_exact_normalized_matching_excludes_inactive_other_location_and_ambiguous() -> None:
    active = {"id": "boat", "name": "Pontoon Boat", "slug": "pontoon-boat"}
    query = MagicMock(); query.select.return_value = query; query.eq.return_value = query; query.order.return_value = query; query.execute.return_value = _Response([active])
    client = MagicMock(); client.table.return_value = query
    repository = ServiceRepository(client)
    assert repository.find_active_by_customer_text("raipur", " pontoon-boat! ") == active
    assert repository.find_active_by_customer_text("raipur", "unapproved helicopter") is None
    assert normalize_service_text("Kids'   Paddle-Boat") == "kids paddle boat"

    duplicate_query = MagicMock(); duplicate_query.select.return_value = duplicate_query; duplicate_query.eq.return_value = duplicate_query; duplicate_query.order.return_value = duplicate_query; duplicate_query.execute.return_value = _Response([active, active | {"id": "boat-two"}])
    duplicate_client = MagicMock(); duplicate_client.table.return_value = duplicate_query
    assert ServiceRepository(duplicate_client).find_active_by_customer_text("raipur", "Pontoon Boat") is None


def test_normalize_service_text_corrects_known_typos() -> None:
    assert normalize_service_text("party baot") == "party boat"
    assert normalize_service_text("kayk") == "kayak"
    assert normalize_service_text("aqua cyle") == "aqua cycle"
    assert normalize_service_text("bumber") == "bumper"
    assert normalize_service_text("bumber boat") == "bumper boat"


class _BookingRepository:
    def __init__(self): self.record = None
    def create_idempotent(self, record): self.record = dict(record); return self.record, True


class _Services:
    def __init__(self, row): self.row = row
    def find_active_by_customer_text(self, _location_id, _text): return self.row


def _details(text: str) -> BookingDetails:
    return BookingDetails("Customer", text, date(2026, 8, 1), time(16), 2, 0, 2)


def test_booking_service_links_only_a_safe_match_and_preserves_original_text() -> None:
    repository = _BookingRepository()
    service = BookingEnquiryService(repository, service_repository=_Services({"id": "approved-service"}))
    result = service.submit(_details("Pontoon boat!!"), customer_id="customer", conversation_id="conversation", location_id="raipur", source_message_id="msg", now=datetime(2026, 7, 22, tzinfo=timezone.utc))
    assert result.created and repository.record["requested_service_id"] == "approved-service"
    assert repository.record["requested_service_text"] == "Pontoon boat!!"

    unknown_repository = _BookingRepository()
    BookingEnquiryService(unknown_repository, service_repository=_Services(None)).submit(_details("Unapproved activity"), customer_id="customer", conversation_id="conversation", location_id="raipur", source_message_id="msg2", now=datetime(2026, 7, 22, tzinfo=timezone.utc))
    assert unknown_repository.record["requested_service_id"] is None


def test_manual_migration_is_raipur_only_and_does_not_touch_protected_data() -> None:
    sql = (ROOT / "supabase/migrations/202607200010_seed_raipur_services.sql").read_text(encoding="utf-8").casefold()
    executable = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert "slug = 'raipur'" in sql and "booking_enquiries" not in executable
    assert all(word not in executable for word in ("delete", "customers", "conversations", "messages", "knowledge_documents"))
    assert "raise exception 'duplicate raipur service records require review'" in sql


def test_live_service_linking_dry_run_never_creates_client(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["test_live_raipur_service_linking.py"])
    monkeypatch.setattr(live_script, "get_supabase_client", lambda: (_ for _ in ()).throw(AssertionError("no client")))
    assert live_script.main() == 0
    output = capsys.readouterr().out
    assert "mode=dry_run" in output and "live_write_performed=false" in output
    assert "whatsapp_sent=false" in output and "openai_called=false" in output
