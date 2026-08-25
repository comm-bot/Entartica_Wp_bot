"""Minimal Razorpay Standard Payment Links API client."""
from __future__ import annotations

from typing import Any
import httpx


class RazorpayConfigurationError(RuntimeError):
    pass


class RazorpayPaymentLinkClient:
    def __init__(self, *, key_id: str, key_secret: str, mode: str = "test",
                 api_base_url: str = "https://api.razorpay.com/v1",
                 transport: httpx.BaseTransport | None = None) -> None:
        if mode != "test":
            raise RazorpayConfigurationError("razorpay_test_mode_required")
        if not key_id.startswith("rzp_test_"):
            raise RazorpayConfigurationError("razorpay_test_key_required")
        if not key_secret:
            raise RazorpayConfigurationError("razorpay_key_secret_required")
        self._key_id, self._key_secret = key_id, key_secret
        self._base_url, self._transport = api_base_url.rstrip("/"), transport

    def create_payment_link(self, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(auth=(self._key_id, self._key_secret), timeout=15,
                          transport=self._transport) as client:
            response = client.post(f"{self._base_url}/payment_links", json=payload)
            response.raise_for_status()
            data = response.json()
        required = ("id", "short_url", "reference_id", "amount", "currency", "status")
        if not isinstance(data, dict) or any(data.get(field) in (None, "") for field in required):
            raise RuntimeError("razorpay_payment_link_response_invalid")
        return data
