"""Mocked tests for service data access."""

from unittest.mock import MagicMock

from app.repositories.services import ServiceRepository


def test_list_active_services_for_location_excludes_inactive_records() -> None:
    """Service queries scope results to a location and active records."""

    response = MagicMock(data=[{"id": "service-1", "name": "Active service"}])
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.execute.return_value = response
    client = MagicMock()
    client.table.return_value = query

    services = ServiceRepository(client).list_active_for_location("location-1")

    assert services == response.data
    client.table.assert_called_once_with("services")
    assert query.eq.call_args_list[0].args == ("location_id", "location-1")
    assert query.eq.call_args_list[1].args == ("is_active", True)
    query.order.assert_called_once_with("name")
