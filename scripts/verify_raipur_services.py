"""Read-only verification for the approved Raipur service manifest."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.supabase import get_supabase_client
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, normalize_service_text


def _rows(response: object) -> list[dict[str, Any]]:
    data = getattr(response, "data", None) if response is not None else None
    return data if isinstance(data, list) else [data] if isinstance(data, dict) else []


def _report(**values: object) -> dict[str, object]:
    return {
        "services_table_ready": values.get("services_table_ready", False),
        "raipur_location_ready": values.get("raipur_location_ready", False),
        "approved_service_count": len(APPROVED_RAIPUR_SERVICES),
        "existing_matching_services": values.get("existing_matching_services", 0),
        "active_matching_services": values.get("active_matching_services", 0),
        "inactive_matching_services": values.get("inactive_matching_services", 0),
        "duplicate_service_groups": values.get("duplicate_service_groups", 0),
        "missing_approved_services": values.get("missing_approved_services", len(APPROVED_RAIPUR_SERVICES)),
        "unexpected_raipur_services": values.get("unexpected_raipur_services", 0),
        "reason": values.get("reason", "unexpected_schema"),
    }


def inspect_raipur_services(client: Any) -> dict[str, object]:
    try:
        locations = _rows(client.table("locations").select("id,slug,is_active").eq("slug", "raipur").execute())
    except Exception:
        return _report(reason="raipur_location_unavailable")
    active = [row for row in locations if row.get("is_active") is True and isinstance(row.get("id"), str)]
    if len(active) != 1:
        return _report(services_table_ready=True, reason="raipur_location_missing" if not active else "duplicate_raipur_locations_require_review")
    location_id = active[0]["id"]
    try:
        services = _rows(client.table("services").select("id,name,slug,is_active").eq("location_id", location_id).execute())
    except Exception:
        return _report(raipur_location_ready=True, reason="services_table_unavailable")

    approved_by_slug = {item.slug: item for item in APPROVED_RAIPUR_SERVICES}
    groups: dict[str, list[dict[str, Any]]] = {}
    unexpected = 0
    for service in services:
        matched = approved_by_slug.get(service.get("slug"))
        if matched is None or normalize_service_text(service.get("name")) != normalize_service_text(matched.name):
            unexpected += 1
            continue
        groups.setdefault(matched.slug, []).append(service)
    duplicates = sum(1 for group in groups.values() if len(group) > 1)
    matching = sum(len(group) for group in groups.values())
    active_count = sum(1 for group in groups.values() for service in group if service.get("is_active") is True)
    inactive_count = matching - active_count
    missing = len(APPROVED_RAIPUR_SERVICES) - len(groups)
    reason = "ready"
    if duplicates:
        reason = "duplicate_raipur_services_require_review"
    elif unexpected:
        reason = "unexpected_raipur_service_requires_review"
    elif missing:
        reason = "approved_services_missing"
    return _report(services_table_ready=True, raipur_location_ready=True, existing_matching_services=matching,
                   active_matching_services=active_count, inactive_matching_services=inactive_count,
                   duplicate_service_groups=duplicates, missing_approved_services=missing,
                   unexpected_raipur_services=unexpected, reason=reason)


def main() -> int:
    report = inspect_raipur_services(get_supabase_client())
    print(" ".join(f"{key}={str(value).lower() if isinstance(value, bool) else value}" for key, value in report.items()))
    return 0 if report["reason"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
