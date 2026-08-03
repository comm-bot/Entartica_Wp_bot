"""Configured, customer-safe Entartica sales-contact presentation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SalesContact:
    phone: str
    email: str

    @classmethod
    def from_settings(cls, settings: Any) -> "SalesContact":
        # Use the typed Settings defaults for legacy narrow test/config objects;
        # the approved values remain defined once in application configuration.
        from app.config import Settings

        phone = getattr(settings, "entartica_sales_phone", Settings.model_fields["entartica_sales_phone"].default)
        email = getattr(settings, "entartica_sales_email", Settings.model_fields["entartica_sales_email"].default)
        if not isinstance(phone, str) or not isinstance(email, str) or not phone.strip() or not email.strip():
            raise ValueError("sales_contact_configuration_invalid")
        return cls(phone=phone.strip(), email=email.strip())

    @property
    def display_phone(self) -> str:
        digits = "".join(character for character in self.phone if character.isdigit())
        if len(digits) == 12 and digits.startswith("91"):
            return f"+91 {digits[2:7]} {digits[7:]}"
        return self.phone

    def details(self) -> str:
        return f"📞 Call: {self.display_phone}\n✉️ Email: {self.email}"


def approved_safe_fallback(contact: SalesContact, language: str) -> str:
    if language == "hinglish":
        return (
            "Maaf kijiye, mere paas is query ka confirmed answer available nahi hai. "
            "Aap Entartica sales team se directly contact kar sakte hain:\n\n"
            f"{contact.details()}\n\n"
            "Entartica sales team aapki assistance karegi."
        )
    return (
        "I don’t have enough confirmed information to answer this accurately. "
        "Please contact the Entartica sales team for assistance:\n\n"
        f"{contact.details()}\n\n"
        "The Entartica sales team will assist you."
    )


def controlled_sales_handover(contact: SalesContact, language: str) -> str:
    if language == "hinglish":
        lead = "Current pricing, availability aur final booking confirmation Entartica sales team handle karti hai."
        tail = "Entartica sales team aapki assistance karegi."
    else:
        lead = "Current pricing, availability and final booking confirmation are handled by the Entartica sales team."
        tail = "The Entartica sales team will assist you."
    return f"{lead}\n\n{contact.details()}\n\n{tail}"


def booking_sales_handover(contact: SalesContact, language: str, service_name: str | None = None) -> str:
    """Provide the approved contact route without collecting booking details."""

    service = f"For {service_name} booking assistance" if service_name else "For booking assistance"
    if language == "hinglish":
        service = f"{service_name} booking assistance ke liye" if service_name else "Booking assistance ke liye"
    return f"{service}, please contact the Entartica sales team directly:\n\n{contact.details()}"


def direct_human_handover(contact: SalesContact, language: str) -> str:
    if language == "hinglish":
        return (
            f"Entartica sales team se contact karne ke liye:\n\n{contact.details()}\n\n"
            "Entartica sales team aapki assistance karegi."
        )
    return (
        f"You can contact the Entartica sales team here:\n\n{contact.details()}\n\n"
        "The Entartica sales team will assist you."
    )
