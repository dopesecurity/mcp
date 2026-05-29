"""Tests for policy MCP tool registration."""

from __future__ import annotations

from pydantic import SecretStr

from dopesecurity.mcp_server.config import DEFAULT_BASE_URL, Settings
from dopesecurity.mcp_server.server import create_server

READ_TOOLS = {
    "list_policies",
    "get_policy_assignments",
    "get_policy_restrictions",
    "get_policy_exceptions",
    "get_policy_url_bypass",
    "get_policy_application_bypass_entries",
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
}

DESTRUCTIVE_TOOLS = {
    "delete_policy",
    "reset_policy_restrictions_to_base",
    "reset_policy_url_bypass_to_base",
    "reset_policy_application_bypass_to_base",
}


def _settings(
    *, enable_mutations: bool = False, enable_destructive: bool = False
) -> Settings:
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


def _tool_names(server: object, *, with_descriptions: bool = False) -> dict[str, str]:
    tools = server._tool_manager.list_tools()  # type: ignore[attr-defined]
    if with_descriptions:
        return {t.name: (t.description or "") for t in tools}
    return {t.name: "" for t in tools}


def test_policy_read_tools_registered_when_mutations_disabled() -> None:
    server = create_server(_settings(enable_mutations=False))
    names = set(_tool_names(server))
    assert READ_TOOLS.issubset(names)


def test_policy_write_and_destructive_tools_absent_when_mutations_disabled() -> None:
    server = create_server(_settings(enable_mutations=False))
    names = set(_tool_names(server))
    assert WRITE_TOOLS.isdisjoint(names)
    assert DESTRUCTIVE_TOOLS.isdisjoint(names)


def test_policy_write_tools_present_when_mutations_enabled() -> None:
    server = create_server(_settings(enable_mutations=True))
    names = set(_tool_names(server))
    assert WRITE_TOOLS.issubset(names)


def test_policy_destructive_tools_absent_when_only_mutations_enabled() -> None:
    server = create_server(_settings(enable_mutations=True))
    names = set(_tool_names(server))
    assert DESTRUCTIVE_TOOLS.isdisjoint(names)


def test_policy_destructive_tools_present_when_both_enabled() -> None:
    server = create_server(
        _settings(enable_mutations=True, enable_destructive=True)
    )
    names = set(_tool_names(server))
    assert DESTRUCTIVE_TOOLS.issubset(names)


def test_mutating_policy_descriptions_warn_about_tenant_state() -> None:
    server = create_server(
        _settings(enable_mutations=True, enable_destructive=True)
    )
    descriptions = _tool_names(server, with_descriptions=True)
    for name in WRITE_TOOLS | DESTRUCTIVE_TOOLS:
        assert "tenant state" in descriptions[name].lower(), (
            f"{name} description should mention tenant state"
        )


def test_replace_exceptions_description_mentions_per_category_replacement() -> None:
    server = create_server(_settings(enable_mutations=True))
    descriptions = _tool_names(server, with_descriptions=True)
    desc = descriptions["replace_policy_category_exceptions"].lower()
    assert "per-category" in desc or "per category" in desc


def test_url_bypass_descriptions_explain_custom_and_default() -> None:
    server = create_server(_settings(enable_mutations=True))
    descriptions = _tool_names(server, with_descriptions=True)
    for name in ("get_policy_url_bypass", "upsert_policy_url_bypass"):
        desc = descriptions[name].lower()
        assert "custom" in desc and "default" in desc, (
            f"{name} description should explain custom vs default entries"
        )
