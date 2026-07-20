"""Perform a read-only Supabase connectivity check."""

from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from app.integrations.supabase import get_supabase_client


def main() -> int:
    """Count readable location and service records without exposing secrets."""

    try:
        client = get_supabase_client()
        locations = client.table("locations").select("id", count="exact").execute()
        services = client.table("services").select("id", count="exact").execute()
    except Exception:
        print("Supabase connection check failed.")
        return 1

    print("Supabase connection successful")
    print(f"Locations found: {locations.count or 0}")
    print(f"Services found: {services.count or 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
