"""Idempotently seed only approved Raipur data after explicit confirmation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.supabase import get_supabase_client
from app.services.raipur_seed import (
    load_seed_json,
    location_database_row,
    service_database_row,
    validate_raipur_seed,
)


def _response_row(response: object) -> dict[str, Any] | None:
    data = getattr(response, "data", None) if response is not None else None
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def seed_raipur(*, location: dict[str, Any], services_document: dict[str, Any]) -> tuple[int, int]:
    """Upsert Raipur and its approved services without altering other locations."""

    client = get_supabase_client()
    location_response = client.table("locations").upsert(
        location_database_row(location), on_conflict="slug"
    ).execute()
    location_row = _response_row(location_response)
    if location_row is None or not isinstance(location_row.get("id"), str):
        raise RuntimeError("Raipur location upsert did not return a location identifier.")
    location_id = location_row["id"]
    service_count = 0
    for service in services_document["services"]:
        client.table("services").upsert(
            service_database_row(service, location_id), on_conflict="location_id,slug"
        ).execute()
        service_count += 1
    return 1, service_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Allow the idempotent Raipur-only upsert.")
    parser.add_argument("--allow-placeholders", action="store_true", help="Allow development placeholders only.")
    parser.add_argument("--location", type=Path, default=ROOT / "data/seed/raipur_location.example.json")
    parser.add_argument("--services", type=Path, default=ROOT / "data/seed/raipur_services.example.json")
    args = parser.parse_args()
    if not args.confirm:
        print("seed_refused confirmation_required=true")
        return 2
    try:
        location = load_seed_json(args.location)
        services_document = load_seed_json(args.services)
        result = validate_raipur_seed(location, services_document)
    except (OSError, ValueError) as error:
        print(f"seed_failed error_class={type(error).__name__}")
        return 1
    if result.errors:
        print(f"seed_refused validation_error_count={len(result.errors)}")
        return 1
    if result.placeholders and not args.allow_placeholders:
        print(f"seed_refused unresolved_placeholder_count={len(result.placeholders)}")
        return 1
    try:
        location_count, service_count = seed_raipur(location=location, services_document=services_document)
    except Exception as error:
        print(f"seed_failed error_class={type(error).__name__}")
        return 1
    print(f"seed_complete location_count={location_count} service_count={service_count} location_name=Entartica_SeaWorld_Raipur")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
