from datetime import datetime, timezone
from pathlib import Path
from app.services.raipur_availability_input import checksum, validate
from scripts.import_raipur_availability import approval_valid
ROOT=Path(__file__).resolve().parents[1]
def test_synthetic_approved_rows_validate_and_bad_rows_are_rejected(tmp_path):
 fixture=ROOT/"tests/fixtures/raipur_availability_synthetic.csv";report=validate(fixture,now=datetime(2098,1,1,tzinfo=timezone.utc));assert report.file_valid and report.metrics["valid_rows"]==6
 bad=tmp_path/"bad.csv";bad.write_text("service_name,availability_date,start_time,end_time,total_capacity,available_capacity,operational_status,verified_at,data_owner,internal_note\nUnknown,2000-01-01,11:00,10:00,-1,3,available,not-a-time,,price\n")
 report=validate(bad,now=datetime(2026,1,1,tzinfo=timezone.utc));assert not report.file_valid and report.metrics["unknown_services"]==1 and report.metrics["invalid_rows"]==1
def test_approval_gate_requires_approved_matching_checksum(tmp_path):
 source=tmp_path/"source.csv";source.write_text("x",encoding="utf-8");approval=tmp_path/"approval.md";approval.write_text(f"Approval status: APPROVED\nSource CSV filename: {source.name}\nSource CSV checksum (SHA-256): {checksum(source)}",encoding="utf-8");assert approval_valid(approval,source)
