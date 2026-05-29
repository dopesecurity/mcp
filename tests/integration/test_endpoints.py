"""Integration scenarios for endpoint tools."""

from __future__ import annotations

import pytest

from .harness import IntegrationConfig, ToolError, integration


async def test_search_endpoints_basic_listing(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, _cleaner):
        page = await mcp.call("search_endpoints", {})
        assert "endpoints" in page
        assert "page_info" in page
        assert isinstance(page["endpoints"], list)


async def test_search_endpoints_with_first(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, _cleaner):
        page = await mcp.call("search_endpoints", {"first": 1})
        assert isinstance(page["endpoints"], list)
        assert len(page["endpoints"]) <= 1


async def test_search_endpoints_rejects_multiple_filters(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, _cleaner):
        with pytest.raises(ToolError) as exc_info:
            await mcp.call(
                "search_endpoints",
                {"query": "x", "device_name": "y"},
            )
        msg = str(exc_info.value).lower()
        assert "at most one" in msg or "one of" in msg
