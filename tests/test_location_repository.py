"""Mocked tests for location data access."""

from unittest.mock import MagicMock

from app.repositories.locations import LocationRepository


def test_list_active_locations_excludes_inactive_records() -> None:
    """Active-location queries filter inactive records at the database."""

    response = MagicMock(data=[{"id": "location-1", "name": "Active location"}])
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.execute.return_value = response
    client = MagicMock()
    client.table.return_value = query

    locations = LocationRepository(client).list_active()

    assert locations == response.data
    client.table.assert_called_once_with("locations")
    query.eq.assert_called_once_with("is_active", True)
    query.order.assert_called_once_with("name")


def test_get_active_location_returns_one_location() -> None:
    """A single-location query includes both identifier and active filters."""

    response = MagicMock(data={"id": "location-1", "name": "Active location"})
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.maybe_single.return_value = query
    query.execute.return_value = response
    client = MagicMock()
    client.table.return_value = query

    location = LocationRepository(client).get_active("location-1")

    assert location == response.data
    assert query.eq.call_args_list[0].args == ("id", "location-1")
    assert query.eq.call_args_list[1].args == ("is_active", True)
