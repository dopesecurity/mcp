"""Integration scenarios for custom-category tools (read + write)."""

from __future__ import annotations

import pytest

from .harness import IntegrationConfig, ToolError, integration, make_tag


async def test_custom_category_full_lifecycle(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, cleaner):
        name = make_tag("cat")
        await mcp.call("create_custom_category", {"custom_category_name": name})
        cleaner.track_custom_category(name)

        names = await mcp.list_all_custom_category_names()
        assert name in names

        urls = ["example.com", "foo.example.com", "bar.example.com"]
        await mcp.call(
            "add_urls_to_custom_category",
            {"custom_category_name": name, "urls": urls},
        )
        listed = await mcp.call(
            "get_custom_category_urls", {"custom_category_name": name}
        )
        assert set(urls).issubset(set(listed["urls"]))

        await mcp.call(
            "delete_single_url_from_custom_category",
            {"custom_category_name": name, "url": urls[0]},
        )
        after_single = await mcp.call(
            "get_custom_category_urls", {"custom_category_name": name}
        )
        assert urls[0] not in after_single["urls"]
        assert urls[1] in after_single["urls"]

        await mcp.call(
            "delete_all_urls_from_custom_category", {"custom_category_name": name}
        )
        cleared = await mcp.call(
            "get_custom_category_urls", {"custom_category_name": name}
        )
        assert cleared["urls"] == []

        await mcp.call("delete_custom_category", {"custom_category_name": name})
        cleaner.custom_categories.remove(name)
        names = await mcp.list_all_custom_category_names()
        assert name not in names


async def test_delete_unknown_custom_category_errors(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, _cleaner):
        bogus = make_tag("nope")
        with pytest.raises(ToolError):
            await mcp.call("delete_custom_category", {"custom_category_name": bogus})
