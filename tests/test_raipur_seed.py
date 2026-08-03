"""Tests for the safe, placeholder-aware Raipur seed format."""

import json
from pathlib import Path
import sys
from unittest.mock import MagicMock

from app.rag.location_filter import build_location_metadata, is_document_available_for_location
from app.services.raipur_seed import location_database_row, service_database_row, validate_raipur_seed
from scripts import seed_raipur, validate_raipur_seed as validate_script
from scripts import verify_raipur_location as location_verify


ROOT = Path(__file__).resolve().parents[1]


def _location() -> dict[str, object]:
    return {
        "code": "raipur", "name": "Entartica SeaWorld Raipur", "city": "Raipur",
        "state": "Chhattisgarh", "country": "India", "status": "active",
        "booking_enquiry_enabled": True, "requires_human_confirmation": True,
        "requires_human_quotation": True, "address": "TO_BE_APPROVED",
        "contact_reference": "TO_BE_APPROVED", "operating_hours": "TO_BE_APPROVED",
    }


def test_seed_validation_keeps_unapproved_placeholders_visible() -> None:
    result = validate_raipur_seed(_location(), {"location_code": "raipur", "services": []})

    assert result.is_valid
    assert set(result.placeholders) == {"address", "contact_reference", "operating_hours"}
    assert result.service_count == 0


def test_seed_validation_rejects_duplicate_services_and_fake_prices() -> None:
    services = {"location_code": "raipur", "services": [
        {"location_code": "raipur", "code": "snow-park", "name": "Snow Park", "active": True,
         "booking_enquiry_allowed": True, "requires_human_quotation": True, "requires_human_confirmation": True},
        {"location_code": "raipur", "code": "SNOW-PARK", "name": "Other", "active": True,
         "booking_enquiry_allowed": True, "requires_human_quotation": True, "requires_human_confirmation": True,
         "price": "100"},
    ]}

    result = validate_raipur_seed(_location(), services)

    assert "duplicate_service_code" in result.errors
    assert "unapproved_price_field" in result.errors


def test_seed_mapping_is_idempotent_and_preserves_human_requirements() -> None:
    first = location_database_row(_location())
    second = location_database_row(_location())
    service = service_database_row(
        {"code": "snow-park", "name": "Snow Park", "active": True,
         "booking_enquiry_allowed": True, "requires_human_quotation": True,
         "requires_human_confirmation": True},
        "raipur-id",
    )

    assert first == second
    assert first["slug"] == "raipur"
    assert first["metadata"]["requires_human_confirmation"] is True
    assert service["location_id"] == "raipur-id"
    assert service["metadata"]["requires_human_quotation"] is True


def test_seed_mapping_keeps_approved_structured_location_details() -> None:
    row = location_database_row(_location() | {
        "name": "Entartica Sea World Raipur",
        "address": "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh",
        "address_line": "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh",
        "landmark": "Near MAYFAIR Resort",
        "maps_url": "https://maps.app.goo.gl/VtxPyANfMC3rztex8",
    })

    assert row["name"] == "Entartica Sea World Raipur"
    assert row["address"] == "Sector 24, Jhanjh Lake, Atal Nagar, New Raipur, Chhattisgarh"
    assert row["metadata"]["location_name"] == "Entartica Sea World Raipur"
    assert row["metadata"]["landmark"] == "Near MAYFAIR Resort"
    assert row["metadata"]["maps_url"] == "https://maps.app.goo.gl/VtxPyANfMC3rztex8"


def test_seed_execution_is_idempotent_and_never_deletes_or_activates_other_locations(monkeypatch) -> None:
    location_query = MagicMock()
    location_query.upsert.return_value = location_query
    location_query.execute.return_value = MagicMock(data=[{"id": "raipur-id"}])
    client = MagicMock()
    client.table.return_value = location_query
    monkeypatch.setattr(seed_raipur, "get_supabase_client", lambda: client)
    document = {"location_code": "raipur", "services": []}

    assert seed_raipur.seed_raipur(location=_location(), services_document=document) == (1, 0)
    assert seed_raipur.seed_raipur(location=_location(), services_document=document) == (1, 0)
    assert [call.args for call in client.table.call_args_list] == [("locations",), ("locations",)]
    assert location_query.upsert.call_count == 2
    assert not hasattr(location_query, "delete") or location_query.delete.call_count == 0


def test_seed_validator_output_excludes_contact_values(tmp_path, monkeypatch, capsys) -> None:
    location_path = tmp_path / "location.json"
    services_path = tmp_path / "services.json"
    location = _location() | {"contact_reference": "+919000000000"}
    location_path.write_text(json.dumps(location), encoding="utf-8")
    services_path.write_text(json.dumps({"location_code": "raipur", "services": []}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["validate_raipur_seed.py", "--location", str(location_path), "--services", str(services_path)])

    assert validate_script.main() == 0
    assert "+919000000000" not in capsys.readouterr().out


def test_knowledge_retrieval_allows_raipur_and_explicit_global_only() -> None:
    raipur = build_location_metadata(location_code="raipur", location_id="raipur-id", document_category="faq")

    assert is_document_available_for_location(raipur, "raipur")
    assert not is_document_available_for_location({"location_code": "delhi"}, "raipur")
    assert is_document_available_for_location({"location_code": "global", "global_approved": True}, "raipur")
    assert not is_document_available_for_location({"location_code": "global", "global_approved": False}, "raipur")


class _LocationResponse:
    def __init__(self, data): self.data=data
class _LocationQuery:
    def __init__(self, data): self.data=data
    def select(self,*_args): return self
    def eq(self,*_args): return self
    def execute(self): return _LocationResponse(self.data)
class _LocationClient:
    def __init__(self, locations, services=()): self.locations=locations;self.services=services
    def table(self,name): return _LocationQuery(self.locations if name=="locations" else self.services)


def test_raipur_location_verifier_handles_missing_active_inactive_duplicate_and_conflict() -> None:
    missing=location_verify.inspect_raipur_location(_LocationClient([]))
    assert missing["reason"]=="raipur_location_missing"
    active={"id":"r","slug":"raipur","name":"Entartica Sea World Raipur","city":"Raipur","state":"Chhattisgarh","is_active":True}
    ready=location_verify.inspect_raipur_location(_LocationClient([active],[{"id":"s"}]))
    assert ready["reason"]=="ready" and ready["related_services_count"]==1
    inactive=location_verify.inspect_raipur_location(_LocationClient([active|{"is_active":False}]))
    assert inactive["reason"]=="raipur_location_inactive"
    duplicate=location_verify.inspect_raipur_location(_LocationClient([active,active|{"id":"r2"}]))
    assert duplicate["reason"]=="duplicate_raipur_locations_require_review"
    conflict=location_verify.inspect_raipur_location(_LocationClient([active|{"name":"Other"}]))
    assert conflict["reason"]=="existing_raipur_location_conflict"


def test_raipur_seed_migration_is_raipur_only_idempotent_and_does_not_touch_customer_data() -> None:
    sql=(ROOT/"supabase/migrations/202607200009_seed_raipur_location.sql").read_text(encoding="utf-8").casefold()
    executable="\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert "on conflict (slug) do update" in sql and "set is_active = true" in sql
    assert "delete" not in executable and "booking_enquiries" not in executable and "customers" not in executable and "services" not in executable
