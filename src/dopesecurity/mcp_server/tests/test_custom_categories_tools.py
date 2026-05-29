"""Tests for custom-category MCP tool registration."""

from __future__ import annotations

from pydantic import SecretStr

from dopesecurity.mcp_server.config import DEFAULT_BASE_URL, Settings
from dopesecurity.mcp_server.server import create_server

READ_TOOLS = {"list_custom_categories", "get_custom_category_urls"}
WRITE_TOOLS = {
    "create_custom_category",
    "add_urls_to_custom_category",
    "delete_single_url_from_custom_category",
}
DESTRUCTIVE_TOOLS = {
    "delete_custom_category",
    "delete_all_urls_from_custom_category",
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


def _tool_names(server: object) -> set[str]:
    tools = server._tool_manager.list_tools()  # type: ignore[attr-defined]
    return {t.name for t in tools}


def test_custom_category_read_tools_registered_when_mutations_disabled() -> None:
    server = create_server(_settings(enable_mutations=False))
    names = _tool_names(server)
    assert READ_TOOLS.issubset(names)


def test_custom_category_write_and_destructive_tools_absent_when_mutations_disabled() -> None:
    server = create_server(_settings(enable_mutations=False))
    names = _tool_names(server)
    assert WRITE_TOOLS.isdisjoint(names)
    assert DESTRUCTIVE_TOOLS.isdisjoint(names)


def test_custom_category_write_tools_present_when_mutations_enabled() -> None:
    server = create_server(_settings(enable_mutations=True))
    assert WRITE_TOOLS.issubset(_tool_names(server))


def test_custom_category_destructive_tools_absent_when_only_mutations_enabled() -> None:
    server = create_server(_settings(enable_mutations=True))
    assert DESTRUCTIVE_TOOLS.isdisjoint(_tool_names(server))


def test_custom_category_destructive_tools_present_when_both_enabled() -> None:
    server = create_server(
        _settings(enable_mutations=True, enable_destructive=True)
    )
    assert DESTRUCTIVE_TOOLS.issubset(_tool_names(server))
