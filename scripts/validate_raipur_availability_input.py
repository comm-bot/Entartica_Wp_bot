from __future__ import annotations
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.services.raipur_availability_input import validate
def main()->int:
 parser=argparse.ArgumentParser();parser.add_argument("--file",type=Path,required=True);parser.add_argument("--allow-past-correction",action="store_true");args=parser.parse_args();report=validate(args.file,allow_past=args.allow_past_correction,max_age_minutes=Settings().availability_max_age_minutes);print(" ".join([f"file_valid={str(report.file_valid).lower()}"]+[f"{k}={v}" for k,v in report.metrics.items()]+[f"reason={report.reason}"]));return 0 if report.file_valid else 1
if __name__=="__main__":raise SystemExit(main())
