"""FastMCP server composition root."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from mcp.server.fastmcp import FastMCP

from dopesecurity.mcp_server.auth import FlightdeckTokenManager
from dopesecurity.mcp_server.config import Settings, load_settings
from dopesecurity.mcp_server.flightdeck.client import FlightdeckClient
from dopesecurity.mcp_server.instructions import INSTRUCTIONS

_logger = structlog.get_logger("dopesecurity.mcp_server.server")

if TYPE_CHECKING:
    from dopesecurity.mcp_server.services.custom_categories import CustomCategoriesService
    from dopesecurity.mcp_server.services.endpoints import EndpointsService
    from dopesecurity.mcp_server.services.policies import PoliciesService


SERVER_NAME = "dope-security"


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    token_manager: FlightdeckTokenManager
    flightdeck: FlightdeckClient
    endpoints: EndpointsService
    policies: PoliciesService
    custom_categories: CustomCategoriesService


def _build_services(flightdeck: FlightdeckClient) -> tuple[Any, Any, Any]:
    # Imported lazily so server.py stays import-safe even before the service
    # modules are written.
    from dopesecurity.mcp_server.services.custom_categories import CustomCategoriesService
    from dopesecurity.mcp_server.services.endpoints import EndpointsService
    from dopesecurity.mcp_server.services.policies import PoliciesService

    return (
        EndpointsService(flightdeck),
        PoliciesService(flightdeck),
        CustomCategoriesService(flightdeck),
    )


def _make_lifespan(
    settings: Settings,
) -> Any:
    @asynccontextmanager
    async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
        # WARNING: settings include the (masked) client_secret only via
        # SecretStr's repr; client_id is logged in clear text on purpose.
        _logger.info(
            "server.lifespan.start",
            api_base_url=settings.api_base_url,
            timeout_seconds=settings.timeout_seconds,
            enable_mutations=settings.enable_mutations,
            enable_destructive=settings.enable_destructive,
            client_id=settings.client_id,
            log_level=settings.log_level,
            token_refresh_skew_seconds=settings.token_refresh_skew_seconds,
        )
        try:
            async with httpx.AsyncClient(
                base_url=settings.api_base_url,
                timeout=settings.timeout_seconds,
            ) as http:
                token_manager = FlightdeckTokenManager(http=http, settings=settings)
                flightdeck = FlightdeckClient(http=http, token_manager=token_manager)
                endpoints, policies, custom_categories = _build_services(flightdeck)
                _logger.info("server.lifespan.ready")
                yield AppContext(
                    settings=settings,
                    token_manager=token_manager,
                    flightdeck=flightdeck,
                    endpoints=endpoints,
                    policies=policies,
                    custom_categories=custom_categories,
                )
        except Exception as exc:
            _logger.exception(
                "server.lifespan.error",
                exc_type=type(exc).__name__,
                exc_message=str(exc),
            )
            raise
        finally:
            _logger.info("server.lifespan.shutdown")

    return app_lifespan


def _register_tools(
    mcp: FastMCP, *, enable_mutations: bool, enable_destructive: bool
) -> None:
    from dopesecurity.mcp_server.tools.custom_categories import register_custom_category_tools
    from dopesecurity.mcp_server.tools.endpoints import register_endpoint_tools
    from dopesecurity.mcp_server.tools.policies import register_policy_tools

    register_endpoint_tools(mcp, enable_mutations=enable_mutations)
    register_policy_tools(
        mcp,
        enable_mutations=enable_mutations,
        enable_destructive=enable_destructive,
    )
    register_custom_category_tools(
        mcp,
        enable_mutations=enable_mutations,
        enable_destructive=enable_destructive,
    )


def create_server(settings: Settings | None = None) -> FastMCP:
    """Build a configured FastMCP server instance."""

    settings = settings if settings is not None else load_settings()
    if settings.enable_destructive and not settings.enable_mutations:
        # Defense in depth: Settings has a validator for this, but tests can
        # hand-construct via model_construct which bypasses validation.
        raise ValueError(
            "enable_destructive requires enable_mutations to also be enabled "
            "(destructive tools are a subset of write tools)."
        )
    lifespan = _make_lifespan(settings)
    mcp = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS, lifespan=lifespan)
    _register_tools(
        mcp,
        enable_mutations=settings.enable_mutations,
        enable_destructive=settings.enable_destructive,
    )
    return mcp
