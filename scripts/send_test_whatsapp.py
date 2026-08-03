"""Send one explicitly requested WhatsApp test message through Exotel."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from app.config import get_settings
from app.integrations.supabase import get_supabase_client
from app.services.outbound_messages import (
    OutboundMessageError,
    OutboundMessageService,
)


def _redact(value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if len(value) > 8 else "[redacted]"


async def main() -> int:
    """Validate explicit arguments and submit the manually requested test."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--to", required=True)
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    if not get_settings().exotel_outbound_enabled:
        print("failed: outbound messaging is disabled")
        return 1
    try:
        result = await OutboundMessageService(get_supabase_client()).send_text_message(
            to_number=args.to, text=args.message
        )
    except OutboundMessageError:
        print("failed: provider request was not accepted")
        return 1
    print(f"accepted: status=2xx provider_sid={_redact(result.provider_message_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
