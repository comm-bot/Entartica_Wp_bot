"""Configuration-gated SMTP notifications for qualified Coimbatore leads."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
import smtplib
import ssl
from typing import Any


class LeadEmailConfigurationError(RuntimeError):
    """Raised before network I/O when SMTP configuration is incomplete."""


@dataclass(frozen=True)
class LeadEmail:
    action: str
    lead_name: str
    lead_email: str
    lead_phone: str
    guest_count: str
    event_date: str


_ACTION_LABELS = {
    "coimbatore_pontoon_book_standard": "Book Now",
    "coimbatore_pontoon_customize": "Customize Package",
    "coimbatore_pontoon_talk_sales": "Talk to Sales Person",
}


def lead_email_from_context(action: str, customer: dict[str, Any], context: Any) -> LeadEmail | None:
    label = _ACTION_LABELS.get(action)
    if label is None:
        return None
    details = getattr(context, "details", None)
    values = getattr(context, "form_values", None) or {}
    planned = getattr(details, "preferred_date", None)
    return LeadEmail(
        action=label,
        lead_name=str(
            (customer.get("name") if isinstance(customer, dict) else None)
            or getattr(details, "customer_name", None)
            or "Not provided"
        ),
        lead_email=str(
            (customer.get("email") if isinstance(customer, dict) else None)
            or values.get("customer_email")
            or "Not provided"
        ),
        lead_phone=str(
            (customer.get("whatsapp_number") if isinstance(customer, dict) else None)
            or values.get("payment_customer_mobile")
            or "Not provided"
        ),
        guest_count=str(getattr(details, "total_guests", None) or "Not provided"),
        event_date=planned.strftime("%d %b %Y") if planned is not None else "Not provided",
    )


class SmtpLeadEmailNotifier:
    def __init__(self, settings: Any) -> None:
        self._enabled = bool(getattr(settings, "lead_email_notifications_enabled", False))
        self._to = str(getattr(settings, "lead_email_to", "hasim@echt.co.in") or "").strip()
        self._host = str(getattr(settings, "smtp_host", "") or "").strip()
        self._port = int(getattr(settings, "smtp_port", 587))
        self._username = str(getattr(settings, "smtp_username", "") or "").strip()
        password = getattr(settings, "smtp_password", None)
        self._password = password.get_secret_value() if password is not None else ""
        self._from = str(getattr(settings, "smtp_from_email", "") or "").strip()
        self._use_tls = bool(getattr(settings, "smtp_use_tls", True))
        self._use_ssl = bool(getattr(settings, "smtp_use_ssl", False))
        self._timeout = float(getattr(settings, "smtp_timeout_seconds", 10.0))

    def send(self, lead: LeadEmail) -> bool:
        if not self._enabled:
            return False
        if not all((self._to, self._host, self._username, self._password, self._from)):
            raise LeadEmailConfigurationError("lead_email_smtp_configuration_missing")
        message = EmailMessage()
        safe_name = " ".join(lead.lead_name.replace("\r", " ").replace("\n", " ").split())
        message["Subject"] = f"New Coimbatore Pontoon Celebration Lead — {lead.action} — {safe_name}"
        message["From"] = self._from
        message["To"] = self._to
        rows = (
            ("Lead action", lead.action),
            ("Location", "Entartica Coimbatore"),
            ("Service", "Pontoon Celebration"),
            ("Lead name", lead.lead_name),
            ("Lead email", lead.lead_email),
            ("WhatsApp number", lead.lead_phone),
            ("Number of guests", lead.guest_count),
            ("Celebration date", lead.event_date),
        )
        message.set_content(
            "New lead received from the Entartica WhatsApp chatbot.\n\n"
            + "\n".join(f"{label}: {value}" for label, value in rows)
            + "\n\nPlease contact the customer and continue the enquiry."
        )
        html_rows = "".join(
            f"<tr><th style='text-align:left;padding:6px'>{escape(label)}</th>"
            f"<td style='padding:6px'>{escape(value)}</td></tr>"
            for label, value in rows
        )
        message.add_alternative(
            "<p>A new lead was received from the Entartica WhatsApp chatbot.</p>"
            f"<table style='border-collapse:collapse'>{html_rows}</table>"
            "<p>Please contact the customer and continue the enquiry.</p>",
            subtype="html",
        )
        smtp_class = smtplib.SMTP_SSL if self._use_ssl else smtplib.SMTP
        with smtp_class(self._host, self._port, timeout=self._timeout) as client:
            if self._use_tls and not self._use_ssl:
                client.starttls(context=ssl.create_default_context())
            client.login(self._username, self._password)
            client.send_message(message)
        return True
