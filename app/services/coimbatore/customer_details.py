"""Secure pre-chat customer-details collection for Coimbatore only."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import re
import secrets
from typing import Any
from urllib.parse import urlparse

from app.repositories.conversations import ConversationRepository
from app.repositories.customer_detail_forms import CustomerDetailFormRepository
from app.repositories.customers import CustomerRepository


_EMAIL = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$", re.I)


@dataclass(frozen=True)
class IssuedDetailsForm:
    token: str
    url: str


@dataclass(frozen=True)
class DetailsSubmission:
    accepted: bool
    reason: str
    customer: dict[str, Any] | None = None
    conversation_id: str | None = None
    form_id: str | None = None
    duplicate: bool = False


def customer_details_complete(customer: dict[str, Any]) -> bool:
    return bool(str(customer.get("name") or "").strip() and str(customer.get("email") or "").strip())


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _valid_public_base_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value.strip())
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (parsed.scheme != "https" and not local_http) or not parsed.netloc or parsed.username or parsed.password:
        return None
    return value.strip().rstrip("/")


def validate_details(name: object, email: object) -> tuple[str | None, str | None, str | None]:
    clean_name = " ".join(str(name or "").split())
    clean_email = str(email or "").strip().casefold()
    if not clean_name or len(clean_name) > 120:
        return None, None, "invalid_name"
    if len(clean_email) > 254 or not _EMAIL.fullmatch(clean_email):
        return None, None, "invalid_email"
    local = clean_email.partition("@")[0]
    if local.startswith(".") or local.endswith(".") or ".." in clean_email:
        return None, None, "invalid_email"
    return clean_name, clean_email, None


class CustomerDetailsFormService:
    def __init__(self, client: Any, *, public_base_url: str | None, ttl_minutes: int = 30) -> None:
        self._forms = CustomerDetailFormRepository(client)
        self._customers = CustomerRepository(client)
        self._conversations = ConversationRepository(client)
        self._base_url = _valid_public_base_url(public_base_url)
        self._ttl_minutes = max(5, min(int(ttl_minutes), 1440))

    def issue(self, *, customer_id: str, conversation_id: str) -> IssuedDetailsForm:
        if self._base_url is None:
            raise RuntimeError("customer_details_public_url_missing")
        if not self._conversations.belongs_to_customer(conversation_id, customer_id):
            raise ValueError("customer_details_conversation_mismatch")
        token = secrets.token_urlsafe(32)
        self._forms.create(customer_id=customer_id, conversation_id=conversation_id,
                           token_digest=_digest(token), ttl_minutes=self._ttl_minutes)
        return IssuedDetailsForm(token, f"{self._base_url}/coimbatore/details/{token}")

    def issue_native_token(self, *, customer_id: str, conversation_id: str) -> str:
        if not self._conversations.belongs_to_customer(conversation_id, customer_id):
            raise ValueError("customer_details_conversation_mismatch")
        token = secrets.token_urlsafe(32)
        self._forms.create(customer_id=customer_id, conversation_id=conversation_id,
                           token_digest=_digest(token), ttl_minutes=self._ttl_minutes)
        return token

    def submit_native(self, token: str, *, customer_id: str, conversation_id: str,
                      name: object, email: object) -> DetailsSubmission:
        form, reason = self.resolve(token)
        if form is None:
            return DetailsSubmission(False, reason)
        if form.get("customer_id") != customer_id or form.get("conversation_id") != conversation_id:
            return DetailsSubmission(False, "identity_mismatch")
        return self.submit(token, name=name, email=email)

    def resolve(self, token: str) -> tuple[dict[str, Any] | None, str]:
        if not isinstance(token, str) or not 32 <= len(token) <= 200:
            return None, "invalid_token"
        row = self._forms.get_by_digest(_digest(token))
        if row is None:
            return None, "invalid_token"
        try:
            expires = datetime.fromisoformat(str(row.get("expires_at", "")).replace("Z", "+00:00"))
        except ValueError:
            return None, "invalid_token"
        if expires.tzinfo is None or expires.astimezone(UTC) <= datetime.now(UTC):
            return None, "expired_token"
        return row, "ok"

    def submit(self, token: str, *, name: object, email: object) -> DetailsSubmission:
        clean_name, clean_email, validation_error = validate_details(name, email)
        if validation_error:
            return DetailsSubmission(False, validation_error)
        form, reason = self.resolve(token)
        if form is None:
            return DetailsSubmission(False, reason)
        customer_id, conversation_id = form.get("customer_id"), form.get("conversation_id")
        if not isinstance(customer_id, str) or not isinstance(conversation_id, str):
            return DetailsSubmission(False, "invalid_token")
        if form.get("status") == "completed":
            customer = self._customers.get_by_id(customer_id)
            return DetailsSubmission(True, "already_completed", customer, conversation_id,
                                     str(form.get("id")), True)
        if form.get("status") != "pending":
            return DetailsSubmission(False, "invalid_token")
        customer = self._customers.update_details(customer_id, name=clean_name or "", email=clean_email or "")
        if customer is None:
            return DetailsSubmission(False, "persistence_failed")
        context = self._conversations.get_service_context(conversation_id, customer_id) or {}
        details = dict(context.get("booking_details") or {})
        details["customer_name"] = clean_name
        values = dict(context.get("form_values") or {})
        values.update({"customer_email": clean_email, "customer_details_complete": True})
        context.update({
            "selected_location": "coimbatore", "location_code": "coimbatore",
            "service_code": "pontoon_celebration", "service_name": "Pontoon Boat Celebration",
            "active_journey": "pontoon_qualification", "active_form": "customer_details",
            "form_status": "completed", "form_values": values, "booking_details": details,
            "pending_field": "total_guests", "updated_at": datetime.now(UTC).isoformat(),
        })
        if not self._conversations.save_service_context(conversation_id, customer_id, context):
            return DetailsSubmission(False, "persistence_failed")
        if not self._forms.complete(str(form["id"])):
            refreshed, _ = self.resolve(token)
            if not refreshed or refreshed.get("status") != "completed":
                return DetailsSubmission(False, "persistence_failed")
        return DetailsSubmission(True, "completed", customer, conversation_id, str(form["id"]))
