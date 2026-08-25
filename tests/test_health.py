"""Tests for the service health endpoint."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_ok() -> None:
    """The health endpoint reports that the API is available."""

    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_revision"]
    assert payload["router_revision"] == "raipur-router-20260802-1"
    assert payload["started_at"]
    assert payload["process_started_at"] == payload["started_at"]
    assert payload["environment"]
    assert payload["active_conversation_engine"] in {"legacy", "langgraph"}
    assert isinstance(payload["raipur_langgraph_enabled"], bool)
    assert isinstance(payload["raipur_langgraph_comparison_mode"], bool)
    assert isinstance(payload["coimbatore_langgraph_enabled"], bool)
    assert payload["active_coimbatore_engine"] in {"legacy", "langgraph"}
