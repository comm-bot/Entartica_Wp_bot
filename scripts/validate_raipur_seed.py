"""Validate Raipur seed files without disclosing contact or placeholder values."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.raipur_seed import load_seed_json, validate_raipur_seed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--location", type=Path, default=ROOT / "data/seed/raipur_location.example.json")
    parser.add_argument("--services", type=Path, default=ROOT / "data/seed/raipur_services.example.json")
    args = parser.parse_args()
    try:
        result = validate_raipur_seed(load_seed_json(args.location), load_seed_json(args.services))
    except (OSError, ValueError) as error:
        print(f"seed_validation_failed error_class={type(error).__name__}")
        return 1
    print(f"seed_validation valid={result.is_valid} service_count={result.service_count} placeholder_fields={len(result.placeholders)} error_count={len(result.errors)}")
    if result.errors:
        print("seed_validation_errors=" + ",".join(result.errors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
