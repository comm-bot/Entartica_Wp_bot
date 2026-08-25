"""Validate Chiki sales fine-tuning data without external calls."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.evaluation.chiki_fine_tuning import validate_dataset

ROOT = Path(__file__).resolve().parents[1] / "data" / "fine_tuning" / "chiki_sales_v1"

if __name__ == "__main__":
    result = validate_dataset(ROOT)
    print(f"valid={result.valid} examples={result.example_count}")
    for error in result.errors:
        print(error)
    raise SystemExit(0 if result.valid else 1)
