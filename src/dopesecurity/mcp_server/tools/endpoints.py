"""Endpoint MCP tool registration."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field, ValidationError

from dopesecurity.mcp_server.errors import InvalidToolInputError
from dopesecurity.mcp_server.schemas import EndpointSearchInput, SearchEndpointsResult
from dopesecurity.mcp_server.tools import get_app_context


def register_endpoint_tools(mcp: MCPServer, *, enable_mutations: bool = False) -> None:  # noqa: ARG001
    """Register read-only endpoint tools on `mcp`.

    Endpoint tools are always registered regardless of the mutation setting.
    """

    @mcp.tool(
        name="search_endpoints",
        description=(
            "List or search Flightdeck endpoints (devices running the dope agent). "
            "With no search field, lists all endpoints (paginated). At most one of "
            "query, email_id, device_name, user_id, os_version, status, debug_state, "
            "fallback_mode, location_id, or agent_version may be supplied per call. "
            "Use `first` and `after` for pagination. The result describes the AGENT "
            "(its enforcement state, version, last-seen, etc.), not the policy "
            "applied to the user. Fields like `status`, `disableMode`, "
            "`fallbackMode`, and `adminSetState.enabled` describe whether the agent "
            "is enforcing policy on the device, not whether the user is blocked — a "
            "disabled agent enforces nothing. To read what the user's policy "
            "actually permits, use the `policy_name` returned here with "
            "get_policy_restrictions / get_policy_exceptions / get_policy_url_bypass."
        ),
    )
    async def search_endpoints(
        ctx: Context,
        first: Annotated[int | None, Field(gt=0)] = None,
        after: str | None = None,
        order: Literal["asc", "desc"] | None = None,
        query: str | None = None,
        email_id: str | None = None,
        device_name: str | None = None,
        user_id: str | None = None,
        os_version: str | None = None,
        status: str | None = None,
        debug_state: str | None = None,
        fallback_mode: str | None = None,
        location_id: str | None = None,
        agent_version: str | None = None,
    ) -> SearchEndpointsResult:
        try:
            input = EndpointSearchInput(
                first=first,
                after=after,
                order=order,
                query=query,
                email_id=email_id,
                device_name=device_name,
                user_id=user_id,
                os_version=os_version,
                status=status,
                debug_state=debug_state,
                fallback_mode=fallback_mode,
                location_id=location_id,
                agent_version=agent_version,
            )
        except ValidationError as exc:
            raise InvalidToolInputError(str(exc)) from exc
        return await get_app_context(ctx).endpoints.search_endpoints(input)
