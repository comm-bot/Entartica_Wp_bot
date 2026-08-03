"""Safety and empty-table tests for the local booking-enquiry sales report."""

from __future__ import annotations

import sys

from scripts import list_recent_booking_enquiries as report


class _Error(Exception):
    def __init__(self, code, message="", details="", hint=""):
        self.code, self.message, self.details, self.hint = code, message, details, hint


def test_report_empty_table_is_success(monkeypatch, capsys) -> None:
    class Bookings:
        def __init__(self, _client): pass
        def list_recent_for_sales(self, _limit): return []
    class Customers:
        def __init__(self, _client): pass
        def list_by_ids(self, _ids): raise AssertionError("no customer lookup")
    class Services:
        def __init__(self, _client): pass
        def list_active_by_ids(self, _ids): raise AssertionError("no service lookup")
    monkeypatch.setattr(report, "BookingEnquiryRepository", Bookings)
    monkeypatch.setattr(report, "CustomerRepository", Customers)
    monkeypatch.setattr(report, "ServiceRepository", Services)
    monkeypatch.setattr(report, "get_supabase_client", lambda: object())
    monkeypatch.setattr(sys, "argv", ["list_recent_booking_enquiries.py", "--limit", "25"])
    assert report.main() == 0
    assert capsys.readouterr().out == "sales_report_complete enquiry_count=0\n"


def test_report_handles_null_missing_and_active_service_without_ids_or_phone_leakage() -> None:
    row = {"reference": "ENQ-20260722-0001", "customer_id": "customer-internal", "requested_service_id": None,
           "requested_service_text": "Customer wording", "special_requirements": "private notes"}
    customer = {"customer-internal": {"name": "Customer", "whatsapp_number": "+919876543210"}}
    output = report._format_row(row, customer, {})
    assert "matched_service=false" in output and "matched_service_name=unspecified" in output
    assert "+919876543210" not in output and "customer-internal" not in output and "private notes" not in output
    row["requested_service_id"] = "service-internal"
    output = report._format_row(row, customer, {"service-internal": {"name": "Pontoon Boat"}})
    assert "matched_service=true" in output and "matched_service_name=Pontoon Boat" in output
    assert "service-internal" not in output


def test_safe_api_error_output_classifies_relationship_column_permission_and_connection() -> None:
    ambiguous = report._error_output(_Error(300, "multiple relationships", "phone +919876543210", "secret"))
    missing = report._error_output(_Error("42703", 'column "x" does not exist'))
    permission = report._error_output(_Error("42501", "permission denied"))
    connection = report._error_output(ConnectionError("private endpoint"))
    assert "safe_error_code=300" in ambiguous and "reason=relationship_ambiguous" in ambiguous
    assert "safe_error_code=42703" in missing and "reason=column_missing" in missing
    assert "reason=permission_denied" in permission and "reason=connection_failure" in connection
    assert "+919876543210" not in ambiguous and "secret" not in ambiguous and "private endpoint" not in connection


def test_sales_repository_query_has_no_embedded_relationships() -> None:
    from app.repositories.booking_enquiries import BookingEnquiryRepository

    class Query:
        def select(self, columns): self.columns = columns; return self
        def order(self, *_args, **_kwargs): return self
        def limit(self, *_args): return self
        def execute(self): return type("Response", (), {"data": []})()
    class Client:
        def __init__(self): self.query = Query()
        def table(self, _name): return self.query
    client = Client()
    assert BookingEnquiryRepository(client).list_recent_for_sales(25) == []
    assert "customers(" not in client.query.columns and "services(" not in client.query.columns
