"""Explicit, dry-run-first CLI for one approved Raipur draft send."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _secret(value: Any) -> str | None:
    if value is None:
        return None
    return value.get_secret_value() if hasattr(value, "get_secret_value") else value if isinstance(value, str) else None


def build_controlled_sender_dependencies() -> tuple[Any, Any, Any]:
    """Build the already-approved sender components only after confirmation."""
    from app.config import get_settings
    from app.integrations.exotel import ExotelClient
    from app.integrations.supabase import get_supabase_client
    from app.repositories.outbound_drafts import OutboundDraftRepository
    from app.services.raipur_draft_sender import RaipurDraftSender

    settings = get_settings()
    account_sid, api_key, api_token = _secret(settings.exotel_account_sid), _secret(settings.exotel_api_key), _secret(settings.exotel_api_token)
    if not all((account_sid, api_key, api_token, settings.exotel_whatsapp_from)):
        raise RuntimeError("outbound_configuration_unavailable")
    client = get_supabase_client()
    repository = OutboundDraftRepository(client)
    exotel = ExotelClient(account_sid=account_sid, api_key=api_key, api_token=api_token,
                          whatsapp_from=settings.exotel_whatsapp_from, api_base_url=settings.exotel_api_base_url)
    return settings, repository, RaipurDraftSender(repository, settings, exotel)


def _print_live(*, settings: Any | None, draft: dict[str, Any] | None, recipient: str,
                result: Any | None, reason: str) -> None:
    configured = bool(settings and settings.exotel_outbound_enabled and settings.raipur_approved_draft_send_enabled)
    allowlisted = bool(settings and recipient in settings.raipur_outbound_test_recipients)
    approved = bool(draft and draft.get("draft_status") == "approved" and isinstance(draft.get("draft_metadata"), dict) and draft["draft_metadata"].get("response_valid"))
    attempted = bool(result and result.attempted)
    accepted = bool(result and result.accepted)
    sid_recorded = bool(result and result.sid_recorded)
    duplicate = bool(result and result.duplicate_prevented)
    print("mode=live")
    print(f"configuration_ready={str(configured).lower()}")
    print(f"draft_found={str(isinstance(draft, dict)).lower()}")
    print(f"draft_approved={str(approved).lower()}")
    print(f"recipient_allowlisted={str(allowlisted).lower()}")
    print(f"send_attempted={str(attempted).lower()}")
    print(f"api_accepted={str(accepted).lower()}")
    print(f"sid_recorded={str(sid_recorded).lower()}")
    print(f"duplicate_send_prevented={str(duplicate).lower()}")
    print(f"message_sent={str(accepted and sid_recorded).lower()}")
    print(f"reason={reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--to", required=True)
    parser.add_argument("--confirm-send", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_send:
        print("mode=dry_run\nreason=dry_run")
        return 0
    try:
        settings, repository, sender = build_controlled_sender_dependencies()
        draft = repository.get_draft_by_id(args.draft_id)
        result = asyncio.run(sender.send(args.draft_id, args.to, confirmed=True))
        _print_live(settings=settings, draft=draft, recipient=args.to, result=result, reason=result.reason)
        return 0 if result.accepted and result.sid_recorded else 1
    except Exception:
        _print_live(settings=None, draft=None, recipient=args.to, result=None, reason="configuration_unavailable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
