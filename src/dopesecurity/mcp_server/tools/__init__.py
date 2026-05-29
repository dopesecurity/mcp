"""MCP tool registration helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

    from dopesecurity.mcp_server.server import AppContext


def get_app_context(ctx: Context[Any, Any, Any]) -> AppContext:
    """Retrieve the typed lifespan-managed AppContext from a FastMCP Context."""

    lifespan_context = ctx.request_context.lifespan_context
    return lifespan_context  # type: ignore[no-any-return]
