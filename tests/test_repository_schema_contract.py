"""Regression checks for fields used by inbound-message repositories."""

from pathlib import Path
import re


MIGRATIONS_DIRECTORY = Path(__file__).parents[1] / "supabase" / "migrations"


def _migration_sql() -> str:
    """Read the versioned application schema without connecting to Supabase."""

    return "\n".join(
        migration.read_text(encoding="utf-8")
        for migration in sorted(MIGRATIONS_DIRECTORY.glob("*.sql"))
    )


def _table_definition(sql: str, table_name: str) -> str:
    """Return a table definition, including later alter statements separately."""

    match = re.search(
        rf"create table public\.{table_name} \((.*?)\n\);",
        sql,
        re.DOTALL | re.IGNORECASE,
    )
    assert match is not None, f"Missing {table_name} table migration"
    return match.group(1)


def _assert_columns(
    table_sql: str, table_name: str, columns: set[str], migration_sql: str
) -> None:
    """Assert each repository field is declared or added by a later migration."""

    for column in columns:
        declared_in_table = re.search(
            rf"^\s*{column}\s+", table_sql, re.MULTILINE
        )
        added_later = re.search(
            rf"alter\s+table\s+public\.{table_name}\s+add\s+column\s+"
            rf"(?:if\s+not\s+exists\s+)?{column}\s+",
            migration_sql,
            re.IGNORECASE,
        )
        assert declared_in_table or added_later, column


def test_inbound_repository_fields_exist_in_migrations() -> None:
    """Repository reads and inserts are supported by versioned schema fields."""

    sql = _migration_sql()
    _assert_columns(
        _table_definition(sql, "customers"),
        "customers",
        {"whatsapp_number", "name"},
        sql,
    )
    _assert_columns(
        _table_definition(sql, "conversations"),
        "conversations",
        {"customer_id", "state", "mode", "closed_at"},
        sql,
    )
    _assert_columns(
        _table_definition(sql, "messages"),
        "messages",
        {
            "conversation_id",
            "customer_id",
            "direction",
            "message_type",
            "content",
            "external_provider",
            "external_message_id",
            "received_at",
        },
        sql,
    )
