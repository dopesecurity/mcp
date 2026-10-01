"""Custom category MCP tool registration."""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import Context, MCPServer

from dopesecurity.mcp_server.schemas import (
    CustomCategoryUrlsResult,
    ListCustomCategoriesResult,
    SuccessResult,
)
from dopesecurity.mcp_server.tools import get_app_context


def register_custom_category_tools(
    mcp: MCPServer,
    *,
    enable_mutations: bool = False,
    enable_destructive: bool = False,
) -> None:
    """Register custom-category read tools (always), write tools (when
    mutations are enabled), and destructive tools (when both flags are
    enabled)."""

    _register_read_tools(mcp)
    if enable_mutations:
        _register_write_tools(mcp)
        if enable_destructive:
            _register_destructive_tools(mcp)


def _register_read_tools(mcp: MCPServer) -> None:
    @mcp.tool(
        name="list_custom_categories",
        description=(
            "List all custom categories. Cursor-paginated. Returns only category "
            "names/metadata; use get_custom_category_urls to read the URLs that "
            "define each one."
        ),
    )
    async def list_custom_categories(
        ctx: Context,
        first: int | None = None,
        after: str | None = None,
        order: Literal["asc", "desc"] | None = None,
    ) -> ListCustomCategoriesResult:
        return await get_app_context(ctx).custom_categories.list_custom_categories(
            first=first, after=after, order=order
        )

    @mcp.tool(
        name="get_custom_category_urls",
        description=(
            "Get all URL entries in a custom category. A custom category's effect on "
            "a specific policy depends on that policy's restriction for the category "
            "(get_policy_restrictions) and any per-principal exceptions "
            "(get_policy_exceptions)."
        ),
    )
    async def get_custom_category_urls(
        ctx: Context, custom_category_name: str
    ) -> CustomCategoryUrlsResult:
        return await get_app_context(ctx).custom_categories.get_urls(custom_category_name)


def _register_write_tools(mcp: MCPServer) -> None:
    @mcp.tool(
        name="create_custom_category",
        description=(
            "Create a custom category by name. The new category has no URL entries; "
            "add them with add_urls_to_custom_category. Modifies tenant state."
        ),
    )
    async def create_custom_category(
        ctx: Context, custom_category_name: str
    ) -> SuccessResult:
        return await get_app_context(ctx).custom_categories.create(custom_category_name)

    @mcp.tool(
        name="add_urls_to_custom_category",
        description=(
            "Append URL entries to a custom category. The list must be non-empty. "
            "Each entry is a hostname or URL pattern (e.g. example.com, "
            "sub.example.com, *.example.com, example.com/path/*, "
            "example.com?q=*). No scheme — Flightdeck rejects values that start "
            "with http:// or https://. Ports (example.com:8080) and single-label "
            "domains (localhost) are rejected. Domain wildcards are allowed only "
            "at the leftmost position (*.example.com and *example.com are valid; "
            "sub.*.example.com is not); wildcards may appear anywhere in the "
            "path, query, or fragment sections. IPv4 (192.168.1.1) and bracketed "
            "IPv6 ([2001:db8::1]) hosts are accepted; partial IPs, IP ranges, and "
            "wildcards in IPs are not. If any entry is rejected the entire "
            "request fails atomically (no partial add). Modifies tenant state."
        ),
    )
    async def add_urls_to_custom_category(
        ctx: Context,
        custom_category_name: str,
        urls: list[str],
    ) -> SuccessResult:
        return await get_app_context(ctx).custom_categories.add_urls(
            custom_category_name, urls
        )

    @mcp.tool(
        name="delete_single_url_from_custom_category",
        description=(
            "Delete a single URL from a custom category. The URL must match an "
            "entry returned by get_custom_category_urls exactly; if it does not, "
            "Flightdeck returns 404 and this tool surfaces a not-found error "
            "naming the URL and category. The URL is URL-encoded internally "
            "before calling Flightdeck. Modifies tenant state."
        ),
    )
    async def delete_single_url_from_custom_category(
        ctx: Context,
        custom_category_name: str,
        url: str,
    ) -> SuccessResult:
        return await get_app_context(ctx).custom_categories.delete_single_url(
            custom_category_name, url
        )


def _register_destructive_tools(mcp: MCPServer) -> None:
    @mcp.tool(
        name="delete_custom_category",
        description=(
            "DESTRUCTIVE. Delete a custom category by name, including all of its URL "
            "entries. Never use as a diagnostic step. Before calling, confirm the "
            "exact target with the user and wait for an explicit yes. Modifies "
            "tenant state."
        ),
    )
    async def delete_custom_category(
        ctx: Context, custom_category_name: str
    ) -> SuccessResult:
        return await get_app_context(ctx).custom_categories.delete(custom_category_name)

    @mcp.tool(
        name="delete_all_urls_from_custom_category",
        description=(
            "DESTRUCTIVE / WHOLESALE. Removes every URL entry from a custom category "
            "(the category itself remains). Use only when the user has explicitly "
            "asked to clear the category. To remove one URL, use "
            "delete_single_url_from_custom_category. Before calling, confirm the "
            "exact target with the user and wait for an explicit yes. Modifies "
            "tenant state."
        ),
    )
    async def delete_all_urls_from_custom_category(
        ctx: Context, custom_category_name: str
    ) -> SuccessResult:
        return await get_app_context(ctx).custom_categories.delete_all_urls(
            custom_category_name
        )
