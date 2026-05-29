"""Tests for the FastMCP server composition."""

from __future__ import annotations

import argparse

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import SecretStr

from dopesecurity.mcp_server.__main__ import _build_parser
from dopesecurity.mcp_server.auth import FlightdeckTokenManager
from dopesecurity.mcp_server.config import DEFAULT_BASE_URL, Settings
from dopesecurity.mcp_server.flightdeck.client import FlightdeckClient
from dopesecurity.mcp_server.server import AppContext, create_server
from dopesecurity.mcp_server.services.custom_categories import CustomCategoriesService
from dopesecurity.mcp_server.services.endpoints import EndpointsService
from dopesecurity.mcp_server.services.policies import PoliciesService


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


def test_create_server_returns_fastmcp_instance() -> None:
    server = create_server(_settings())
    assert isinstance(server, FastMCP)


async def test_lifespan_builds_shared_context() -> None:
    server = create_server(_settings())

    lifespan = server._mcp_server.lifespan
    async with lifespan(server._mcp_server) as ctx:
        assert isinstance(ctx, AppContext)
        assert isinstance(ctx.settings, Settings)
        assert isinstance(ctx.token_manager, FlightdeckTokenManager)
        assert isinstance(ctx.flightdeck, FlightdeckClient)
        assert isinstance(ctx.endpoints, EndpointsService)
        assert isinstance(ctx.policies, PoliciesService)
        assert isinstance(ctx.custom_categories, CustomCategoriesService)


def _patch_registrations(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, dict[str, bool]]:
    captured: dict[str, dict[str, bool]] = {}

    def fake_register_policy(
        mcp: FastMCP,
        *,
        enable_mutations: bool = False,
        enable_destructive: bool = False,
    ) -> None:
        captured["policies"] = {
            "mutations": enable_mutations,
            "destructive": enable_destructive,
        }

    def fake_register_endpoints(
        mcp: FastMCP, *, enable_mutations: bool = False
    ) -> None:
        captured["endpoints"] = {"mutations": enable_mutations}

    def fake_register_custom(
        mcp: FastMCP,
        *,
        enable_mutations: bool = False,
        enable_destructive: bool = False,
    ) -> None:
        captured["custom"] = {
            "mutations": enable_mutations,
            "destructive": enable_destructive,
        }

    monkeypatch.setattr(
        "dopesecurity.mcp_server.tools.policies.register_policy_tools",
        fake_register_policy,
    )
    monkeypatch.setattr(
        "dopesecurity.mcp_server.tools.endpoints.register_endpoint_tools",
        fake_register_endpoints,
    )
    monkeypatch.setattr(
        "dopesecurity.mcp_server.tools.custom_categories.register_custom_category_tools",
        fake_register_custom,
    )
    return captured


def test_write_tools_not_registered_when_mutations_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_registrations(monkeypatch)
    create_server(_settings(enable_mutations=False))
    assert captured == {
        "policies": {"mutations": False, "destructive": False},
        "endpoints": {"mutations": False},
        "custom": {"mutations": False, "destructive": False},
    }


def test_write_tools_registered_when_mutations_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_registrations(monkeypatch)
    create_server(_settings(enable_mutations=True))
    assert captured == {
        "policies": {"mutations": True, "destructive": False},
        "endpoints": {"mutations": True},
        "custom": {"mutations": True, "destructive": False},
    }


def test_destructive_flag_threads_through_when_both_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_registrations(monkeypatch)
    create_server(_settings(enable_mutations=True, enable_destructive=True))
    assert captured == {
        "policies": {"mutations": True, "destructive": True},
        "endpoints": {"mutations": True},
        "custom": {"mutations": True, "destructive": True},
    }


def test_destructive_without_mutations_rejected_at_startup() -> None:
    with pytest.raises(ValueError, match="destructive"):
        create_server(_settings(enable_mutations=False, enable_destructive=True))


def test_cli_does_not_define_secret_flags() -> None:
    parser = _build_parser()
    actions = {a.dest for a in parser._actions if isinstance(a, argparse.Action)}
    assert "client_id" not in actions
    assert "client_secret" not in actions

    with pytest.raises(SystemExit):
        parser.parse_args(["--client-id", "x"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--client-secret", "x"])
