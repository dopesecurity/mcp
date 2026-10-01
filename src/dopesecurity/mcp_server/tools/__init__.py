"""MCP tool registration helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context

    from dopesecurity.mcp_server.server import AppContext


def get_app_context(ctx: Context) -> AppContext:
    """Retrieve the typed lifespan-managed AppContext from an MCPServer Context."""

    return cast("AppContext", ctx.request_context.lifespan_context)
