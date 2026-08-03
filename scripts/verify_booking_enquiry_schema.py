"""Read-only, zero-row migration-007 schema diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.supabase import get_supabase_client

REQUIRED_COLUMNS = (
    "requested_service_id", "requested_service_text", "total_guests", "availability_status",
    "enquiry_status", "assigned_salesperson", "source", "source_message_id",
)
IDEMPOTENCY_INDEX = "booking_enquiries_whatsapp_source_message_idx"
REQUIRED_CONSTRAINTS = (
    "booking_enquiries_availability_status_check",
    "booking_enquiries_enquiry_status_check",
    "booking_enquiries_source_check",
)


@dataclass(frozen=True)
class SchemaReport:
    table_exists: bool
    missing_columns: tuple[str, ...] = ()
    missing_indexes: tuple[str, ...] = ()
    missing_constraints: tuple[str, ...] = ()
    database_error: str = "none"
    reason: str = "ready"

    @property
    def schema_ready(self) -> bool:
        return (
            self.table_exists and not self.missing_columns and not self.missing_indexes
            and not self.missing_constraints and self.database_error == "none"
        )


def _error_code(error: Exception) -> str:
    return str(getattr(error, "code", ""))


def _category(error: Exception) -> str:
    code = _error_code(error)
    status = getattr(error, "status", None)
    if code in {"401", "PGRST301"} or status == 401:
        return "authentication_failure"
    if code in {"42501", "403"} or status == 403:
        return "permission_failure"
    if code in {"PGRST106", "PGRST107", "PGRST202"}:
        return "schema_introspection_unavailable"
    if code in {"PGRST205", "42P01"}:
        return "table_missing"
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return "connection_failure"
    return "unexpected_schema"


def _missing_column_from_error(error: Exception) -> str | None:
    text = " ".join(str(getattr(error, key, "")) for key in ("message", "details"))
    match = re.search(r"(?:column|field)\s+['\"]?([a-z_]+)", text, re.I)
    value = match.group(1) if match else None
    return value if value in REQUIRED_COLUMNS else None


def _table_probe(client: Any, columns: tuple[str, ...]) -> None:
    client.table("booking_enquiries").select(",".join(columns)).limit(0).execute()


def inspect_schema(client: Any) -> SchemaReport:
    """Inspect schema only: every data query is `LIMIT 0` and never reads rows."""

    try:
        _table_probe(client, REQUIRED_COLUMNS)
    except Exception as error:
        category = _category(error)
        if category in {"authentication_failure", "permission_failure", "connection_failure"}:
            return SchemaReport(False, database_error=category, reason=category)
        if category == "table_missing":
            # A known core table missing too indicates a likely wrong project.
            try:
                client.table("locations").select("id").limit(0).execute()
            except Exception as core_error:
                if _category(core_error) == "table_missing":
                    return SchemaReport(False, database_error="wrong_database_project", reason="wrong_database_project")
            return SchemaReport(False, database_error="none", reason="table_missing")
        missing: list[str] = []
        for column in REQUIRED_COLUMNS:
            try:
                _table_probe(client, (column,))
            except Exception as column_error:
                name = _missing_column_from_error(column_error) or column
                if name not in missing:
                    missing.append(name)
        if missing:
            return SchemaReport(True, tuple(sorted(missing)), reason="column_missing")
        return SchemaReport(True, database_error=category, reason="unexpected_schema")

    # REST cannot read pg_catalog/information_schema. Use the optional existing
    # migration helper when available, but never mistake a missing helper for a
    # missing migration table or column.
    try:
        data = getattr(client.rpc("booking_enquiry_schema_ready").execute(), "data", None)
    except Exception as error:
        if _category(error) == "schema_introspection_unavailable":
            return SchemaReport(
                True,
                missing_indexes=("unverified",),
                missing_constraints=("unverified",),
                database_error="schema_introspection_unavailable",
                reason="unexpected_schema",
            )
        return SchemaReport(True, database_error=_category(error), reason=_category(error))
    if not isinstance(data, dict):
        return SchemaReport(True, database_error="unexpected_schema", reason="unexpected_schema")
    missing_indexes = tuple(value for value in data.get("missing_indexes", ()) if value in {IDEMPOTENCY_INDEX}) if isinstance(data.get("missing_indexes"), (list, tuple)) else (() if data.get("idempotency_index_exists") is True else (IDEMPOTENCY_INDEX,))
    reported_constraints = data.get("missing_constraints")
    if isinstance(reported_constraints, (list, tuple)):
        missing_constraints = tuple(value for value in reported_constraints if value in REQUIRED_CONSTRAINTS)
        return SchemaReport(True, missing_indexes=missing_indexes, missing_constraints=missing_constraints, reason="index_missing" if missing_indexes else ("constraint_missing" if missing_constraints else "ready"))
    # The helper supplied by migration 007 does not inspect check-constraint
    # definitions, so do not claim that they were verified.
    return SchemaReport(
        True,
        missing_indexes=missing_indexes,
        missing_constraints=("unverified",),
        database_error="schema_introspection_unavailable",
        reason="index_missing" if missing_indexes else "unexpected_schema",
    )


def _list(values: tuple[str, ...]) -> str:
    return ",".join(values) if values else "none"


def main() -> int:
    try:
        report = inspect_schema(get_supabase_client())
    except Exception as error:
        category = _category(error)
        report = SchemaReport(False, database_error=category, reason=category)
    print(
        f"schema_ready={str(report.schema_ready).lower()} table_exists={str(report.table_exists).lower()} "
        f"missing_columns={_list(report.missing_columns)} missing_indexes={_list(report.missing_indexes)} "
        f"missing_constraints={_list(report.missing_constraints)} database_error={report.database_error} reason={report.reason}"
    )
    return 0 if report.schema_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
