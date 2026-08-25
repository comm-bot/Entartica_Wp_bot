"""Run the one authorized Chiki FT-2B SFT job and persist its evaluation metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings


ROOT = Path(__file__).resolve().parents[1] / "data" / "fine_tuning" / "chiki_sales_v1"
REPORT_PATH = ROOT / "ft2b_experiment.json"
BASE_MODEL = "gpt-4.1-mini-2025-04-14"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save(report: dict[str, object]) -> None:
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-one-paid-sft-job", action="store_true")
    args = parser.parse_args()
    if not args.allow_one_paid_sft_job:
        raise SystemExit("Refusing upload/job creation without --allow-one-paid-sft-job.")
    if REPORT_PATH.exists():
        existing = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        if existing.get("job_id") or existing.get("training_file_id"):
            raise SystemExit("FT-2B already started; refusing a duplicate upload or job.")

    settings = Settings(chiki_sales_fine_tuned_enabled=False)
    if settings.chiki_sales_fine_tuned_enabled:
        raise SystemExit("Production fine-tuned model must remain disabled.")
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required.")

    train_path = ROOT / "train.jsonl"
    validation_path = ROOT / "validation.jsonl"
    holdout_path = ROOT / "holdout.jsonl"
    report: dict[str, object] = {
        "base_model": BASE_MODEL,
        "suffix": "chiki-sales-v1",
        "production_model_changed": False,
        "production_ft_enabled": False,
        "holdout_uploaded": False,
        "holdout_sha256": _sha256(holdout_path),
        "train_sha256": _sha256(train_path),
        "validation_sha256": _sha256(validation_path),
        "hyperparameters": "platform defaults",
    }
    _save(report)
    client = OpenAI(api_key=settings.openai_api_key.get_secret_value())

    with train_path.open("rb") as source:
        training_file = client.files.create(file=source, purpose="fine-tune")
    report["training_file_id"] = training_file.id
    _save(report)
    print(f"TRAINING_FILE_UPLOADED={training_file.id}", flush=True)

    with validation_path.open("rb") as source:
        validation_file = client.files.create(file=source, purpose="fine-tune")
    report["validation_file_id"] = validation_file.id
    _save(report)
    print(f"VALIDATION_FILE_UPLOADED={validation_file.id}", flush=True)

    job = client.fine_tuning.jobs.create(
        model=BASE_MODEL,
        training_file=training_file.id,
        validation_file=validation_file.id,
        suffix="chiki-sales-v1",
    )
    report.update({
        "job_id": job.id,
        "created_at": job.created_at,
        "status": job.status,
    })
    _save(report)
    print(f"JOB_CREATED={job.id} STATUS={job.status}", flush=True)

    while job.status not in {"succeeded", "failed", "cancelled"}:
        time.sleep(30)
        job = client.fine_tuning.jobs.retrieve(job.id)
        report.update({"status": job.status, "fine_tuned_model": job.fine_tuned_model})
        _save(report)
        print(f"JOB_STATUS={job.status}", flush=True)

    report.update({
        "status": job.status,
        "finished_at": job.finished_at,
        "fine_tuned_model": job.fine_tuned_model,
        "trained_tokens": job.trained_tokens,
        "result_files": list(job.result_files or []),
        "error": job.error.model_dump() if job.error else None,
    })
    _save(report)
    print(f"FINAL_STATUS={job.status}", flush=True)

    if job.result_files:
        content = client.files.content(job.result_files[0])
        metrics_path = ROOT / "ft2b_result_metrics.csv"
        metrics_path.write_bytes(content.read())
        print(f"METRICS_SAVED={metrics_path.name}", flush=True)


if __name__ == "__main__":
    main()
