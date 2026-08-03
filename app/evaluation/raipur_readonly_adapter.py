"""Narrow, read-only Supabase surface for explicit local evaluations."""
from __future__ import annotations

from typing import Any

from app.rag.retrieval import retrieve_candidates
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, knowledge_service_code


class ReadOnlyEvaluationViolation(RuntimeError):
    pass


class RaipurReadOnlyAdapter:
    """Expose only approved knowledge/location/service reads; client stays private."""
    def __init__(self, client: Any) -> None:
        self.__client = client
        self.database_write_attempts = 0

    def resolve_raipur_location(self) -> dict[str, Any] | None:
        data = self.__client.table("locations").select("id,code,name,address_line,landmark,maps_url").eq("code", "raipur").eq("is_active", True).maybe_single().execute().data
        return data if isinstance(data, dict) else None

    def list_active_services(self, location_id: str) -> list[dict[str, Any]]:
        data = self.__client.table("services").select("id,name,slug,location_id,is_active").eq("location_id", location_id).eq("is_active", True).execute().data
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def get_service_by_code(self, service_code: str) -> dict[str, Any] | None:
        approved = next((item for item in APPROVED_RAIPUR_SERVICES if knowledge_service_code(item) == service_code), None)
        return {"service_code": service_code, "name": approved.name, "slug": approved.slug} if approved else None

    def read_approved_knowledge_documents(self) -> list[dict[str, Any]]:
        data = self.__client.table("knowledge_documents").select("id,source_file,metadata").eq("is_active", True).execute().data
        return [row for row in data if isinstance(row, dict) and isinstance(row.get("metadata"), dict) and row["metadata"].get("location_code") == "raipur" and row["metadata"].get("approval_status") == "approved" and row["metadata"].get("customer_facing") is True]

    def retrieve_service_knowledge(self, embedding: list[float], service_code: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = retrieve_candidates(self.__client, embedding, limit=limit)
        return [row for row in rows if isinstance(row.get("metadata"), dict) and row["metadata"].get("service_code") == service_code and row["metadata"].get("catalogue_status") == "active" and row["metadata"].get("customer_facing") is True]

    def retrieve_venue_knowledge(self, embedding: list[float], *, limit: int = 20) -> list[dict[str, Any]]:
        return retrieve_candidates(self.__client, embedding, limit=limit)

    def __getattr__(self, name: str) -> Any:
        if any(token in name.casefold() for token in ("insert", "update", "delete", "upsert", "create", "save", "persist", "write", "rpc")):
            self.database_write_attempts += 1
            raise ReadOnlyEvaluationViolation("forbidden_write_operation")
        raise AttributeError(name)
