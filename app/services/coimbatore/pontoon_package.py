"""Approved Coimbatore package loading, rendering, and action routing."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, time
from functools import lru_cache
import json
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from app.schemas.interactive_messages import InteractiveMessage, InteractiveOption
from app.services.raipur.response_models import ConversationContext, ConversationResult
from app.services.raipur.sales_state import SalesStage

logger = logging.getLogger("uvicorn.error")

ROOT = Path(__file__).resolve().parents[3]
CONFIG_FILE = ROOT / "config" / "Coimbatore" / "coimbatore_pontoon_standard.yaml"
MASTER_KB = ROOT / "documents" / "coimbatore" / "active" / "COIMBATORE_KNOWLEDGE_BASE.md"
STANDARD_PACKAGE_ID = "coimbatore_pontoon_standard"
COUPLE_PACKAGE_ID = "coimbatore_pontoon_couple_romance"
STANDARD_PACKAGE_IMAGE_URL = (
    "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/"
    "pontoon_boat_celebration_Coimbtore.jpg"
)
STANDARD_PACKAGE_BROCHURE_URL = (
    "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/"
    "Pontoon_Celebration_Brochure.pdf"
)

@dataclass(frozen=True)
class StandardPackage:
    package_id: str
    title: str
    inclusions: tuple[str, ...]
    rack_rate: str
    offer_rate: str
    token_amount: str
    offer_note: str
    booking_wording: str
    refund_rule: str
    add_ons: tuple[str, ...]
    media_asset: str
    actions: tuple[InteractiveOption, ...]
    message_template: str = ""
    fixed_guest_count: int | None = None


@dataclass(frozen=True)
class StandardPackagePricing:
    slab_id: str
    min_guests: int
    max_guests: int
    regular_price: int
    offer_price: int

    @property
    def offer_price_paise(self) -> int:
        return self.offer_price * 100


@lru_cache(maxsize=1)
def _standard_pricing_slabs() -> tuple[StandardPackagePricing, ...]:
    rows = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("pricing")
    if not isinstance(rows, list):
        raise ValueError("standard_package_pricing_missing")
    slabs = tuple(StandardPackagePricing(
        slab_id=str(row["slab_id"]), min_guests=int(row["min_guests"]),
        max_guests=int(row["max_guests"]), regular_price=int(row["regular_price"]),
        offer_price=int(row["offer_price"]),
    ) for row in rows)
    expected = (("up_to_6", 1, 6, 5999, 5100), ("up_to_9", 7, 9, 7500, 6375),
                ("up_to_12", 10, 12, 9000, 7650))
    if tuple((s.slab_id, s.min_guests, s.max_guests, s.regular_price, s.offer_price) for s in slabs) != expected:
        raise ValueError("invalid_standard_package_pricing")
    return slabs


def resolve_standard_package_pricing(guest_count: int | None) -> StandardPackagePricing | None:
    """Resolve an approved price without arithmetic, defaults, or LLM input."""
    if not isinstance(guest_count, int) or isinstance(guest_count, bool) or guest_count <= 0:
        return None
    return next((slab for slab in _standard_pricing_slabs()
                 if slab.min_guests <= guest_count <= slab.max_guests), None)


@lru_cache(maxsize=4)
def _presentation_block(heading: str) -> tuple[str, str, str]:
    text = MASTER_KB.read_text(encoding="utf-8")
    match = re.search(rf"^# {re.escape(heading)}\s*$\n(.*?)(?=^# ACTIVE |^---\s*$)", text, re.M | re.S)
    if match is None:
        raise ValueError("active_package_presentation_missing")
    block = match.group(1)
    identity = dict(re.findall(r"^(package_id|status|customer_facing|presentation_mode):\s*(.+)$", block, re.M))
    if identity.get("status") != "ACTIVE" or identity.get("customer_facing") != "true" or identity.get("presentation_mode") != "exact":
        raise ValueError("invalid_active_package_presentation")
    message = re.search(r"^## CUSTOMER_PACKAGE_MESSAGE\s*$\n\n(.*?)(?=^## )", block, re.M | re.S)
    if message is None:
        raise ValueError("invalid_customer_package_block")
    return identity["package_id"].strip(), message.group(1).strip(), ""

@lru_cache(maxsize=1)
def load_standard_package() -> StandardPackage:
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if config.get("location") != "coimbatore" or config.get("product") != "pontoon_celebration" or config.get("active") is not True:
        raise ValueError("invalid_coimbatore_package_scope")
    if config.get("media_asset") != STANDARD_PACKAGE_IMAGE_URL:
        raise ValueError("invalid_standard_package_media_asset")
    if config.get("brochure_asset") != STANDARD_PACKAGE_BROCHURE_URL:
        raise ValueError("invalid_standard_package_brochure_asset")
    package_id, message, add_ons_text = _presentation_block("ACTIVE STANDARD PONTOON PACKAGE — CUSTOMER PRESENTATION")
    if package_id != config.get("package_id"): raise ValueError("invalid_standard_package_knowledge")
    inclusions_block = re.search(r"🎉 Inclusions:\n(.*?)(?=\n\n💰)", message, re.S)
    inclusions = tuple(re.findall(r"^• (.+)$", inclusions_block.group(1), re.M)) if inclusions_block else ()
    add_ons = tuple(re.findall(r"^• (.+)$", add_ons_text, re.M))
    if not inclusions or "{{regular_price}}" not in message or "{{offer_price}}" not in message:
        raise ValueError("invalid_standard_package_knowledge")
    actions = tuple(InteractiveOption(str(item["id"]), str(item["title"])) for item in config["actions"])
    if len(actions) != 6:
        raise ValueError("standard_package_requires_six_actions")
    return StandardPackage(package_id, message.splitlines()[0].removesuffix(" ✨"), inclusions,
                           "₹5,999", "₹5,100/- (15% OFF) including GST", "",
                           "Rates are valid for today.", "",
                           "Full refund if cancelled before 24 hours of the event date.", add_ons,
                           str(config["media_asset"]), actions, message, None)


@lru_cache(maxsize=1)
def load_couple_package() -> StandardPackage:
    package_id, message, add_ons_text = _presentation_block("ACTIVE COUPLE ROMANCE PONTOON PACKAGE — CUSTOMER PRESENTATION")
    if package_id != COUPLE_PACKAGE_ID: raise ValueError("invalid_couple_package_knowledge")
    inclusions_block = re.search(r"🎉 Inclusions:\n(.*?)(?=\n\n💰)", message, re.S)
    inclusions = tuple(re.findall(r"^• (.+)$", inclusions_block.group(1), re.M)) if inclusions_block else ()
    price = re.search(r"💰 Package Price: ~(₹[\d,]+/-)~", message)
    offer = re.search(r"😍 Offer Price: (₹[\d,]+/- \(15% off\) including GST)", message)
    if not inclusions or not price or not offer: raise ValueError("invalid_couple_package_knowledge")
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    actions = tuple(
        InteractiveOption(
            "coimbatore_pontoon_check_standard" if item["id"] == "coimbatore_pontoon_check_couple" else str(item["id"]),
            "Check Standard Package" if item["id"] == "coimbatore_pontoon_check_couple" else str(item["title"]),
        )
        for item in config["actions"]
        if item["id"] != "coimbatore_pontoon_brochure"
    )
    return StandardPackage(package_id, message.splitlines()[0].removesuffix(" ❤️✨"), inclusions,
                           price.group(1).removesuffix("/-").strip(), offer.group(1).strip(), "", "", "", "",
                           tuple(re.findall(r"^• (.+)$", add_ons_text, re.M)), "", actions, message, 2)


def load_package(package_id: str) -> StandardPackage:
    if package_id == STANDARD_PACKAGE_ID: return load_standard_package()
    if package_id == COUPLE_PACKAGE_ID: return load_couple_package()
    raise ValueError("unsupported_coimbatore_package")

def resolve_s3_image_url(uri: str, settings: Any) -> str | None:
    if isinstance(uri, str) and uri.startswith("https://"):
        return uri
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        return None
    access = getattr(settings, "aws_access_key_id", None)
    secret = getattr(settings, "aws_secret_access_key", None)
    if access is None or secret is None:
        return None
    try:
        import boto3
        kwargs = {"aws_access_key_id": access.get_secret_value(), "aws_secret_access_key": secret.get_secret_value(),
                  "region_name": getattr(settings, "aws_region", "ap-south-1")}
        token = getattr(settings, "aws_session_token", None)
        if token is not None: kwargs["aws_session_token"] = token.get_secret_value()
        return boto3.client("s3", **kwargs).generate_presigned_url(
            "get_object", Params={"Bucket": parsed.netloc, "Key": parsed.path.lstrip("/")},
            ExpiresIn=int(getattr(settings, "s3_presigned_url_expiry_seconds", 3600)),
        )
    except Exception:
        return None

def render_package(
    package: StandardPackage,
    event_date: date | None,
    guests: int | None,
    preferred_time: time | None = None,
    *,
    default_standard_pricing: bool = False,
) -> str:
    body = package.message_template
    date_line = f"📅 Event Date: {event_date.strftime('%d %b %Y')}" if event_date is not None else ""
    guest_value = package.fixed_guest_count if package.fixed_guest_count is not None else guests
    guest_line = f"👥 Guests: {guest_value}" if guest_value is not None else ""
    body = body.replace("📅 Event Date: {{event_date}}", date_line).replace("👥 Guests: {{guest_count}}", guest_line)
    if package.package_id == STANDARD_PACKAGE_ID:
        pricing = resolve_standard_package_pricing(guests)
        if pricing is None and default_standard_pricing:
            pricing = resolve_standard_package_pricing(1)
        regular = f"{pricing.regular_price:,}" if pricing is not None else ""
        offer = f"{pricing.offer_price:,}" if pricing is not None else ""
        body = body.replace("{{regular_price}}", regular).replace("{{offer_price}}", offer)
        if pricing is None:
            body = re.sub(r"\n?💰 Special Offer\n\n~₹/-~\n₹/- \(15% OFF\) including GST\n?", "\n", body)
    if preferred_time is not None:
        rendered_time = preferred_time.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
        anchor = date_line or body.splitlines()[0]
        body = body.replace(anchor, f"{anchor}\n🕐 Preferred Time: {rendered_time}", 1)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if package.package_id == STANDARD_PACKAGE_ID and event_date is not None and guests is not None:
        body = ("Thank you for sharing your details 😊\n"
                "Here is the package for your Pontoon Boat Celebration.\n\n" + body)
    if package.add_ons:
        return f"{body}\n\nAPPROVED ADD-ONS\n\n" + "\n".join(f"• {item}" for item in package.add_ons)
    return body

def action_message(
    package: StandardPackage,
    *,
    body: str = "What would you like to do next?",
    header_image_url: str | None = None,
) -> InteractiveMessage:
    # WhatsApp quick replies allow at most three buttons. The Standard package
    # has four required actions, so use one provider-supported list without
    # dropping any option.
    return InteractiveMessage(kind="list" if len(package.actions) > 3 else "buttons", body=body, fallback_text=body,
                              button_label="Package Actions", options=package.actions,
                              header_image_url=header_image_url)


def post_media_cta(package_id: str) -> InteractiveMessage:
    """Return one three-button sales continuation for a completed media sequence."""

    if package_id not in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID}:
        raise ValueError("unsupported_post_media_package")
    body = (
        "❤️ Ready to make it special?\n\nYou've just seen a glimpse of the Couple Romance experience.\n\n"
        "Book now, customize the experience, or ask me anything before you decide."
        if package_id == COUPLE_PACKAGE_ID
        else "✨ Ready to make it yours?\n\nYou've just seen a glimpse of the Pontoon Celebration experience.\n\n"
        "Book now, customize the experience, or ask me anything before you decide."
    )
    return InteractiveMessage(
        kind="buttons", body=body, fallback_text=body,
        button_label="Choose an option",
        options=(
            InteractiveOption("coimbatore_pontoon_book_standard", "Book Now"),
            InteractiveOption("coimbatore_pontoon_customize", "Customize"),
            InteractiveOption("coimbatore_pontoon_ask_question", "Ask a Question"),
        ),
    )

def package_presented(context: ConversationContext) -> bool:
    return bool((context.form_values or {}).get("standard_package_presented"))

def mark_presented(context: ConversationContext, package: StandardPackage) -> ConversationContext:
    values = dict(context.form_values or {})
    values.update({"standard_package_presented": True, "standard_package_id": package.package_id})
    return replace(context, form_values=values)

def action_id(text: object) -> str | None:
    value = text.casefold().strip() if isinstance(text, str) else ""
    exact = {
        "coimbatore_pontoon_book_standard", "coimbatore_pontoon_ask_question",
        "coimbatore_pontoon_customize", "coimbatore_pontoon_more_photos",
        "coimbatore_pontoon_brochure",
        "coimbatore_pontoon_check_couple", "coimbatore_pontoon_check_standard",
    }
    if value in exact: return value
    if re.search(r"\b(book now|book this|book package|book it|i want this|i am interested|proceed|how to book|send payment|i want to confirm)\b", value): return "coimbatore_pontoon_book_standard"
    if re.search(r"\b(ask a question|i have a question|question about package)\b", value): return "coimbatore_pontoon_ask_question"
    if re.search(r"\b(customize|custom package|special decoration|special request|i want changes|call me|talk to team|need human|contact person)\b", value): return "coimbatore_pontoon_customize"
    if re.search(r"\b(see photo (?:and|&) video|show more photos|more pictures|photos|show images|aur photos|photo dikhao)\b", value): return "coimbatore_pontoon_more_photos"
    if re.search(r"\b(?:see|send|show|open|download)(?: the)?(?: pontoon(?: boat)?(?: celebration)?)? brochure\b", value): return "coimbatore_pontoon_brochure"
    if re.search(r"\b(check|show|see) (?:the )?couple package\b", value): return "coimbatore_pontoon_check_couple"
    if re.search(r"\b(check|show|see) (?:the )?standard package\b", value): return "coimbatore_pontoon_check_standard"
    return None

def is_package_request(text: object) -> bool:
    return package_request_id(text) is not None


def package_request_id(text: object) -> str | None:
    """Resolve explicit canonical requests; ``choice`` means genuinely vague."""
    value = text.casefold().strip() if isinstance(text, str) else ""
    if re.search(r"\b(?:price|cost|rate|inclusions?|included|cake|pyros?|duration|how long|token|refund|book|booking|customi[sz]e|photos?)\b", value):
        return None
    normalized = value.replace("₹", "").replace(",", "")
    if re.search(r"\b(?:3999\s*package|couple(?: romance)?\s*package|romantic\s*package|couple romance|package\s+for\s+(?:a\s+)?couple|package\s+for\s+2)\b", normalized):
        return COUPLE_PACKAGE_ID
    if re.search(r"\b(?:5999\s*package|standard(?: pontoon)?\s*package|send\s+(?:me\s+)?standard\s*package|show\s+(?:me\s+)?standard\s*package)\b", normalized):
        return STANDARD_PACKAGE_ID
    if re.fullmatch(r"(?:please\s+)?(?:package|send (?:me )?(?:the )?package(?: again)?|package details|send full details(?: plz| please)?|what is your package|what package do you have)\s*[?.!]*", normalized):
        return "choice"
    return None

def answer_package_question(text: object, package: StandardPackage) -> str | None:
    """Answer only narrow facts that are explicitly present in the package KB."""
    value = text.casefold().strip() if isinstance(text, str) else ""
    if "cake" in value and any(item.casefold() == "cake" for item in package.inclusions):
        return "Yes 😊 Cake is included in the Standard Pontoon Celebration Package."
    if re.search(r"\b(how much is it|offer price|price|cost)\b", value):
        return f"The original package price is {package.rack_rate}. The current offer price is {package.offer_rate}."
    if re.search(r"\b(token|advance)\b", value):
        return "Our team will help you with the current payment and booking steps."
    return None

def payment_page_url(
    public_base_url: str | None,
    package_id: str,
    booking_ref: str | None = None,
    *,
    pricing_slab: str | None = None,
    payment_destination_configured: bool = True,
) -> str | None:
    """Build only an HTTPS URL for one explicitly supported package."""

    parsed = urlparse(public_base_url) if isinstance(public_base_url, str) else None
    if parsed is None or parsed.scheme != "https" or not parsed.netloc:
        return None
    if not payment_destination_configured:
        return None
    if package_id == STANDARD_PACKAGE_ID:
        path = {
            None: "/pay/coimbatore/standard", "up_to_6": "/pay/coimbatore/standard",
            "up_to_9": "/pay/coimbatore/standard/up-to-9",
            "up_to_12": "/pay/coimbatore/standard/up-to-12",
        }.get(pricing_slab)
    else:
        path = "/pay/coimbatore/couple-romance" if package_id == COUPLE_PACKAGE_ID else None
    if path is None:
        return None
    url = f"{public_base_url.rstrip('/')}{path}"
    if isinstance(booking_ref, str) and re.fullmatch(r"[A-Za-z0-9-]{1,32}", booking_ref.strip()):
        url = f"{url}?booking_ref={booking_ref.strip()}"
    return url


def handle_action(
    action: str,
    context: ConversationContext,
    *,
    public_base_url: str | None = None,
    standard_up_to_6_payment_configured: bool = True,
    standard_up_to_9_payment_configured: bool = False,
    standard_up_to_12_payment_configured: bool = False,
) -> ConversationResult:
    planned, guests = context.details.preferred_date, context.details.total_guests
    metadata = {"response_mode": "deterministic_interactive", "response_basis": "deterministic", "structured_grounding": True,
                "customer_response_sanitized": True, "button_action": action, "service_code": "pontoon_celebration"}
    handover = action == "coimbatore_pontoon_customize"
    if action in {"coimbatore_pontoon_check_couple", "coimbatore_pontoon_check_standard"}:
        package_id = COUPLE_PACKAGE_ID if action == "coimbatore_pontoon_check_couple" else STANDARD_PACKAGE_ID
        package = load_package(package_id)
        values = dict(context.form_values or {})
        values.update({"active_package_id": package_id, "standard_package_presented": True, "standard_package_id": package_id})
        if package_id == STANDARD_PACKAGE_ID:
            pricing = resolve_standard_package_pricing(guests)
            if pricing is not None:
                values.update({"pricing_slab": pricing.slab_id, "regular_price": pricing.regular_price,
                               "offer_price": pricing.offer_price})
        context = replace(context, form_values=values, sales_stage=SalesStage.PACKAGE_PRESENTED)
        text = render_package(package, planned, guests)
        metadata.update({
            "package_id": package_id,
            "interactive_message": action_message(package, body=text).as_metadata(),
            "approved_package": True,
            "approved_coimbatore_master": True,
            "exact_kb_package_block": True,
            "answer_source": "pontoon_package_boundary",
            "source_filename": "COIMBATORE_KNOWLEDGE_BASE.md",
            "knowledge_location": "coimbatore",
            "authority": "approved_current",
            "automatic_reply_category": "information",
            "source_heading": (
                "ACTIVE COUPLE ROMANCE PONTOON PACKAGE — CUSTOMER PRESENTATION"
                if package_id == COUPLE_PACKAGE_ID
                else "ACTIVE STANDARD PONTOON PACKAGE — CUSTOMER PRESENTATION"
            ),
        })
    elif action == "coimbatore_pontoon_book_standard":
        if planned is None:
            return ConversationResult(
                action="answer_information",
                draft_text="Sure 😊 Please share your celebration date before we continue with booking.",
                reason_code="coimbatore_booking_date_required",
                detected_intent="booking",
                detected_location="coimbatore",
                response_language="en",
                human_handover_required=False,
                context=replace(context, pending_field="preferred_date"),
                safe_metadata={**metadata, "booking_allowed": False, "date_required": True},
            )
        values = dict(context.form_values or {})
        package_id = values.get("active_package_id")
        if package_id not in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID}:
            package_id = values.get("standard_package_id")
        pricing = resolve_standard_package_pricing(guests) if package_id == STANDARD_PACKAGE_ID else None
        configured = True
        if pricing is not None:
            configured = {
                "up_to_6": standard_up_to_6_payment_configured,
                "up_to_9": standard_up_to_9_payment_configured,
                "up_to_12": standard_up_to_12_payment_configured,
            }[pricing.slab_id]
            values.update({"pricing_slab": pricing.slab_id, "regular_price": pricing.regular_price,
                           "offer_price": pricing.offer_price})
        url = payment_page_url(
            public_base_url, package_id, pricing_slab=pricing.slab_id if pricing else None,
            payment_destination_configured=configured and (package_id != STANDARD_PACKAGE_ID or pricing is not None),
        ) if isinstance(package_id, str) else None
        values["booking_intent"] = True
        context = replace(context, form_values=values, sales_stage=SalesStage.PAYMENT_PENDING, pending_field=None)
        if url is None and pricing is not None:
            text = (f"Your booking amount is ₹{pricing.offer_price:,}. I'm getting the secure payment option "
                    "ready for this booking.")
            logger.warning("coimbatore_standard_payment_destination_missing pricing_slab=%s offer_price=%s",
                           pricing.slab_id, pricing.offer_price)
            metadata.update(automatic_reply_category="information", payment_link_unavailable=True,
                            package_id=package_id, pricing_slab=pricing.slab_id,
                            offer_price=pricing.offer_price, offer_price_paise=pricing.offer_price_paise)
        elif url is None:
            text = "I couldn't prepare a secure payment link right now. Our team will help you continue safely."
            metadata.update(automatic_reply_category="information", payment_link_unavailable=True)
        elif package_id == COUPLE_PACKAGE_ID:
            text = (
                "❤️ Book Now & Save 15%\n\n"
                "Make your celebration special! You're getting an exclusive 15% instant booking discount "
                "for confirming your Couple Romance celebration now.\n\n"
                "Complete your secure payment through Razorpay using the link below. You'll be asked for "
                "your customer details during the payment process.\n\n"
                f"🔒 Secure Payment by Razorpay\n\nPay & Confirm Booking:\n{url}"
            )
        else:
            text = (
                "🎉 Book Now & Save 15%\n\n"
                "Great choice! You're getting an exclusive 15% instant booking discount for confirming "
                "your Pontoon Celebration now.\n\n"
                "Complete your secure payment through Razorpay using the link below. You'll be asked for "
                "your customer details during the payment process.\n\n"
                f"🔒 Secure Payment by Razorpay\n\nPay & Confirm Booking:\n{url}"
            )
        if url is not None:
            metadata.update({
                "package_id": package_id, "payment_page_path": urlparse(url).path,
                "approved_package": True, "approved_coimbatore_master": True,
                "answer_source": "pontoon_package_boundary",
                "source_filename": "COIMBATORE_KNOWLEDGE_BASE.md",
                "knowledge_location": "coimbatore", "authority": "approved_current",
                "automatic_reply_category": "information",
            })
            if pricing is not None:
                metadata.update(pricing_slab=pricing.slab_id, regular_price=pricing.regular_price,
                                offer_price=pricing.offer_price, offer_price_paise=pricing.offer_price_paise)
    elif action == "coimbatore_pontoon_ask_question":
        active_package = (context.form_values or {}).get("active_package_id")
        package_name = "Couple Romance Package" if active_package == COUPLE_PACKAGE_ID else "Standard Pontoon Package"
        text = f"Sure 😊 What would you like to know about the {package_name}?"
    elif handover:
        text = "Sure 😊 Our team will help you with a customized celebration requirement."
        context = replace(context, sales_stage=SalesStage.HANDOVER)
        metadata["handover_context"] = {
            "location": "coimbatore", "service": "pontoon_celebration",
            "package_id": (context.form_values or {}).get("active_package_id"),
            "planned_date": planned.isoformat() if planned is not None else None, "guest_count": guests,
        }
        pricing = resolve_standard_package_pricing(guests) if (context.form_values or {}).get("active_package_id") == STANDARD_PACKAGE_ID else None
        if pricing is not None:
            metadata["handover_context"].update(pricing_slab=pricing.slab_id,
                                                 regular_price=pricing.regular_price,
                                                 offer_price=pricing.offer_price)
    elif action == "coimbatore_pontoon_more_photos":
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        values = context.form_values or {}
        active_package = values.get("active_package_id") or values.get("standard_package_id")
        if active_package not in {STANDARD_PACKAGE_ID, COUPLE_PACKAGE_ID}:
            text = "I couldn't identify the active package for those photos. Please choose a package first."
            metadata.update(automatic_reply_category="information", media_sequence_unavailable=True)
            return ConversationResult(
                action="answer_information", draft_text=text,
                reason_code="coimbatore_media_package_context_missing", detected_intent="general_information",
                detected_location="coimbatore", response_language="en", human_handover_required=False,
                context=context, safe_metadata=metadata,
            )
        media_group = "couple_action_media" if active_package == COUPLE_PACKAGE_ID else "action_media"
        sequence = (config.get(media_group) or {}).get("coimbatore_pontoon_more_photos")
        expected_count = 3
        if not isinstance(sequence, list) or len(sequence) != expected_count:
            raise ValueError("coimbatore_photo_video_sequence_missing")
        package_label = "Couple Romance" if active_package == COUPLE_PACKAGE_ID else "Pontoon Celebration"
        text = f"Here are the approved {package_label} photo{'s' if expected_count == 3 else ''} and video 😊"
        metadata["media_sequence"] = [
            {"type": str(item["type"]), "url": str(item["url"]),
             "caption": f"{package_label} photo" if item["type"] == "image" else f"{package_label} video"}
            for item in sequence
        ]
        metadata.update({
            "package_id": active_package,
            "interactive_message": post_media_cta(active_package).as_metadata(),
            "post_media_cta": True,
            "automatic_reply_category": "information",
        })
    elif action == "coimbatore_pontoon_brochure":
        active_package = (context.form_values or {}).get("active_package_id")
        if active_package != STANDARD_PACKAGE_ID:
            text = "Please select the Standard Pontoon Package to view its brochure."
        else:
            text = "Here is the Pontoon Boat Celebration brochure 😊"
            metadata.update({
                "package_id": STANDARD_PACKAGE_ID,
                "document_message": {
                    "type": "document",
                    "url": STANDARD_PACKAGE_BROCHURE_URL,
                    "caption": "Pontoon Boat Celebration Brochure",
                    "filename": "Pontoon-Celebration-Brochure.pdf",
                },
                "automatic_reply_category": "information",
            })
    return ConversationResult(action="general_human_handover" if handover else "answer_information", draft_text=text,
        reason_code="coimbatore_pontoon_package_action", detected_intent="human_support" if handover else "general_information",
        detected_location="coimbatore", response_language="en", human_handover_required=handover, context=context, safe_metadata=metadata)
