"""Surface checks against the live spawned MCP server.

These verify that the spawned server actually exposes every read and
write tool we expect over the MCP wire (catching registration regressions
that unit tests on the in-process FastMCP object might miss).
"""

from __future__ import annotations

from .harness import IntegrationConfig, open_harness

READ_TOOLS = {
    "search_endpoints",
    "list_policies",
    "get_policy_assignments",
    "get_policy_restrictions",
    "get_policy_exceptions",
    "get_policy_url_bypass",
    "get_policy_application_bypass_entries",
    "list_custom_categories",
    "get_custom_category_urls",
}

WRITE_TOOLS = {
    "create_policy",
    "assign_policy_principals",
    "unassign_policy_principals",
    "update_policy_restrictions",
    "replace_policy_category_exceptions",
    "upsert_policy_url_bypass",
    "delete_policy_url_bypass_entries",
    "upsert_policy_application_bypass",
    "delete_policy_application_bypass_entries",
    "create_custom_category",
    "add_urls_to_custom_category",
    "delete_single_url_from_custom_category",
}

DESTRUCTIVE_TOOLS = {
    "delete_policy",
    "reset_policy_restrictions_to_base",
    "reset_policy_url_bypass_to_base",
    "reset_policy_application_bypass_to_base",
    "delete_custom_category",
    "delete_all_urls_from_custom_category",
}


async def test_live_server_read_only_surface(
    integration_config: IntegrationConfig,
) -> None:
    async with open_harness(
        integration_config, enable_mutations=False, enable_destructive=False
    ) as mcp:
        names = await mcp.list_tool_names()
        assert names == READ_TOOLS, {
            "missing": sorted(READ_TOOLS - names),
            "extra": sorted(names - READ_TOOLS),
        }


async def test_live_server_mutations_only_surface(
    integration_config: IntegrationConfig,
) -> None:
    async with open_harness(
        integration_config, enable_mutations=True, enable_destructive=False
    ) as mcp:
        names = await mcp.list_tool_names()
        expected = READ_TOOLS | WRITE_TOOLS
        assert names == expected, {
            "missing": sorted(expected - names),
            "extra": sorted(names - expected),
        }


async def test_live_server_full_surface(
    integration_config: IntegrationConfig,
) -> None:
    async with open_harness(
        integration_config, enable_mutations=True, enable_destructive=True
    ) as mcp:
        names = await mcp.list_tool_names()
        expected = READ_TOOLS | WRITE_TOOLS | DESTRUCTIVE_TOOLS
        assert expected.issubset(names), {
            "missing": sorted(expected - names),
            "extra": sorted(names - expected),
        }
