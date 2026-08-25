"""Offline safety audit for manifest-eligible Raipur celebration Markdown."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from app.rag.raipur_ingestion import build_plan

BANNED = ("completely safe", "100% safe", "no risk", "guaranteed safe", "no age restriction", "unsinkable", "shock-free", "booking is confirmed", "payment is confirmed")


def main() -> int:
    plan, errors = build_plan(ROOT)
    documents = [row.document for row in plan if row.document is not None and row.document.metadata.get("knowledge_type") == "celebration"]
    combined = "\n".join(document.text.casefold() for document in documents)
    has_party = any(document.metadata.get("service_code") == "party_boat_celebration" for document in documents)
    duration_ok = ("starting duration: 2 hours" in combined and "starting duration: 30 minutes" in combined) if has_party else False
    lake_ok = "jhanjh lake" in combined if documents else False
    handover_ok = all("price" not in document.text.casefold() or any(term in document.text.casefold() for term in ("verify", "team", "handover", "assist")) for document in documents)
    print(f"mode=offline_celebration_audit approved_documents={len(documents)} party_boat_metadata_present={str(has_party).lower()} party_boat_duration_present={str(duration_ok).lower()} jhanjh_lake_present={str(lake_ok).lower()} pricing_availability_handover_wording={str(handover_ok).lower()} banned_phrase_count={sum(phrase in combined for phrase in BANNED)} validation_errors={len(errors)}")
    return 1 if errors or any(phrase in combined for phrase in BANNED) else 0


if __name__ == "__main__": raise SystemExit(main())
