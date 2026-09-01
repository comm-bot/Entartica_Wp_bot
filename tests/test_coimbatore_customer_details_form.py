from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import uuid

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import coimbatore_customer_details as api
from app.services.coimbatore.customer_details import (
    CustomerDetailsFormService, DetailsSubmission, IssuedDetailsForm,
    customer_details_complete, validate_details,
)
from app.services.coimbatore.inbound_orchestrator import CoimbatoreInboundOrchestrator


MIGRATION = Path(__file__).parents[1] / "supabase" / "migrations" / "202608240017_coimbatore_customer_details_form.sql"
FLOW = Path(__file__).parents[1] / "config" / "Coimbatore" / "coimbatore_customer_details_flow.json"


class Response:
    def __init__(self, data): self.data = data


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.action, self.values = db, table, "select", None
        self.filters, self.single, self.maximum = [], False, None
    def select(self, _columns): self.action = "select"; return self
    def insert(self, values): self.action, self.values = "insert", deepcopy(values); return self
    def update(self, values): self.action, self.values = "update", deepcopy(values); return self
    def eq(self, key, value): self.filters.append((key, value)); return self
    def maybe_single(self): self.single = True; return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, maximum): self.maximum = maximum; return self
    def _rows(self):
        rows = [row for row in self.db.data[self.table] if all(row.get(k) == v for k, v in self.filters)]
        return rows[:self.maximum] if self.maximum else rows
    def execute(self):
        if self.action == "select":
            rows = deepcopy(self._rows())
            return Response(rows[0] if self.single and rows else None if self.single else rows)
        if self.action == "insert":
            row = {"id": str(uuid.uuid4()), **self.values}
            self.db.data[self.table].append(row)
            return Response([deepcopy(row)])
        rows = self._rows()
        for row in rows: row.update(self.values)
        return Response(deepcopy(rows))


class Database:
    def __init__(self):
        self.data = {
            "customers": [{"id":"customer-1", "whatsapp_number":"+919876543210", "name":None, "email":None}],
            "conversations": [{"id":"conversation-1", "customer_id":"customer-1", "service_context":{}}],
            "customer_detail_forms": [], "messages": [],
        }
    def table(self, name): return Query(self, name)


def service(db=None):
    database = db or Database()
    return database, CustomerDetailsFormService(
        database, public_base_url="https://forms.entartica.test", ttl_minutes=30,
    )


def test_secure_form_token_url_contains_no_phone_or_internal_identity():
    db, forms = service()
    issued = forms.issue(customer_id="customer-1", conversation_id="conversation-1")
    assert issued.url.startswith("https://forms.entartica.test/coimbatore/details/")
    assert "+919876543210" not in issued.url and "customer-1" not in issued.url and "conversation-1" not in issued.url
    assert len(issued.token) >= 40 and db.data["customer_detail_forms"][0]["token_digest"] != issued.token


def test_valid_submission_uses_server_side_whatsapp_identity_and_is_idempotent():
    db, forms = service()
    issued = forms.issue(customer_id="customer-1", conversation_id="conversation-1")
    first = forms.submit(issued.token, name="  Rahul   Sharma ", email=" RAHUL@example.com ")
    second = forms.submit(issued.token, name="Rahul Sharma", email="rahul@example.com")
    customer = db.data["customers"][0]
    context = db.data["conversations"][0]["service_context"]
    assert first.accepted and not first.duplicate and second.accepted and second.duplicate
    assert customer["name"] == "Rahul Sharma" and customer["email"] == "rahul@example.com"
    assert customer["whatsapp_number"] == "+919876543210"
    assert context["booking_details"]["customer_name"] == "Rahul Sharma"
    assert context["form_values"]["customer_email"] == "rahul@example.com"
    assert context["form_values"]["customer_details_complete"] is True
    assert context["form_status"] == "completed" and len(db.data["customers"]) == 1


def test_token_is_bound_to_its_original_customer_and_conversation():
    db, forms = service()
    db.data["customers"].append({"id":"customer-2", "whatsapp_number":"+919999999999", "name":None, "email":None})
    db.data["conversations"].append({"id":"conversation-2", "customer_id":"customer-2", "service_context":{}})
    issued = forms.issue(customer_id="customer-1", conversation_id="conversation-1")
    result = forms.submit(issued.token, name="Rahul Sharma", email="rahul@example.com")
    assert result.customer["id"] == "customer-1" and result.conversation_id == "conversation-1"
    assert db.data["customers"][1]["name"] is None and db.data["conversations"][1]["service_context"] == {}


def test_native_flow_token_submission_requires_matching_exotel_identity():
    db = Database()
    forms = CustomerDetailsFormService(db, public_base_url=None, ttl_minutes=30)
    token = forms.issue_native_token(customer_id="customer-1", conversation_id="conversation-1")
    rejected = forms.submit_native(token, customer_id="customer-2", conversation_id="conversation-2",
                                   name="Attacker", email="attacker@example.com")
    accepted = forms.submit_native(token, customer_id="customer-1", conversation_id="conversation-1",
                                   name="Rahul Sharma", email="rahul@example.com")
    assert not rejected.accepted and rejected.reason == "identity_mismatch"
    assert accepted.accepted and db.data["customers"][0]["whatsapp_number"] == "+919876543210"


def test_invalid_expired_and_missing_details_are_rejected_without_mutation():
    db, forms = service()
    issued = forms.issue(customer_id="customer-1", conversation_id="conversation-1")
    assert forms.submit(issued.token, name="", email="rahul@example.com").reason == "invalid_name"
    assert forms.submit(issued.token, name="Rahul", email="not-an-email").reason == "invalid_email"
    assert forms.submit(issued.token, name="Rahul", email="").reason == "invalid_email"
    assert forms.submit("x" * 40, name="Rahul", email="rahul@example.com").reason == "invalid_token"
    db.data["customer_detail_forms"][0]["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert forms.submit(issued.token, name="Rahul", email="rahul@example.com").reason == "expired_token"
    assert db.data["customers"][0]["name"] is None


def test_email_validation_rejects_obvious_invalid_values_and_trims_valid_values():
    assert validate_details(" Rahul Sharma ", " RAHUL@example.com ") == ("Rahul Sharma", "rahul@example.com", None)
    for value in ("rahul", "@example.com", "rahul@", "rahul@example", "rahul..sharma@example.com"):
        assert validate_details("Rahul", value)[2] == "invalid_email"


class RouteService:
    def __init__(self, submission=None, resolved=None):
        self.submission = submission
        self.resolved = resolved or ({"status":"pending"}, "ok")
    def resolve(self, _token): return self.resolved
    def submit(self, *_args, **_kwargs): return self.submission


class RouteDelivery:
    def __init__(self): self.calls = []
    async def send(self, **kwargs): self.calls.append(kwargs); return True


def route_client(monkeypatch, route_service, delivery=None):
    delivery = delivery or RouteDelivery()
    monkeypatch.setattr(api, "get_customer_details_service", lambda: route_service)
    monkeypatch.setattr(api, "get_customer_details_delivery", lambda: delivery)
    app = FastAPI(); app.include_router(api.router)
    return TestClient(app), delivery


def test_mobile_form_contains_only_name_and_email_and_never_phone(monkeypatch):
    client, _ = route_client(monkeypatch, RouteService())
    response = client.get("/coimbatore/details/secure-token-value")
    body = response.text
    assert response.status_code == 200 and 'name="full_name"' in body and 'name="email"' in body
    assert "WhatsApp" not in body and 'name="phone"' not in body and 'name="whatsapp"' not in body
    assert 'name="' in body and 'viewport' in body and "Continue" in body


def test_successful_web_submission_sends_named_qualification_once(monkeypatch):
    customer = {"id":"customer-1", "name":"Rahul Sharma", "email":"rahul@example.com", "whatsapp_number":"+919876543210"}
    submission = DetailsSubmission(True, "completed", customer, "conversation-1", "form-1")
    client, delivery = route_client(monkeypatch, RouteService(submission))
    response = client.post("/coimbatore/details/secure-token-value", data={"full_name":"Rahul Sharma", "email":"rahul@example.com"})
    assert response.status_code == 200 and "return to WhatsApp" in response.text
    assert len(delivery.calls) == 1
    text = delivery.calls[0]["content"]
    assert text.startswith("Thanks Rahul! 👋") and "How many guests" in text and "💡 eg. 7 , 26/08/2026" in text
    assert "+919876543210" not in text and "share your name" not in text.casefold() and "email" not in text.casefold()


def test_duplicate_web_submission_does_not_send_second_continuation(monkeypatch):
    customer = {"id":"customer-1", "name":"Rahul Sharma", "email":"rahul@example.com", "whatsapp_number":"+919876543210"}
    submission = DetailsSubmission(True, "already_completed", customer, "conversation-1", "form-1", True)
    client, delivery = route_client(monkeypatch, RouteService(submission))
    response = client.post("/coimbatore/details/secure-token-value", data={"full_name":"Rahul Sharma", "email":"rahul@example.com"})
    assert response.status_code == 200 and delivery.calls == []


def test_route_validation_and_invalid_token_do_not_send(monkeypatch):
    for reason, status in (("invalid_name", 422), ("invalid_email", 422), ("invalid_token", 404), ("expired_token", 410)):
        client, delivery = route_client(monkeypatch, RouteService(DetailsSubmission(False, reason)))
        response = client.post("/coimbatore/details/token-token-token-token-token-token", data={"full_name":"", "email":"bad"})
        assert response.status_code == status and delivery.calls == []


class FormIssuer:
    def __init__(self): self.calls = []
    def issue(self, **kwargs): self.calls.append(kwargs); return IssuedDetailsForm("opaque", "https://forms.entartica.test/coimbatore/details/opaque")
    def issue_native_token(self, **kwargs): self.calls.append(kwargs); return "opaque-native-flow-token"


class Contexts:
    def save_service_context(self, *_args): return True


def prechat_result(message):
    bot = CoimbatoreInboundOrchestrator.__new__(CoimbatoreInboundOrchestrator)
    bot._settings = SimpleNamespace(coimbatore_customer_details_form_enabled=True,
                                    coimbatore_customer_details_flow_id="27532617159750529",
                                    coimbatore_persist_sales_state=False)
    bot._customer_details, bot._contexts = FormIssuer(), Contexts()
    return bot._process_turn(SimpleNamespace(content=message),
        customer={"id":"customer-1", "whatsapp_number":"+919876543210", "name":None, "email":None},
        conversation={"id":"conversation-1"}, source_message_id="message-1")


def test_new_hi_and_hello_are_blocked_on_details_form_before_qualification():
    for greeting in ("Hi", "Hello"):
        result = prechat_result(greeting)
        assert result.reason_code == "coimbatore_customer_details_required"
        assert "How many guests" not in result.draft_text
        interactive = result.safe_metadata["interactive_message"]
        assert interactive["kind"] == "flow" and interactive["button_label"] == "Complete Details"
        assert interactive["flow_id"] == "27532617159750529"
        assert interactive["flow_screen_id"] == "CUSTOMER_DETAILS"
        assert "http" not in result.draft_text.casefold()
        assert result.context.pending_field is None and result.context.form_status == "in_progress"


def test_new_customer_first_hi_retries_transient_flow_token_disconnect():
    class FlakyFormIssuer(FormIssuer):
        attempts = 0

        def issue_native_token(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return super().issue_native_token(**kwargs)

    bot = CoimbatoreInboundOrchestrator.__new__(CoimbatoreInboundOrchestrator)
    bot._settings = SimpleNamespace(
        coimbatore_customer_details_form_enabled=True,
        coimbatore_customer_details_flow_id="1604509561221337",
        coimbatore_persist_sales_state=False,
    )
    issuer = FlakyFormIssuer()
    bot._customer_details, bot._contexts = issuer, Contexts()

    result = bot._process_turn(
        SimpleNamespace(content="Hii"),
        customer={"id":"customer-1", "whatsapp_number":"+919876543210", "name":None, "email":None},
        conversation={"id":"conversation-1"},
        source_message_id="message-1",
    )

    assert issuer.attempts == 2
    assert result.safe_metadata["interactive_message"]["kind"] == "flow"
    assert result.safe_metadata["interactive_message"]["flow_id"] == "1604509561221337"
    assert "temporarily unavailable" not in result.draft_text


def test_native_whatsapp_flow_submission_persists_details_and_returns_named_qualification():
    db = Database()
    forms = CustomerDetailsFormService(db, public_base_url=None, ttl_minutes=30)
    token = forms.issue_native_token(customer_id="customer-1", conversation_id="conversation-1")
    bot = CoimbatoreInboundOrchestrator.__new__(CoimbatoreInboundOrchestrator)
    bot._settings = SimpleNamespace(coimbatore_customer_details_form_enabled=True,
                                    coimbatore_customer_details_flow_id="published-flow-id",
                                    coimbatore_persist_sales_state=False)
    bot._customer_details, bot._contexts = forms, Contexts()
    message = SimpleNamespace(content="Sent", message_type="flow", form_response={
        "flow_token": token, "full_name": "Rahul Sharma", "email": "rahul@example.com",
    })
    result = bot._process_turn(message,
        customer={"id":"customer-1", "whatsapp_number":"+919876543210", "name":None, "email":None},
        conversation={"id":"conversation-1"}, source_message_id="message-flow-1")
    assert result.reason_code == "coimbatore_customer_details_completed"
    assert result.draft_text.startswith("Thanks Rahul! 👋") and "How many guests" in result.draft_text
    assert result.context.details.customer_name == "Rahul Sharma"
    assert result.context.pending_field == "total_guests"
    assert db.data["customers"][0]["email"] == "rahul@example.com"


def test_completed_identity_predicate_requires_name_and_email_but_not_phone_input():
    assert customer_details_complete({"name":"Rahul", "email":"rahul@example.com", "whatsapp_number":"+919876543210"})
    assert not customer_details_complete({"name":"Rahul", "email":None, "whatsapp_number":"+919876543210"})


def test_completed_customer_bypasses_form_and_name_is_hydrated_into_chatbot_context():
    from tests.test_coimbatore_llm_brain import service as existing_service
    bot = existing_service(persist=False)
    bot._settings.coimbatore_customer_details_form_enabled = True
    bot._customer_details = FormIssuer()
    result = bot.process(SimpleNamespace(content="Hello"),
        customer={"id":"customer-1", "whatsapp_number":"+919876543210",
                  "name":"Rahul Sharma", "email":"rahul@example.com"},
        conversation={"id":"conversation-1"}, source_message_id="message-1")
    assert result.reason_code != "coimbatore_customer_details_required"
    assert "Complete Details" not in result.draft_text
    assert result.context.details.customer_name == "Rahul Sharma"
    assert result.context.form_values["customer_email"] == "rahul@example.com"


def test_completed_customer_continues_existing_guest_date_and_book_now_without_identity_questions():
    from tests.test_coimbatore_llm_brain import service as existing_service
    bot = existing_service(persist=False, media=False)
    bot._settings.coimbatore_customer_details_form_enabled = True
    bot._customer_details = FormIssuer()
    customer = {"id":"customer-1", "whatsapp_number":"+919876543210",
                "name":"Rahul Sharma", "email":"rahul@example.com"}
    conversation = {"id":"conversation-1"}
    package = bot.process(SimpleNamespace(content="7, 26/10/2026"), customer=customer,
                          conversation=conversation, source_message_id="message-1")
    assert package.context.details.total_guests == 7
    assert package.context.details.preferred_date.isoformat() == "2026-10-26"
    assert package.safe_metadata["package_id"] == "coimbatore_pontoon_standard"
    bot.confirm_standard_package_presented(package, "customer-1", "conversation-1")
    booking = bot.process(SimpleNamespace(content="Book Now"), customer=customer,
                          conversation=conversation, source_message_id="message-2")
    lowered = booking.draft_text.casefold()
    assert "share your name" not in lowered
    assert "share your email" not in lowered
    assert "share your whatsapp number" not in lowered
    assert booking.context.details.customer_name == "Rahul Sharma"


def test_migration_adds_customer_email_and_secure_conversation_bound_form_table():
    sql = MIGRATION.read_text(encoding="utf-8").casefold()
    assert "alter table public.customers" in sql and "add column if not exists email" in sql
    assert "create table if not exists public.customer_detail_forms" in sql
    assert "token_digest text not null unique" in sql
    assert "customer_id uuid not null references public.customers" in sql
    assert "conversation_id uuid not null references public.conversations" in sql
    assert "expires_at timestamptz not null" in sql and "enable row level security" in sql
    assert "whatsapp_number" not in sql and "drop table" not in sql


def test_native_flow_definition_contains_only_required_name_and_email_fields():
    import json
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    form = flow["screens"][0]["layout"]["children"][2]
    inputs = [item for item in form["children"] if item["type"] == "TextInput"]
    assert [(item["name"], item["required"]) for item in inputs] == [
        ("full_name", True), ("email", True),
    ]
    assert all("phone" not in item["name"] and "whatsapp" not in item["name"] for item in inputs)
    footer = form["children"][-1]
    assert footer["on-click-action"]["name"] == "complete"
    assert footer["on-click-action"]["payload"] == {
        "full_name": "${form.full_name}", "email": "${form.email}",
    }
