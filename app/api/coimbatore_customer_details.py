"""Mobile web form for Coimbatore pre-chat customer details."""
from __future__ import annotations

from functools import lru_cache
from html import escape
import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.integrations.supabase import get_supabase_client
from app.services.coimbatore.customer_details import CustomerDetailsFormService
from app.services.coimbatore.customer_details_delivery import CustomerDetailsDelivery


router = APIRouter(prefix="/coimbatore/details", tags=["coimbatore-customer-details"])
logger = logging.getLogger("uvicorn.error")


@lru_cache(maxsize=1)
def get_customer_details_service() -> CustomerDetailsFormService:
    settings = get_settings()
    return CustomerDetailsFormService(
        get_supabase_client(), public_base_url=settings.public_base_url,
        ttl_minutes=settings.coimbatore_customer_details_form_ttl_minutes,
    )


def get_customer_details_delivery() -> CustomerDetailsDelivery:
    return CustomerDetailsDelivery(get_supabase_client(), get_settings())


def _page(token: str, *, name: str = "", email: str = "", error: str | None = None,
          completed: bool = False) -> str:
    notice = f'<div class="error">{escape(error)}</div>' if error else ""
    content = ("<h1>Thank you! 😊</h1><p>Your details have been saved.</p>"
               "<p>You can return to WhatsApp now.</p>") if completed else f"""
      <h1>Entartica Coimbatore</h1>
      <h2>Let's get to know you 😊</h2>
      <p>This will help us assist you better.</p>{notice}
      <form method="post" action="/coimbatore/details/{escape(token, quote=True)}" novalidate>
        <label for="full_name">Full Name <span>*</span></label>
        <input id="full_name" name="full_name" type="text" maxlength="120" autocomplete="name" required value="{escape(name, quote=True)}">
        <label for="email">Email Address <span>*</span></label>
        <input id="email" name="email" type="email" maxlength="254" autocomplete="email" required value="{escape(email, quote=True)}">
        <button type="submit">Continue</button>
      </form>"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Entartica Coimbatore</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f2f8f6;color:#173b34;font-family:Arial,sans-serif}}
    main{{width:min(92%,430px);margin:7vh auto;background:#fff;padding:28px;border-radius:16px;box-shadow:0 8px 30px #0b66551f}}
    h1{{color:#0b6655;font-size:25px;margin:0 0 18px}}h2{{font-size:19px;margin:0 0 8px}}p{{line-height:1.5;color:#50645f}}
    label{{display:block;font-weight:700;margin:20px 0 7px}}span{{color:#b42318}}input{{width:100%;padding:13px;border:1px solid #a9bbb6;border-radius:8px;font-size:16px}}
    input:focus{{outline:3px solid #0b66552b;border-color:#0b6655}}button{{width:100%;margin-top:24px;padding:14px;border:0;border-radius:8px;background:#0b6655;color:#fff;font-size:17px;font-weight:700}}
    .error{{background:#fff0ed;color:#9b251d;border:1px solid #e7a39c;padding:10px;border-radius:8px;margin-top:14px}}
    </style></head><body><main>{content}</main></body></html>"""


@router.get("/{token}", response_class=HTMLResponse)
def show_customer_details(token: str) -> HTMLResponse:
    row, reason = get_customer_details_service().resolve(token)
    if row is None:
        message = "This form link has expired. Please return to WhatsApp and request a new link." if reason == "expired_token" else "This form link is invalid. Please return to WhatsApp and request a new link."
        return HTMLResponse(_page("", error=message), status_code=410 if reason == "expired_token" else 404)
    return HTMLResponse(_page(token, completed=row.get("status") == "completed"))


@router.post("/{token}", response_class=HTMLResponse)
async def submit_customer_details(token: str, request: Request) -> HTMLResponse:
    # The page posts only application/x-www-form-urlencoded data. Parsing the
    # bounded body here avoids adding a multipart dependency for a two-field form.
    body = await request.body()
    if len(body) > 4096:
        return HTMLResponse(_page(token, error="The submitted form is too large."), status_code=413)
    form = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    name = str((form.get("full_name") or [""])[0])
    email = str((form.get("email") or [""])[0])
    result = get_customer_details_service().submit(token, name=name, email=email)
    if not result.accepted:
        messages = {
            "invalid_name": "Please enter your full name.",
            "invalid_email": "Please enter a valid email address.",
            "expired_token": "This form link has expired. Please request a new link in WhatsApp.",
            "invalid_token": "This form link is invalid. Please request a new link in WhatsApp.",
        }
        status = 422 if result.reason in {"invalid_name", "invalid_email"} else 410 if result.reason == "expired_token" else 404 if result.reason == "invalid_token" else 503
        return HTMLResponse(_page(token, name=name, email=email,
                                  error=messages.get(result.reason, "We couldn't save your details. Please try again.")), status_code=status)
    if not result.duplicate and result.customer and result.conversation_id and result.form_id:
        first_name = str(result.customer.get("name") or "").split()[0]
        continuation = (f"Thanks {first_name}! 👋\n\n"
                        "How many guests will be visiting, and what date are you planning for?\n\n"
                        "💡 eg. 7 , 26/08/2026")
        try:
            await get_customer_details_delivery().send(
                customer=result.customer, conversation_id=result.conversation_id,
                form_id=result.form_id, content=continuation,
            )
        except Exception:
            # Details are safely persisted; the next inbound greeting resumes the flow.
            logger.exception("coimbatore_customer_details_continuation_failed")
    return HTMLResponse(_page(token, completed=True))
