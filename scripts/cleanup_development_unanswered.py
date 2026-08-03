"""Delete only explicitly marked development retrieval records after confirmation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.supabase import get_supabase_client


def _count(response: object) -> int:
    data = getattr(response, "data", None) if response is not None else None
    return len(data) if isinstance(data, list) else int(isinstance(data, dict))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Delete development retrieval test records only.")
    args = parser.parse_args()
    if not args.confirm:
        print("cleanup_refused confirmation_required=true")
        return 2
    try:
        response = (
            get_supabase_client()
            .table("unanswered_questions")
            .delete()
            .eq("record_origin", "development_retrieval_test")
            .execute()
        )
    except Exception as error:
        print(f"cleanup_failed error_class={type(error).__name__}")
        return 1
    print(f"cleanup_complete deleted_development_records={_count(response)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
