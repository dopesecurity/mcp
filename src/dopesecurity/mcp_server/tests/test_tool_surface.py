"""End-to-end test for the approved v1 MCP tool surface."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from dopesecurity.mcp_server.config import DEFAULT_BASE_URL, Settings
from dopesecurity.mcp_server.server import create_server

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

# Non-destructive write tools: create/update/upsert/assign/per-entry-delete.
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

# Destructive tools: drop or wipe whole policies/categories or whole sections.
DESTRUCTIVE_TOOLS = {
    "delete_policy",
    "reset_policy_restrictions_to_base",
    "reset_policy_url_bypass_to_base",
    "reset_policy_application_bypass_to_base",
    "delete_custom_category",
    "delete_all_urls_from_custom_category",
}


def _settings(*, enable_mutations: bool, enable_destructive: bool = False) -> Settings:
    return Settings.model_construct(
        _fields_set=None,
        client_id="test-client",
        client_secret=SecretStr("test-secret"),
        enable_mutations=enable_mutations,
        enable_destructive=enable_destructive,
        timeout_seconds=30.0,
        log_level="INFO",
        token_refresh_skew_seconds=60.0,
        api_base_url=DEFAULT_BASE_URL,
    )


def _registered_tools(
    *, enable_mutations: bool, enable_destructive: bool = False
) -> set[str]:
    server = create_server(
        _settings(
            enable_mutations=enable_mutations,
            enable_destructive=enable_destructive,
        )
    )
    return {t.name for t in server._tool_manager.list_tools()}


def _tool_descriptions(
    *, enable_mutations: bool, enable_destructive: bool = False
) -> dict[str, str]:
    server = create_server(
        _settings(
            enable_mutations=enable_mutations,
            enable_destructive=enable_destructive,
        )
    )
    return {t.name: (t.description or "") for t in server._tool_manager.list_tools()}


def test_read_only_tool_surface_exact() -> None:
    assert _registered_tools(enable_mutations=False) == READ_TOOLS


def test_mutation_enabled_tool_surface_exact() -> None:
    # mutations on, destructive off — non-destructive writes added, but no
    # whole-policy / whole-category drops.
    assert _registered_tools(enable_mutations=True) == READ_TOOLS | WRITE_TOOLS


def test_full_surface_when_destructive_enabled() -> None:
    assert (
        _registered_tools(enable_mutations=True, enable_destructive=True)
        == READ_TOOLS | WRITE_TOOLS | DESTRUCTIVE_TOOLS
    )


def test_destructive_without_mutations_errors_at_startup() -> None:
    with pytest.raises(ValueError, match="destructive"):
        create_server(_settings(enable_mutations=False, enable_destructive=True))


def test_destructive_tools_request_confirmation_in_description() -> None:
    descriptions = _tool_descriptions(enable_mutations=True, enable_destructive=True)
    for name in DESTRUCTIVE_TOOLS:
        assert "confirm the exact target with the user" in descriptions[name], name
