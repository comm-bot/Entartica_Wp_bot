"""Public Razorpay Payment Button pages for approved Coimbatore packages."""

from __future__ import annotations

from html import escape
import re

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.config import get_settings


router = APIRouter(prefix="/pay/coimbatore", tags=["coimbatore-payments"])
_BOOKING_REF = re.compile(r"^[A-Za-z0-9-]{1,32}$")


def _safe_booking_ref(value: str | None) -> str | None:
    candidate = value.strip() if isinstance(value, str) else ""
    return candidate if _BOOKING_REF.fullmatch(candidate) else None


def _payment_page(*, celebration_name: str, payment_button_id: str, booking_ref: str | None) -> HTMLResponse:
    safe_ref = _safe_booking_ref(booking_ref)
    reference = f'<p class="reference">Booking Reference: {escape(safe_ref)}</p>' if safe_ref else ""
    safe_name = escape(celebration_name)
    safe_button_id = escape(payment_button_id, quote=True)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_name} | Entartica Coimbatore</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, system-ui, sans-serif; }}
    body {{ margin:0; background:#f4f8f7; color:#17322d; display:grid; min-height:100vh; place-items:center; }}
    main {{ box-sizing:border-box; width:min(92%, 460px); margin:24px; padding:30px 24px; background:white; border-radius:18px; box-shadow:0 12px 40px rgba(18,63,54,.14); text-align:center; }}
    .brand {{ color:#16715f; font-size:.9rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
    h1 {{ font-size:1.65rem; margin:.65rem 0 .25rem; }}
    h2 {{ color:#16715f; font-size:1.15rem; margin:.3rem 0 1rem; }}
    p {{ line-height:1.55; }}
    .reference {{ background:#f1f7f5; border-radius:8px; font-size:.82rem; padding:8px; word-break:break-word; }}
    form {{ margin:24px 0 18px; min-height:48px; }}
    .secure {{ color:#58706b; font-size:.82rem; }}
  </style>
</head>
<body>
  <main>
    <div class="brand">Entartica Coimbatore</div>
    <h1>{safe_name}</h1>
    <h2>Book Now Offer</h2>
    <p>You've unlocked an exclusive 15% instant booking discount.</p>
    <p>Complete your secure payment below to proceed with your booking.</p>
    {reference}
    <form><script src="https://checkout.razorpay.com/v1/payment-button.js" data-payment_button_id="{safe_button_id}" async></script></form>
    <p class="secure">🔒 Secure Payment powered by Razorpay</p>
  </main>
</body>
</html>"""
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'self'; script-src https://checkout.razorpay.com; "
                "frame-src https://checkout.razorpay.com https://api.razorpay.com; "
                "connect-src https://api.razorpay.com https://checkout.razorpay.com; "
                "style-src 'unsafe-inline'; img-src 'self' data: https:"
            ),
            "Referrer-Policy": "strict-origin-when-cross-origin",
        },
    )


def _configured_standard_payment_page(
    *, payment_button_id: str | None, offer_price: int, booking_ref: str | None,
) -> HTMLResponse:
    if not isinstance(payment_button_id, str) or not payment_button_id.strip():
        return HTMLResponse("Secure payment option is not configured for this booking amount.", status_code=503,
                            headers={"Cache-Control": "no-store"})
    return _payment_page(
        celebration_name=f"Pontoon Boat Celebration — ₹{offer_price:,} Offer",
        payment_button_id=payment_button_id, booking_ref=booking_ref,
    )


@router.get("/standard", response_class=HTMLResponse)
async def standard_payment_page(booking_ref: str | None = Query(default=None, max_length=128)) -> HTMLResponse:
    settings = get_settings()
    return _payment_page(
        celebration_name="Pontoon Boat Celebration",
        payment_button_id=settings.coimbatore_standard_razorpay_payment_button_id,
        booking_ref=booking_ref,
    )


@router.get("/standard/up-to-9", response_class=HTMLResponse)
async def standard_up_to_9_payment_page(booking_ref: str | None = Query(default=None, max_length=128)) -> HTMLResponse:
    settings = get_settings()
    return _configured_standard_payment_page(
        payment_button_id=settings.coimbatore_standard_up_to_9_razorpay_payment_button_id,
        offer_price=6375, booking_ref=booking_ref,
    )


@router.get("/standard/up-to-12", response_class=HTMLResponse)
async def standard_up_to_12_payment_page(booking_ref: str | None = Query(default=None, max_length=128)) -> HTMLResponse:
    settings = get_settings()
    return _configured_standard_payment_page(
        payment_button_id=settings.coimbatore_standard_up_to_12_razorpay_payment_button_id,
        offer_price=7650, booking_ref=booking_ref,
    )


@router.get("/couple-romance", response_class=HTMLResponse)
async def couple_romance_payment_page(booking_ref: str | None = Query(default=None, max_length=128)) -> HTMLResponse:
    settings = get_settings()
    return _payment_page(
        celebration_name="Couple Romance Celebration",
        payment_button_id=settings.coimbatore_couple_romance_razorpay_payment_button_id,
        booking_ref=booking_ref,
    )
