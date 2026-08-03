"""Tests for the data-driven Raipur-only MVP location scope."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.repositories.locations import LocationRepository
from app.repositories.services import ServiceRepository
from app.services.location_scope import LocationScopeService


def _settings(monkeypatch, *, default: str = "raipur", enabled: str = "raipur") -> Settings:
    monkeypatch.setenv("MVP_DEFAULT_LOCATION_CODE", default)
    monkeypatch.setenv("MVP_ENABLED_LOCATION_CODES", enabled)
    return Settings()


def test_raipur_is_the_normalized_enabled_default(monkeypatch) -> None:
    settings = _settings(monkeypatch, default=" RAIPUR ", enabled=" RAIPUR, raipur ")

    assert settings.mvp_default_location_code == "raipur"
    assert settings.mvp_enabled_location_codes == ("raipur",)
    assert settings.mvp_location_configuration_is_valid()


def test_empty_or_missing_location_scope_fails_safely(monkeypatch) -> None:
    settings = _settings(monkeypatch, default="", enabled="")
    repository = MagicMock()

    result = LocationScopeService(settings, repository).get_default_location()

    assert result.status == "location_not_configured"
    repository.get_default_enabled_location.assert_not_called()


def test_another_location_is_rejected_for_human_handover(monkeypatch) -> None:
    settings = _settings(monkeypatch)
    repository = MagicMock()
    repository.get_default_enabled_location.return_value = {"id": "raipur-id", "name": "Entartica SeaWorld Raipur"}

    result = LocationScopeService(settings, repository).resolve_requested_location("Delhi")

    assert result.status == "unsupported_location"
    assert result.requested_location == "delhi"
    assert result.available_location == "Entartica SeaWorld Raipur"
    assert result.human_handover_required is True
    repository.get_location_by_code.assert_not_called()


def test_booking_enquiry_requires_enabled_raipur_location_id(monkeypatch) -> None:
    repository = MagicMock()
    repository.ensure_location_is_enabled.return_value = {"id": "raipur-id"}
    service = LocationScopeService(_settings(monkeypatch), repository)

    assert service.require_enabled_location_id("raipur-id") == "raipur-id"
    with pytest.raises(ValueError):
        service.require_enabled_location_id(None)
    repository.ensure_location_is_enabled.return_value = None
    with pytest.raises(ValueError):
        service.require_enabled_location_id("other-location-id")


def test_location_repository_handles_none_list_and_dict_responses() -> None:
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.in_.return_value = query
    query.order.return_value = query
    query.maybe_single.return_value = query
    client = MagicMock()
    client.table.return_value = query
    repository = LocationRepository(client, default_location_code="raipur", enabled_location_codes=("raipur",))

    query.execute.return_value = None
    assert repository.list_enabled_locations() == []
    query.execute.return_value = SimpleNamespace(data={"id": "raipur-id", "slug": "raipur"})
    assert repository.get_default_enabled_location() == {"id": "raipur-id", "slug": "raipur"}
    query.execute.return_value = SimpleNamespace(data=[{"id": "raipur-id"}])
    assert repository.ensure_location_is_enabled("raipur-id") == {"id": "raipur-id"}


def test_services_repository_returns_only_active_location_rows_for_dict_or_none() -> None:
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    client = MagicMock()
    client.table.return_value = query
    repository = ServiceRepository(client)

    query.execute.return_value = SimpleNamespace(data={"id": "service-1", "location_id": "raipur-id"})
    assert repository.list_active_for_location("raipur-id") == [{"id": "service-1", "location_id": "raipur-id"}]
    query.execute.return_value = None
    assert repository.list_active_for_location("raipur-id") == []
