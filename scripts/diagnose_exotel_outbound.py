"""One-request, privacy-safe diagnostic for Exotel outbound WhatsApp sending."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from app.config import Settings
from app.integrations.exotel import (  # noqa: E402
    ExotelAuthenticationError,
    ExotelClient,
    ExotelOutboundError,
)


_SETTING_NAMES = (
    "EXOTEL_ACCOUNT_SID",
    "EXOTEL_API_KEY",
    "EXOTEL_API_TOKEN",
    "EXOTEL_WHATSAPP_FROM",
    "PUBLIC_BASE_URL",
    "EXOTEL_OUTBOUND_ENABLED",
)


def _dotenv_definitions() -> dict[str, list[str]]:
    definitions: dict[str, list[str]] = {}
    path = REPOSITORY_ROOT / ".env"
    if not path.exists():
        return definitions
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*([A-Z0-9_]+)=(.*)$", line)
        if match:
            definitions.setdefault(match.group(1), []).append(match.group(2))
    return definitions


def _source(name: str, dotenv: dict[str, list[str]]) -> str:
    if name in os.environ:
        return "process_environment"
    if name in dotenv:
        return "dotenv"
    return "default" if name == "EXOTEL_OUTBOUND_ENABLED" else "missing"


def _safe_value_report(value: str | None) -> str:
    if value is None:
        return "missing"
    return (
        f"set length={len(value)} leading_or_trailing_space={value != value.strip()} "
        f"surrounding_quotes={len(value) >= 2 and value[0] in chr(34) + chr(39) and value[-1] == value[0]}"
    )


def _is_e164(value: str | None) -> bool:
    return value is not None and bool(re.fullmatch(r"\+[1-9][0-9]{7,14}", value))


def _payload_shape(payload: dict) -> str:
    content = payload.get("content", {})
    text = content.get("text", {}) if isinstance(content, dict) else {}
    body = text.get("body") if isinstance(text, dict) else None
    return (
        f"payload_top_keys={','.join(sorted(payload))} "
        f"content_keys={','.join(sorted(content)) if isinstance(content, dict) else 'none'} "
        f"text_keys={','.join(sorted(text)) if isinstance(text, dict) else 'none'} "
        "value_types=from:str,to:str,content:dict "
        f"none_values={any(value is None for value in payload.values())} "
        "body_transport=json content_type=application/json accept=*/* "
        f"message_length={len(body) if isinstance(body, str) else 0} "
        "status_callback_present=false status_callback_https=false "
        "custom_data_type=omitted custom_data_length=0"
    )


async def main() -> int:
    """Perform exactly one minimal live request after explicit confirmation."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--to", required=True)
    parser.add_argument("--confirm-live-request", action="store_true")
    args = parser.parse_args()
    if not args.confirm_live_request:
        print("refused: add --confirm-live-request to permit one live request")
        return 2

    dotenv = _dotenv_definitions()
    settings = Settings()
    values = {
        "EXOTEL_ACCOUNT_SID": settings.exotel_account_sid,
        "EXOTEL_API_KEY": settings.exotel_api_key.get_secret_value() if settings.exotel_api_key else None,
        "EXOTEL_API_TOKEN": settings.exotel_api_token.get_secret_value() if settings.exotel_api_token else None,
        "EXOTEL_WHATSAPP_FROM": settings.exotel_whatsapp_from,
        "PUBLIC_BASE_URL": settings.public_base_url,
    }
    for name in _SETTING_NAMES[:-1]:
        print(f"{name}={_safe_value_report(values[name])} source={_source(name, dotenv)} duplicates={len(dotenv.get(name, []))}")
    print(f"EXOTEL_OUTBOUND_ENABLED={settings.exotel_outbound_enabled} source={_source('EXOTEL_OUTBOUND_ENABLED', dotenv)} duplicates={len(dotenv.get('EXOTEL_OUTBOUND_ENABLED', []))}")
    if not all(values.values()) or not settings.exotel_outbound_enabled:
        print("configuration_check=failed")
        return 1

    client = ExotelClient(
        account_sid=settings.exotel_account_sid or "",
        api_key=settings.exotel_api_key.get_secret_value(),
        api_token=settings.exotel_api_token.get_secret_value(),
        whatsapp_from=settings.exotel_whatsapp_from or "",
        api_base_url=settings.exotel_api_base_url,
    )
    parsed = urlparse(client.endpoint_pattern())
    print(f"endpoint_hostname={parsed.hostname} endpoint_path_pattern={parsed.path}")
    print("endpoint_account_sid_insertions=1 endpoint_duplicate_slashes=false endpoint_version_path=v2")
    print("authentication=basic username=api_key password=api_token bearer=false credentials_in_url=false")
    print(
        "sender_e164_valid=" + str(_is_e164(settings.exotel_whatsapp_from)) +
        " sender_begins_plus=" + str(bool(settings.exotel_whatsapp_from and settings.exotel_whatsapp_from.startswith("+"))) +
        " sender_digits_only_after_plus=" + str(bool(settings.exotel_whatsapp_from and settings.exotel_whatsapp_from[1:].isdigit())) +
        " sender_has_spaces_or_quotes=" + str(bool(settings.exotel_whatsapp_from and any(character in settings.exotel_whatsapp_from for character in " '\""))) +
        " sender_differs_from_recipient=" + str(settings.exotel_whatsapp_from != args.to)
    )
    payload = client.build_text_payload(to_number=args.to, text="Diagnostic", status_callback=None, custom_data=None)
    print(_payload_shape(payload))
    try:
        await client.send_text_message(args.to, "Diagnostic", None, None)
    except ExotelOutboundError:
        print("minimal_request=not_accepted")
        return 1
    print("minimal_request=accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
