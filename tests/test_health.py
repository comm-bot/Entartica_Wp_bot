"""Tests for the service health endpoint."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_ok() -> None:
    """The health endpoint reports that the API is available."""

    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
