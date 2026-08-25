"""Database-contract and repository tests for the durable booking foundation."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, time
from pathlib import Path
import re
import uuid

import pytest

from app.repositories.bookings import BookingRepository
from app.repositories.payments import PaymentRepository
from app.repositories.webhook_events import WebhookEventRepository


MIGRATION = Path(__file__).parents[1] / "supabase" / "migrations" / "202608200016_coimbatore_booking_foundation.sql"


class UniqueViolation(Exception):
    code = "23505"


class Response:
    def __init__(self, data): self.data = data


class Query:
    def __init__(self, client, table):
        self.client, self.table = client, table
        self.action, self.values, self.filters = "select", None, []
        self.statuses, self.desc, self.max_rows, self.single = None, False, None, False

    def select(self, _columns): self.action = "select"; return self
    def insert(self, values): self.action = "insert"; self.values = deepcopy(values); return self
    def update(self, values): self.action = "update"; self.values = deepcopy(values); return self
    def eq(self, field, value): self.filters.append((field, value)); return self
    def in_(self, field, values): self.statuses = (field, set(values)); return self
    def order(self, _field, desc=False): self.desc = desc; return self
    def limit(self, value): self.max_rows = value; return self
    def maybe_single(self): self.single = True; return self

    def _matching(self):
        rows = [row for row in self.client.data[self.table] if all(row.get(k) == v for k, v in self.filters)]
        if self.statuses: rows = [row for row in rows if row.get(self.statuses[0]) in self.statuses[1]]
        if self.desc: rows.reverse()
        if self.max_rows is not None: rows = rows[:self.max_rows]
        return rows

    def execute(self):
        if self.action == "select":
            rows = deepcopy(self._matching())
            return Response(rows[0] if self.single and rows else None if self.single else rows)
        if self.action == "insert":
            self.client.assert_unique(self.table, self.values)
            row = {"id": str(uuid.uuid4()), **self.values}
            row.setdefault("status", {"bookings":"form_pending", "payments":"created", "webhook_events":"received"}[self.table])
            self.client.data[self.table].append(row)
            return Response([deepcopy(row)])
        rows = self._matching()
        for row in rows: row.update(self.values)
        return Response(deepcopy(rows))


class Client:
    def __init__(self): self.data = {"bookings": [], "payments": [], "webhook_events": []}
    def table(self, name): return Query(self, name)
    def assert_unique(self, table, row):
        keys = {
            "bookings": (("booking_ref",), ("zoho_submission_id",)),
            "payments": (("reference_id",), ("provider_payment_link_id",), ("provider_payment_id",)),
            "webhook_events": (("provider", "provider_event_id"),),
        }[table]
        for fields in keys:
            if any(row.get(field) is None for field in fields): continue
            if any(all(existing.get(field) == row.get(field) for field in fields) for existing in self.data[table]):
                raise UniqueViolation()


@pytest.fixture
def client(): return Client()


def booking_record(**overrides):
    return {
        "booking_ref":"CBE-PTN-TEST001", "conversation_id":"conversation-1", "customer_id":"customer-1",
        "location_code":"coimbatore", "product_code":"pontoon_celebration",
        "package_id":"coimbatore_pontoon_standard", "event_date":date(2026, 8, 23).isoformat(),
        "preferred_time":time(18, 0).isoformat(), "guest_count":8, "amount_paise":599900, "currency":"INR",
        **overrides,
    }


def test_booking_create_read_update_and_active_lookup(client):
    repository = BookingRepository(client)
    created = repository.create_booking(booking_record())
    assert created["amount_paise"] == 599900 and isinstance(created["amount_paise"], int)
    assert created["event_date"] == "2026-08-23" and created["preferred_time"] == "18:00:00"
    assert all(created.get(field) is None for field in ("customer_name", "customer_mobile", "customer_email"))
    assert repository.get_booking_by_ref("CBE-PTN-TEST001")["id"] == created["id"]
    assert repository.get_booking_by_id(created["id"])["booking_ref"] == "CBE-PTN-TEST001"
    updated = repository.update_booking(created["id"], {
        "customer_name":"Mandip", "customer_mobile":"+919999999999",
        "customer_email":"mandip@example.com", "status":"form_submitted",
    })
    assert updated["customer_email"] == "mandip@example.com"
    assert repository.get_active_booking_for_conversation("conversation-1")["status"] == "form_submitted"


def test_booking_ref_is_unique(client):
    repository = BookingRepository(client)
    repository.create_booking(booking_record())
    with pytest.raises(UniqueViolation): repository.create_booking(booking_record(customer_id="customer-2"))


def test_payment_create_lookup_update_relationship_and_unique_provider_ids(client):
    booking = BookingRepository(client).create_booking(booking_record())
    repository = PaymentRepository(client)
    payment = repository.create_payment({
        "booking_id":booking["id"], "provider":"razorpay", "reference_id":"payref-1",
        "provider_payment_link_id":"plink_test123", "amount_paise":599900, "currency":"INR",
    })
    assert payment["booking_id"] == booking["id"] and payment["amount_paise"] == 599900
    assert repository.get_payment_by_id(payment["id"])["reference_id"] == "payref-1"
    assert repository.get_payment_by_reference("payref-1")["id"] == payment["id"]
    assert repository.get_payment_by_provider_link_id("plink_test123")["id"] == payment["id"]
    assert repository.get_active_payment_for_booking(booking["id"])["id"] == payment["id"]
    assert repository.update_payment(payment["id"], {"status":"paid", "provider_payment_id":"pay_test123"})["status"] == "paid"
    with pytest.raises(UniqueViolation):
        repository.create_payment({"booking_id":booking["id"], "provider":"razorpay", "reference_id":"payref-2", "provider_payment_link_id":"plink_test123", "amount_paise":599900})
    with pytest.raises(UniqueViolation):
        repository.create_payment({"booking_id":booking["id"], "provider":"razorpay", "reference_id":"payref-3", "provider_payment_id":"pay_test123", "amount_paise":599900})


def test_webhook_event_atomic_duplicate_and_provider_scope(client):
    repository = WebhookEventRepository(client)
    event, created = repository.try_create_webhook_event({"provider":"razorpay", "provider_event_id":"evt_test123", "event_type":"razorpay.payment_link.paid"})
    duplicate, duplicate_created = repository.try_create_webhook_event({"provider":"razorpay", "provider_event_id":"evt_test123", "event_type":"razorpay.payment_link.paid"})
    zoho, zoho_created = repository.try_create_webhook_event({"provider":"zoho", "provider_event_id":"evt_test123", "event_type":"zoho.form_submitted"})
    assert created and not duplicate_created and duplicate["id"] == event["id"]
    assert zoho_created and zoho["provider"] == "zoho"
    assert repository.mark_webhook_event_processed(event["id"])["status"] == "processed"
    assert repository.mark_webhook_event_failed(zoho["id"], "invalid_form")["error_code"] == "invalid_form"


def test_migration_contract_security_constraints_and_no_destructive_sql():
    sql = MIGRATION.read_text(encoding="utf-8").casefold()
    assert all(f"create table public.{table}" in sql for table in ("bookings", "payments", "webhook_events"))
    assert all(f"alter table public.{table} enable row level security" in sql for table in ("bookings", "payments", "webhook_events"))
    assert "unique (provider, provider_event_id)" in sql
    assert "booking_ref text not null unique" in sql
    assert "reference_id text not null unique" in sql
    assert "provider_payment_link_id) where provider_payment_link_id is not null" in sql
    assert "provider_payment_id) where provider_payment_id is not null" in sql
    assert "amount_paise bigint not null check (amount_paise > 0)" in sql
    assert "event_date date" in sql and "preferred_time time without time zone" in sql
    assert "references public.conversations(id) on delete set null" in sql
    assert "references public.customers(id) on delete set null" in sql
    assert "references public.bookings(id) on delete restrict" in sql
    assert "coimbatore_persist_sales_state" not in sql
    assert not re.search(r"\b(drop|truncate|delete\s+from)\b", sql)
    assert "create policy" not in sql


def test_controlled_status_values_are_declared():
    sql = MIGRATION.read_text(encoding="utf-8")
    for status in ("form_pending", "payment_received", "confirmed", "cancelled", "handoff"):
        assert f"'{status}'" in sql
    for status in ("created", "issued", "pending", "paid", "failed", "expired", "cancelled", "verification_failed"):
        assert f"'{status}'" in sql
    for status in ("received", "processing", "processed", "ignored", "failed"):
        assert f"'{status}'" in sql
