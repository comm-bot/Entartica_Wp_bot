"""Generate the deterministic test-mode booking confirmation used for visual QA."""
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.services.coimbatore.booking_confirmation import generate_confirmation_pdf

output = Path(__file__).parents[1] / "output" / "pdf" / "booking_confirmation_test_sample.pdf"
output.parent.mkdir(parents=True, exist_ok=True)
booking = {
    "booking_ref":"CBE-PTN-A82K5M", "status":"payment_received",
    "package_id":"coimbatore_pontoon_standard", "event_date":"2026-08-30",
    "preferred_time":"18:00:00", "guest_count":8, "customer_name":"Mandip Singh",
    "customer_mobile":"+91 99999 99999", "customer_email":"mandip@example.com",
    "amount_paise":637500,
}
payment = {"status":"paid", "currency":"INR", "amount_paise":637500,
           "provider_payment_id":"pay_test_A82K5M", "paid_at":"2026-08-22T14:30:00+00:00"}
output.write_bytes(generate_confirmation_pdf(
    booking, payment, razorpay_mode="test", generated_at=datetime(2026, 8, 22, 14, 31, tzinfo=UTC),
    font_path="C:/Windows/Fonts/arial.ttf",
))
print(output)
