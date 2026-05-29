"""Tests for the endpoints service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from dopesecurity.mcp_server.schemas import EndpointSearchInput
from dopesecurity.mcp_server.services.endpoints import EndpointsService


class _FakeFlightdeck:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[Mapping[str, Any]] = []

    async def search_endpoints(self, params: Mapping[str, Any]) -> Any:
        self.calls.append(params)
        return self.response


async def test_search_endpoints_service_lists_all() -> None:
    response = {
        "data": {
            "endpoints": [
                {"deviceName": "Mac1", "policyName": "Engineering"},
                {"deviceName": "Mac2", "policyName": "Engineering"},
            ],
            "pageInfo": {"endCursor": "cur", "hasNextPage": True},
        }
    }
    fake = _FakeFlightdeck(response)
    service = EndpointsService(fake)  # type: ignore[arg-type]

    result = await service.search_endpoints(EndpointSearchInput(first=10))

    assert fake.calls == [{"first": 10}]
    assert [e.device_name for e in result.endpoints] == ["Mac1", "Mac2"]
    assert result.page_info.end_cursor == "cur"
    assert result.page_info.has_next_page is True


async def test_search_endpoints_service_maps_query_to_id() -> None:
    fake = _FakeFlightdeck({"data": {"endpoints": [], "pageInfo": {}}})
    service = EndpointsService(fake)  # type: ignore[arg-type]

    await service.search_endpoints(EndpointSearchInput(query="alice"))

    assert fake.calls == [{"id": "alice"}]


async def test_search_endpoints_service_rejects_multiple_filters_before_client_call() -> None:
    fake = _FakeFlightdeck({"data": {"endpoints": [], "pageInfo": {}}})
    service = EndpointsService(fake)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        await service.search_endpoints(
            EndpointSearchInput(query="a", email_id="b@example.com")
        )

    assert fake.calls == []
