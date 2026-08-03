"""Tests for local-only availability and booking-enquiry draft workflows."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sys

from app.services.availability import AvailabilityResult
from app.services.booking_enquiries import BookingDetails, BookingEnquiryService
from scripts import list_recent_booking_enquiries as sales_script
from scripts import verify_booking_enquiry_schema as schema_script
from scripts import test_live_booking_enquiry_persistence as live_script


class FakeAvailabilityProvider:
    def __init__(self, result: AvailabilityResult) -> None:
        self.result = result
        self.requests = []

    def check(self, request):
        self.requests.append(request)
        return self.result


class FakeBookingRepository:
    def __init__(self) -> None:
        self.by_message: dict[str, dict[str, object]] = {}
        self.records: list[dict[str, object]] = []

    def create_idempotent(self, record):
        message_id = record["source_message_id"]
        if message_id in self.by_message:
            return self.by_message[message_id], False
        stored = dict(record)
        self.by_message[message_id] = stored
        self.records.append(stored)
        return stored, True


def _details(**overrides) -> BookingDetails:
    values = {
        "customer_name": "Customer", "requested_service_text": "Boating",
        "preferred_date": date(2026, 7, 25), "preferred_time": time(16, 0),
        "adults_count": 2, "children_count": 1, "total_guests": 3,
        "special_requirements": "Accessible entry request", "requested_service_id": "service-1",
    }
    values.update(overrides)
    return BookingDetails(**values)


def _submit(service: BookingEnquiryService, details: BookingDetails | None = None, *, message_id: str = "provider-1"):
    return service.submit(
        details or _details(), customer_id="customer-1", conversation_id="conversation-1",
        location_id="raipur-location", source_message_id=message_id,
        now=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )


def test_live_availability_found_creates_pending_sales_enquiry_without_confirmation() -> None:
    repository = FakeBookingRepository()
    provider = FakeAvailabilityProvider(AvailabilityResult("available", datetime(2026, 7, 21, tzinfo=timezone.utc)))
    result = _submit(BookingEnquiryService(repository, provider))

    assert result.availability_status == "available"
    assert result.enquiry_state == "availability_found"
    assert result.human_followup_required is True
    assert result.created is True
    assert repository.records[0]["enquiry_status"] == "availability_found"
    assert repository.records[0]["source"] == "whatsapp"
    assert "payment" not in repository.records[0]
    assert "confirmed" not in str(repository.records[0].values()).casefold()


def test_not_found_unavailable_and_stale_availability_never_guess() -> None:
    repository = FakeBookingRepository()
    not_found = BookingEnquiryService(
        repository, FakeAvailabilityProvider(AvailabilityResult("not_available", datetime(2026, 7, 21, tzinfo=timezone.utc)))
    )
    assert _submit(not_found).enquiry_state == "availability_not_found"

    unavailable = BookingEnquiryService(repository)
    result = _submit(unavailable, message_id="provider-2")
    assert result.availability_status == "verification_required"
    assert result.enquiry_state == "pending_availability_check"

    stale_provider = FakeAvailabilityProvider(AvailabilityResult("available", datetime(2026, 7, 20, tzinfo=timezone.utc)))
    stale = BookingEnquiryService(repository, stale_provider)
    stale_result = _submit(stale, message_id="provider-3")
    assert stale_result.availability_status == "stale"
    assert stale_result.human_followup_required is True


def test_missing_details_are_collected_one_field_at_a_time_and_phone_is_reused() -> None:
    repository = FakeBookingRepository()
    service = BookingEnquiryService(repository)
    assert _submit(service, _details(customer_name=None)).next_required_field == "customer_name"
    assert _submit(service, _details(requested_service_text=None)).next_required_field == "requested_service_text"
    assert _submit(service, _details(total_guests=4)).next_required_field == "total_guests"

    result = _submit(service, message_id="provider-complete")
    assert result.created is True
    assert "whatsapp_number" not in repository.records[0]
    assert repository.records[0]["customer_id"] == "customer-1"


def test_duplicate_inbound_message_creates_only_one_enquiry() -> None:
    repository = FakeBookingRepository()
    service = BookingEnquiryService(repository)
    assert _submit(service, message_id="duplicate-message").created is True
    assert _submit(service, message_id="duplicate-message").created is False
    assert len(repository.records) == 1


def test_pricing_routes_to_sales_without_price_quote_payment_or_confirmation() -> None:
    repository = FakeBookingRepository()
    result = BookingEnquiryService(repository).pricing_handover(
        _details(), customer_id="customer-1", conversation_id="conversation-1",
        location_id="raipur-location", source_message_id="pricing-message",
    )

    assert result.pricing_status == "human_quotation_required"
    assert result.human_followup_required is True
    assert result.enquiry_state == "pending_availability_check"
    assert all("price" not in key and "payment" not in key for key in repository.records[0])


def test_sales_report_masks_phone_and_never_prints_notes_or_internal_ids(monkeypatch, capsys) -> None:
    rows = [{
        "reference": "ENQ-20260721-0001", "requested_service_text": "Boating",
        "customer_id": "customer-1", "requested_service_id": "service-1",
        "preferred_date": "2026-07-25", "preferred_time": "16:00:00", "total_guests": 3,
        "availability_status": "verification_required", "enquiry_status": "pending_availability_check",
        "assigned_salesperson": None, "special_requirements": "private note",
    }]

    class FakeSalesRepository:
        def __init__(self, _client): pass
        def list_recent_for_sales(self, _limit): return rows
    class FakeCustomers:
        def __init__(self, _client): pass
        def list_by_ids(self, _ids): return [{"id": "customer-1", "name": "Customer", "whatsapp_number": "+919876543210"}]
    class FakeServices:
        def __init__(self, _client): pass
        def list_active_by_ids(self, _ids): return [{"id": "service-1", "name": "Pontoon Boat"}]

    monkeypatch.setattr(sales_script, "BookingEnquiryRepository", FakeSalesRepository)
    monkeypatch.setattr(sales_script, "CustomerRepository", FakeCustomers)
    monkeypatch.setattr(sales_script, "ServiceRepository", FakeServices)
    monkeypatch.setattr(sales_script, "get_supabase_client", lambda: object())
    monkeypatch.setattr(sys, "argv", ["list_recent_booking_enquiries.py", "--limit", "1"])
    assert sales_script.main() == 0
    output = capsys.readouterr().out
    assert "***3210" in output
    assert "+919876543210" not in output
    assert "private note" not in output
    assert "customer-1" not in output
    assert "notes_present=yes" in output
    assert "matched_service=true" in output and "matched_service_name=Pontoon Boat" in output


def test_local_draft_has_no_retrieval_exotel_or_whatsapp_outbound_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / "app" / "services" / "booking_enquiries.py").read_text(encoding="utf-8").casefold()
    availability = (root / "app" / "services" / "availability.py").read_text(encoding="utf-8").casefold()
    assert "app.integrations.exotel" not in workflow + availability
    assert "send_whatsapp" not in workflow + availability
    assert "embed_texts" not in workflow + availability


class _Response:
    def __init__(self, data=None): self.data = data


class _Query:
    def __init__(self, error=None): self.error = error
    def select(self, *_args): return self
    def limit(self, *_args): return self
    def execute(self):
        if self.error: raise self.error
        return _Response()


class _SchemaClient:
    def __init__(self, *, table_errors=None, rpc_data=None, rpc_error=None):
        self.table_errors = table_errors or {}; self.rpc_data = rpc_data; self.rpc_error = rpc_error
    def table(self, name): return _Query(self.table_errors.get(name))
    def rpc(self, _name): return _Query(self.rpc_error) if self.rpc_error else _QueryWithData(self.rpc_data)


class _QueryWithData(_Query):
    def __init__(self, data): super().__init__(); self.data=data
    def execute(self): return _Response(self.data)


class _Error(Exception):
    def __init__(self, code, message=""):
        self.code=code; self.message=message


def test_schema_verifier_complete_schema_and_empty_table() -> None:
    # Empty-table LIMIT 0 responses must still prove all columns are selectable.
    report = schema_script.inspect_schema(_SchemaClient(rpc_data={"idempotency_index_exists": True, "missing_constraints": []}))
    assert report.table_exists is True
    assert report.missing_columns == ()
    assert report.missing_indexes == ()
    assert report.missing_constraints == ()
    assert report.schema_ready is True


def test_schema_verifier_reports_missing_table_column_index_permission_and_connection() -> None:
    table = schema_script.inspect_schema(_SchemaClient(table_errors={"booking_enquiries": _Error("PGRST205")}))
    assert table.reason == "table_missing"
    column = schema_script.inspect_schema(_SchemaClient(table_errors={"booking_enquiries": _Error("42703", 'column "source" does not exist')}))
    assert column.reason == "column_missing" and "source" in column.missing_columns
    index = schema_script.inspect_schema(_SchemaClient(rpc_data={"idempotency_index_exists": False, "missing_constraints": []}))
    assert index.reason == "index_missing" and index.missing_indexes == (schema_script.IDEMPOTENCY_INDEX,)
    permission = schema_script.inspect_schema(_SchemaClient(table_errors={"booking_enquiries": _Error("42501")}))
    assert permission.database_error == "permission_failure"
    connection = schema_script.inspect_schema(_SchemaClient(table_errors={"booking_enquiries": ConnectionError()}))
    assert connection.database_error == "connection_failure"


def test_live_persistence_dry_run_never_creates_a_client(monkeypatch, capsys) -> None:
    class Settings:
        supabase_url = "configured"
        supabase_secret_key = object()

    monkeypatch.setattr(live_script, "Settings", Settings)
    monkeypatch.setattr(live_script, "get_supabase_client", lambda: (_ for _ in ()).throw(AssertionError("no write client")))
    monkeypatch.setattr(sys, "argv", ["test_live_booking_enquiry_persistence.py"])
    assert live_script.main() == 0
    output = capsys.readouterr().out
    assert "mode=dry_run" in output and "live_write_performed=false" in output


def test_live_persistence_requires_flag_and_safe_output_has_no_sensitive_values(monkeypatch, capsys) -> None:
    class Settings:
        supabase_url = "configured"
        supabase_secret_key = object()

    monkeypatch.setattr(live_script, "Settings", Settings)
    monkeypatch.setattr(live_script, "run_live", lambda _client: {
        "schema_ready": True, "controlled_customer_created": True, "controlled_conversation_created": True,
        "enquiry_created": True, "read_back_verified": True, "duplicate_prevented": True,
        "matching_enquiry_count": 1, "sales_preview_verified": True, "cleanup_completed": True,
        "reason": "completed",
    })
    monkeypatch.setattr(live_script, "get_supabase_client", lambda: object())
    monkeypatch.setattr(sys, "argv", ["test_live_booking_enquiry_persistence.py", "--confirm-live-write"])
    assert live_script.main() == 0
    output = capsys.readouterr().out
    assert "duplicate_prevented=true" in output and "whatsapp_sent=false" in output
    assert "+91" not in output and "Controlled persistence verification only" not in output
    source = (Path(__file__).resolve().parents[1] / "scripts" / "test_live_booking_enquiry_persistence.py").read_text(encoding="utf-8").casefold()
    assert '"source":"whatsapp"' in source and "app.integrations.exotel" not in source and "embed_texts" not in source


def test_live_persistence_refuses_when_raipur_location_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(live_script, "_schema_columns_ready", lambda _client: True)

    class Locations:
        def get_location_by_code(self, _code): return None

    monkeypatch.setattr(live_script, "LocationRepository", lambda _client: Locations())
    class CleanupQuery:
        def delete(self): return self
        def eq(self, *_args): return self
        def select(self, *_args): return self
        def execute(self): return _Response([])
    class Client:
        def table(self, _name): return CleanupQuery()
    outcome = live_script.run_live(Client())
    assert outcome["reason"] == "raipur_location_missing"
    assert outcome["controlled_customer_created"] is False
    assert outcome["cleanup_completed"] is True
