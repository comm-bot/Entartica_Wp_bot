"""Validation for management-supplied Raipur availability CSVs; no database access."""
from __future__ import annotations
import csv, hashlib, re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, normalize_service_text

FIELDS=("service_name","availability_date","start_time","end_time","total_capacity","available_capacity","operational_status","verified_at","data_owner","internal_note")
STATUSES={"available","limited","full","closed","weather_hold","maintenance","verification_required"}
FORBIDDEN=("price","payment","customer","phone","booking confirmation")
@dataclass(frozen=True)
class InputReport:
 rows:list[dict[str,str]]; metrics:dict[str,int]; file_valid:bool; reason:str
def checksum(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def validate(path:Path,*,now:datetime|None=None,allow_past:bool=False,max_age_minutes:int=30)->InputReport:
 metrics={k:0 for k in ("row_count","valid_rows","invalid_rows","duplicate_rows","unknown_services","invalid_dates","invalid_times","invalid_capacities","invalid_statuses","stale_rows")};now=now or datetime.now(timezone.utc)
 try:
  raw=[line for line in path.read_text(encoding="utf-8-sig").splitlines() if not line.lstrip().startswith("#")]
  reader=csv.DictReader(raw); columns=tuple(reader.fieldnames or ())
 except (OSError,csv.Error):return InputReport([],metrics,False,"file_unreadable")
 if not raw:return InputReport([],metrics,False,"empty_file")
 if set(columns)!=set(FIELDS):return InputReport([],metrics,False,"missing_or_unknown_columns")
 rows=[];seen=set();approved={normalize_service_text(x.name) for x in APPROVED_RAIPUR_SERVICES}
 for row in reader:
  metrics["row_count"]+=1;valid=True; joined=" ".join(row.values()).casefold()
  if any(word in joined for word in FORBIDDEN):valid=False
  service=normalize_service_text(row.get("service_name"));
  if service not in approved:metrics["unknown_services"]+=1;valid=False
  try:d=date.fromisoformat(row["availability_date"]);past=d<now.date()
  except ValueError:metrics["invalid_dates"]+=1;valid=False;past=False
  try:start=datetime.strptime(row["start_time"],"%H:%M").time();end=datetime.strptime(row["end_time"],"%H:%M"); valid=valid and end.time()>start
  except ValueError:metrics["invalid_times"]+=1;valid=False
  try:total=int(row["total_capacity"]);available=int(row["available_capacity"]);valid=valid and total>=0 and 0<=available<=total
  except ValueError:metrics["invalid_capacities"]+=1;valid=False;total=available=0
  status=row.get("operational_status");
  if status not in STATUSES or (status in {"available","limited"} and available<=0) or (status=="full" and available!=0):metrics["invalid_statuses"]+=1;valid=False
  try:verified=datetime.fromisoformat(row["verified_at"].replace("Z","+00:00"));verified=verified if verified.tzinfo else verified.replace(tzinfo=timezone.utc);stale=now-verified>timedelta(minutes=max_age_minutes)
  except ValueError:stale=True;valid=False
  if stale:metrics["stale_rows"]+=1;valid=False
  if past and not allow_past:metrics["invalid_dates"]+=1;valid=False
  if not row.get("data_owner","").strip():valid=False
  key=(service,row.get("availability_date"),row.get("start_time"),row.get("end_time"))
  if key in seen:metrics["duplicate_rows"]+=1;valid=False
  seen.add(key)
  if valid:metrics["valid_rows"]+=1;rows.append(row)
  else:metrics["invalid_rows"]+=1
 return InputReport(rows,metrics,metrics["invalid_rows"]==0,"ready" if metrics["invalid_rows"]==0 else "validation_failed")
