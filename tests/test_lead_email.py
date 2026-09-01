from datetime import date
from types import SimpleNamespace

from pydantic import SecretStr

from app.integrations import lead_email
from app.integrations.lead_email import SmtpLeadEmailNotifier, lead_email_from_context


class FakeSmtp:
    instances = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.login_values = None
        self.message = None
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def starttls(self, **_kwargs):
        self.started_tls = True

    def login(self, username, password):
        self.login_values = (username, password)

    def send_message(self, message):
        self.message = message


def test_professional_coimbatore_lead_email_contains_required_fields(monkeypatch):
    FakeSmtp.instances.clear()
    monkeypatch.setattr(lead_email.smtplib, "SMTP", FakeSmtp)
    settings = SimpleNamespace(
        lead_email_notifications_enabled=True,
        lead_email_to="hasim@echt.co.in",
        smtp_host="smtp.example.test", smtp_port=587,
        smtp_username="chatbot@example.test", smtp_password=SecretStr("secret"),
        smtp_from_email="chatbot@example.test", smtp_use_tls=True,
        smtp_use_ssl=False, smtp_timeout_seconds=10,
    )
    context = SimpleNamespace(
        details=SimpleNamespace(
            customer_name="Mandip", total_guests=7,
            preferred_date=date(2026, 12, 31),
        ),
        form_values={"customer_email": "mandip@example.com"},
    )
    lead = lead_email_from_context(
        "coimbatore_pontoon_book_standard",
        {"name": "Mandip", "email": "mandip@example.com", "whatsapp_number": "+919876543210"},
        context,
    )

    assert lead is not None
    assert SmtpLeadEmailNotifier(settings).send(lead) is True

    sent = FakeSmtp.instances[0]
    assert sent.started_tls is True
    assert sent.login_values == ("chatbot@example.test", "secret")
    assert sent.message["To"] == "hasim@echt.co.in"
    assert "Book Now" in sent.message["Subject"]
    body = sent.message.get_body(preferencelist=("plain",)).get_content()
    assert all(value in body for value in (
        "Entartica Coimbatore", "Pontoon Celebration", "Mandip",
        "mandip@example.com", "+919876543210", "7", "31 Dec 2026",
    ))


def test_only_three_approved_actions_create_lead_email():
    context = SimpleNamespace(details=SimpleNamespace(
        customer_name="Guest", total_guests=2, preferred_date=None,
    ), form_values={})
    customer = {"whatsapp_number": "+919876543210"}
    for action in (
        "coimbatore_pontoon_book_standard",
        "coimbatore_pontoon_customize",
        "coimbatore_pontoon_talk_sales",
    ):
        assert lead_email_from_context(action, customer, context) is not None
    for action in ("coimbatore_pontoon_more_photos", "coimbatore_pontoon_brochure"):
        assert lead_email_from_context(action, customer, context) is None
