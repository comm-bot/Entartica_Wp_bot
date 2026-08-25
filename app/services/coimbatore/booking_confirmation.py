"""Deterministic PDF confirmation generation, storage, and delivery orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from io import BytesIO
from html import escape
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.repositories.bookings import BookingRepository
from app.repositories.payments import PaymentRepository
from app.services.coimbatore.pontoon_package import (
    COUPLE_PACKAGE_ID, STANDARD_PACKAGE_ID, resolve_standard_package_pricing,
)


class ConfirmationStorage(Protocol):
    def store(self, key: str, content: bytes) -> str: ...
    def url_for(self, key: str) -> str: ...


class ConfirmationDelivery(Protocol):
    def send(self, *, booking: dict[str, Any], payment: dict[str, Any], pdf_url: str,
             filename: str, caption: str) -> bool: ...


@dataclass(frozen=True)
class ConfirmationResult:
    completed: bool
    reused_pdf: bool
    storage_key: str | None
    reason: str


def _money(paise: int) -> str:
    return f"₹{paise // 100:,}/-"


def _display_date(value: object) -> str:
    try:
        return date.fromisoformat(str(value)).strftime("%d %b %Y")
    except ValueError:
        return str(value or "Not provided")


def _display_time(value: object) -> str:
    if not value:
        return "Not provided"
    try:
        return time.fromisoformat(str(value)).strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return str(value)


def _display_datetime(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")
    except ValueError:
        return str(value or "Not provided")


def _package_truth(booking: dict[str, Any]) -> tuple[str, int, int]:
    package_id, guests = booking.get("package_id"), booking.get("guest_count")
    if package_id == STANDARD_PACKAGE_ID:
        pricing = resolve_standard_package_pricing(guests)
        if pricing is None:
            raise ValueError("confirmation_pricing_unavailable")
        return "Pontoon Boat Celebration - Standard Package", pricing.regular_price, pricing.offer_price
    if package_id == COUPLE_PACKAGE_ID and guests == 2:
        return "Pontoon Couple Romance Celebration", 3999, 3400
    raise ValueError("confirmation_package_unsupported")


def generate_confirmation_pdf(booking: dict[str, Any], payment: dict[str, Any], *,
                              razorpay_mode: str, generated_at: datetime | None = None,
                              font_path: str | None = None) -> bytes:
    package_name, regular, offer = _package_truth(booking)
    paid_paise = payment.get("amount_paise")
    if (booking.get("status") not in {"payment_received", "confirmation_generating", "confirmation_failed", "confirmed"}
            or payment.get("status") != "paid" or payment.get("currency") != "INR"
            or paid_paise != booking.get("amount_paise") or paid_paise != offer * 100
            or not payment.get("provider_payment_id")):
        raise ValueError("confirmation_payment_not_verified")
    generated = generated_at or datetime.now(UTC)
    font_name = "Helvetica"
    candidate = Path(font_path) if font_path else Path("C:/Windows/Fonts/arial.ttf")
    if candidate.is_file():
        font_name = "EntarticaUnicode"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(candidate)))
    currency = "₹" if font_name == "EntarticaUnicode" else "INR "
    money = lambda rupees: f"{currency}{rupees:,}/-"
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Title"], fontName=font_name,
                           fontSize=20, leading=23, textColor=colors.HexColor("#0B6655"), alignment=TA_CENTER)
    heading = ParagraphStyle("Heading", parent=styles["Heading2"], fontName=font_name,
                             fontSize=10, leading=12, textColor=colors.white, spaceBefore=4,
                             spaceAfter=0, backColor=colors.HexColor("#0B6655"),
                             borderPadding=(4, 6, 4, 6))
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName=font_name, fontSize=8.4, leading=10.5)
    terms_heading = ParagraphStyle("TermsHeading", parent=styles["Heading2"], fontName=font_name,
                                   fontSize=9.5, leading=11.5, textColor=colors.HexColor("#0B6655"),
                                   spaceBefore=5, spaceAfter=2)
    terms_body = ParagraphStyle("TermsBody", parent=body, fontSize=8, leading=10.2,
                                leftIndent=4*mm, firstLineIndent=-3*mm, spaceAfter=1.5)
    warning = ParagraphStyle("Warning", parent=body, fontSize=12, leading=16, alignment=TA_CENTER,
                             textColor=colors.HexColor("#A32920"), backColor=colors.HexColor("#FFF0ED"),
                             borderColor=colors.HexColor("#E7A39C"), borderWidth=1, borderPadding=8)
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm,
                            topMargin=12*mm, bottomMargin=12*mm,
                            title=f"Booking Confirmation {booking['booking_ref']}", author="Entartica Coimbatore")
    story: list[Any] = [Paragraph("ENTARTICA SEA WORLD", title), Spacer(1, 1*mm),
                        Paragraph("BOOKING CONFIRMATION", ParagraphStyle("Sub", parent=title, fontSize=13, leading=15))]
    if razorpay_mode == "test":
        story += [Spacer(1, 2*mm), Paragraph("TEST MODE - NOT A LIVE BOOKING", warning)]
    story += [Spacer(1, 2*mm)]

    def section(label: str, rows: list[tuple[str, str]]) -> None:
        story.append(Paragraph(label, heading))
        table = Table([[Paragraph(f"<b>{escape(key)}</b>", body), Paragraph(escape(value), body)] for key, value in rows],
                      colWidths=[48*mm, 130*mm], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#EAF4F1")),
            ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#B7D3CC")),
            ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 3.5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3.5),
        ]))
        story.append(table)

    section("BOOKING SUMMARY", [("Booking ID", str(booking["booking_ref"])),
        ("Booking Date", generated.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")),
        ("Booking Consultant", str(booking.get("booking_consultant") or "Entartica Team")),
        ("Customer Name", str(booking.get("customer_name") or "Not provided")),
        ("Contact Number", str(booking.get("customer_mobile") or "Not provided")),
        ("Location", "Coimbatore"), ("Event", "Pontoon Celebration"),
        ("Event Date", _display_date(booking.get("event_date"))),
        ("Event Time", _display_time(booking.get("preferred_time"))),
        ("Duration", str(booking.get("duration") or "30 Min")),
        ("Guests", f"{booking.get('guest_count')} guests")])
    inclusions = booking.get("inclusions") or (
        "2 Cold Pyro Entry; Royal Red Carpet Welcome; Cake; Music Setup; Decoration; "
        "Cake cutting in the middle of the serene lake; 30 Minutes Premium Boat Ride"
    )
    section("INCLUSIONS & ADD-ONS", [("Inclusions", str(inclusions)),
        ("Customized Cake", str(booking.get("customized_cake") or "NA")),
        ("Customised Decor", str(booking.get("customised_decor") or "NA")),
        ("Rides", str(booking.get("rides") or "NA")),
        ("Special Note", str(booking.get("special_note") or "NA"))])
    section("PAYMENT SUMMARY", [("Package Amount", money(regular)),
        ("Discount", money(regular - offer)), ("Total Amount", money(offer)),
        ("Advance Received", money(int(paid_paise)//100)),
        ("Remaining Amount", money(max(0, offer - int(paid_paise)//100))),
        ("Payment Mode", str(payment.get("payment_mode") or "Online")),
        ("Transaction ID", str(payment["provider_payment_id"])),
        ("Payment Date", _display_datetime(payment.get("paid_at")))])
    section("SITE COORDINATOR", [("Name", str(booking.get("site_coordinator_name") or "Entartica Coimbatore Team")),
        ("Contact Number", str(booking.get("site_coordinator_phone") or "+91 94296 91418"))])
    section("LOCATION INFORMATION", [("Venue", "Entartica Sea World - Coimbatore"),
        ("Address", "Periyakulam Lake Boat House, Ukkadam, Coimbatore, Tamil Nadu - 641001"),
        ("Operating Hours", "10 AM - 11 PM")])
    story += [Spacer(1, 3*mm), Paragraph("Thank You!", ParagraphStyle(
        "Thanks", parent=title, fontSize=13, leading=15)), Paragraph(
        f"Dear {escape(str(booking.get('customer_name') or 'Guest'))},<br/>Thank you for choosing Entartica Sea World. "
        "We are delighted to be part of your celebration and look forward to creating wonderful memories with you.",
        ParagraphStyle("Closing", parent=body, alignment=TA_CENTER, fontSize=8.8, leading=11,
                       textColor=colors.HexColor("#274A43"))), PageBreak()]

    terms: list[tuple[str, list[str]]] = [
        ("1. Booking Confirmation", ["Bookings are confirmed only after receipt of the required advance payment.",
         "All bookings are subject to availability of the selected venue, boat, crew and time slot.",
         "The booking confirmation shared through Email, WhatsApp or SMS shall be considered the official confirmation.",
         "Remaining payment must be completed before commencement of the event."]),
        ("2. Cancellation, Rescheduling & Refund", ["Confirmed bookings are generally non-refundable.",
         "Rescheduling requests are subject to availability.", "Price revisions may apply when changing the booking date.",
         "No refund shall be provided for late arrival or no-show.",
         "Bookings are non-transferable without prior approval from management."]),
        ("3. Weather & Operational Conditions", ["Boat operations are dependent on weather conditions, water level and government permissions.",
         "Management reserves the right to delay, postpone or cancel any activity for safety reasons.",
         "Safety decisions taken by the operations team shall be final."]),
        ("4. Reporting Time", ["Guests should arrive at least 15-30 minutes before the scheduled time.",
         "Late reporting may reduce the overall cruising duration.",
         "No extension will be granted due to late arrival unless operationally feasible."]),
        ("5. Guest Safety", ["Guests must follow all safety instructions issued by the crew.",
         "Life jackets must be worn whenever instructed.", "Children must always remain under adult supervision.",
         "Management reserves the right to deny boarding in unsafe situations."]),
        ("6. Conduct & Damages", ["Misconduct, abusive behaviour or unsafe activities are strictly prohibited.",
         "Damage caused to boats, decorations, sound systems or any property shall be chargeable to the customer.",
         "Littering in rivers, lakes or surrounding premises is prohibited."]),
        ("7. Alcohol & Prohibited Items", ["Alcohol, narcotics and illegal substances are prohibited unless specifically permitted by local authorities.",
         "Guests found under the influence may be refused entry without refund.", "Smoking shall only be permitted where authorised."]),
        ("8. Decorations & Add-ons", ["Decoration themes, cakes, flowers and balloons are subject to availability.",
         "Actual decoration colours and materials may vary slightly from reference photographs.",
         "Outside decorators or vendors require prior written approval."]),
        ("9. Food & Beverage", ["Published food pricing applies to vegetarian menus unless otherwise specified.",
         "Outside food and beverages are not permitted unless approved by management.",
         "Food service timings shall follow operational schedules."]),
        ("10. Capacity & Entry", ["Maximum passenger capacity shall strictly follow statutory safety limits.",
         "Additional guests beyond the confirmed booking shall not be accommodated.", "Pets are not permitted unless expressly allowed.",
         "Management reserves the right of admission."]),
        ("11. Photography & Media", ["Photographs and videos captured during the event may be used for promotional purposes.",
         "Guests may notify management in advance if they do not wish to appear in promotional material."]),
        ("12. Liability", ["Entartica Sea World shall not be responsible for loss of personal belongings.",
         "Management shall not be liable for injuries resulting from negligence or non-compliance with safety instructions.",
         "Participation in all activities is entirely at the guest's own risk."]),
        ("13. Force Majeure", ["Management shall not be liable for cancellations caused by natural disasters, government restrictions, technical failures or other events beyond reasonable control."]),
        ("14. Jurisdiction", ["All disputes shall be subject to the jurisdiction of the city where the respective Entartica Sea World location operates.",
         "By confirming the booking, the customer acknowledges and accepts these Terms & Conditions."]),
    ]

    def add_terms(items: list[tuple[str, list[str]]]) -> None:
        story.append(Paragraph("TERMS & CONDITIONS", ParagraphStyle("TermsTitle", parent=title, fontSize=15, leading=18)))
        for label, clauses in items:
            story.append(Paragraph(label, terms_heading))
            for index, clause in enumerate(clauses, 1):
                story.append(Paragraph(f"{index}. {escape(clause)}", terms_body))

    add_terms(terms[:6])
    story.append(PageBreak())
    add_terms(terms[6:])
    story += [Paragraph("Important", terms_heading),
        Paragraph("• Please arrive at least 15-30 minutes before your scheduled reporting time.<br/>"
                  "• Remaining payment (if applicable) must be completed before boarding.<br/>"
                  "• Schedules may change due to weather, safety or operational reasons.<br/>"
                  "• Guests must follow all safety instructions from the operations team.", terms_body),
        Paragraph("Customer Support", terms_heading),
        Paragraph("+91 94296 91418 | info@entartica.com | www.entartica.com", body),
        Spacer(1, 3*mm), Paragraph("Entartica Sea World<br/>This is a computer generated Booking Confirmation. No signature required.",
                                  ParagraphStyle("Footer", parent=body, alignment=TA_CENTER, textColor=colors.HexColor("#526B66")))]
    doc.build(story)
    return output.getvalue()


class S3ConfirmationStorage:
    def __init__(self, settings: Any) -> None:
        import boto3
        access, secret = settings.aws_access_key_id, settings.aws_secret_access_key
        if access is None or secret is None:
            raise RuntimeError("confirmation_s3_credentials_missing")
        kwargs = {"aws_access_key_id":access.get_secret_value(), "aws_secret_access_key":secret.get_secret_value(),
                  "region_name":settings.aws_region}
        if settings.aws_session_token is not None:
            kwargs["aws_session_token"] = settings.aws_session_token.get_secret_value()
        self._client = boto3.client("s3", **kwargs)
        self._bucket, self._expiry = settings.coimbatore_confirmation_s3_bucket, settings.s3_presigned_url_expiry_seconds

    def store(self, key: str, content: bytes) -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=content,
                                ContentType="application/pdf", ServerSideEncryption="AES256")
        return self.url_for(key)

    def url_for(self, key: str) -> str:
        return self._client.generate_presigned_url("get_object", Params={"Bucket":self._bucket, "Key":key},
                                                   ExpiresIn=int(self._expiry))


class BookingConfirmationService:
    def __init__(self, database: Any, storage: ConfirmationStorage, delivery: ConfirmationDelivery,
                 *, razorpay_mode: str = "test", storage_prefix: str = "booking-confirmations",
                 font_path: str | None = None) -> None:
        self._bookings, self._payments = BookingRepository(database), PaymentRepository(database)
        self._storage, self._delivery, self._mode = storage, delivery, razorpay_mode
        self._prefix, self._font_path = storage_prefix.strip("/"), font_path

    def ensure_confirmation(self, booking_id: str) -> ConfirmationResult:
        booking = self._bookings.get_booking_by_id(booking_id)
        payment = self._payments.get_latest_payment_for_booking(booking_id)
        if not booking or not payment or payment.get("status") != "paid" or booking.get("status") not in {
            "payment_received", "confirmation_generating", "confirmation_failed", "confirmed"}:
            return ConfirmationResult(False, False, None, "verified_payment_required")
        if booking.get("status") == "confirmed":
            return ConfirmationResult(True, True, booking.get("confirmation_pdf_storage_key"), "already_confirmed")
        self._bookings.update_booking(booking_id, {"status":"confirmation_generating"})
        key = booking.get("confirmation_pdf_storage_key")
        reused = isinstance(key, str) and bool(key.strip())
        try:
            if reused:
                url = self._storage.url_for(key)
                booking = self._bookings.update_booking(
                    booking_id, {"confirmation_pdf_url": url}
                ) or booking
            else:
                _package_truth(booking)
                pdf = generate_confirmation_pdf(booking, payment, razorpay_mode=self._mode, font_path=self._font_path)
                key = f"{self._prefix}/{booking['booking_ref']}.pdf"
                url = self._storage.store(key, pdf)
                booking = self._bookings.update_booking(booking_id, {
                    "confirmation_pdf_storage_key":key, "confirmation_pdf_url":url,
                }) or booking
            amount = _money(int(payment["amount_paise"]))
            caption = ("✅ Test Payment Successful\n\nYour booking confirmation has been generated successfully.\n\n"
                f"Booking Reference: {booking['booking_ref']}\nAmount Paid: {amount}\n\n"
                "📄 Your Booking Confirmation is attached below.\n\n"
                "⚠️ TEST MODE - This is not a live booking.") if self._mode == "test" else (
                f"✅ Booking Confirmed!\n\nBooking Reference: {booking['booking_ref']}\nAmount Paid: {amount}")
            sent = self._delivery.send(booking=booking, payment=payment, pdf_url=url,
                                       filename=f"Entartica-{booking['booking_ref']}.pdf", caption=caption)
            if not sent:
                self._bookings.update_booking(booking_id, {"status":"confirmation_failed",
                    "confirmation_pdf_storage_key":key, "confirmation_pdf_url":url})
                return ConfirmationResult(False, reused, key, "whatsapp_delivery_failed")
            self._bookings.update_booking(booking_id, {"status":"confirmed",
                "confirmation_pdf_storage_key":key, "confirmation_pdf_url":url,
                "confirmed_at":datetime.now(UTC).isoformat()})
            return ConfirmationResult(True, reused, key, "confirmed")
        except Exception:
            self._bookings.update_booking(booking_id, {"status":"confirmation_failed"})
            return ConfirmationResult(False, reused, key if isinstance(key, str) else None, "confirmation_failed")
