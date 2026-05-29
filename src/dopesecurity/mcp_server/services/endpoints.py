"""Endpoint service backed by the Flightdeck API."""

from __future__ import annotations

from collections.abc import Mapping

from dopesecurity.mcp_server.flightdeck.client import FlightdeckClient
from dopesecurity.mcp_server.schemas import (
    EndpointItem,
    EndpointSearchInput,
    PageInfo,
    SearchEndpointsResult,
    endpoint_search_params,
    strip_data,
)


class EndpointsService:
    def __init__(self, flightdeck: FlightdeckClient) -> None:
        self._flightdeck = flightdeck

    async def search_endpoints(
        self, input: EndpointSearchInput
    ) -> SearchEndpointsResult:
        params = endpoint_search_params(input)
        payload = await self._flightdeck.search_endpoints(params)

        if not isinstance(payload, Mapping):
            return SearchEndpointsResult()
        data = strip_data(payload)
        endpoints_raw = data.get("endpoints", []) if isinstance(data, Mapping) else []
        page_info_raw = data.get("pageInfo", {}) if isinstance(data, Mapping) else {}

        endpoints = [
            EndpointItem.model_validate(item)
            for item in (endpoints_raw or [])
        ]
        page_info = (
            PageInfo.model_validate(page_info_raw)
            if isinstance(page_info_raw, Mapping)
            else PageInfo()
        )
        return SearchEndpointsResult(endpoints=endpoints, page_info=page_info)
