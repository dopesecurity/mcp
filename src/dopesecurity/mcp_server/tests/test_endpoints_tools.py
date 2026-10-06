"""Tests for the endpoint MCP tool registration."""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import SecretStr

from dopesecurity.mcp_server.config import DEFAULT_BASE_URL, Settings
from dopesecurity.mcp_server.server import create_server


def _settings() -> Settings:
    return Settings.model_construct(
        _fields_set=None,
        client_id="test-client",
        client_secret=SecretStr("test-secret"),
        enable_mutations=False,
        timeout_seconds=30.0,
        log_level="INFO",
        token_refresh_skew_seconds=60.0,
        api_base_url=DEFAULT_BASE_URL,
    )


def _tool_names(server: object) -> list[str]:
    tools = server._tool_manager.list_tools()  # type: ignore[attr-defined]
    return [t.name for t in tools]


def test_search_endpoints_tool_registered_in_read_only_mode() -> None:
    server = create_server(_settings())
    assert "search_endpoints" in _tool_names(server)


def test_search_endpoints_tool_description_mentions_zero_or_one_filter() -> None:
    server = create_server(_settings())
    tools = server._tool_manager.list_tools()
    tool = next(t for t in tools if t.name == "search_endpoints")
    assert tool.description is not None
    assert "one" in tool.description.lower()
    assert "search" in tool.description.lower() or "filter" in tool.description.lower()


async def test_search_endpoints_multiple_filters_error_reaches_caller() -> None:
    server = create_server(_settings())

    with pytest.raises(ToolError, match="at most one"):
        await server.call_tool("search_endpoints", {"query": "x", "device_name": "y"})
