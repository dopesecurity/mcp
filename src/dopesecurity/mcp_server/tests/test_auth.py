"""Tests for the FlightdeckTokenManager."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from pydantic import SecretStr

from dopesecurity.mcp_server.auth import FlightdeckTokenManager
from dopesecurity.mcp_server.config import DEFAULT_BASE_URL, Settings
from dopesecurity.mcp_server.errors import FlightdeckAuthenticationError


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "client_id": "test-client",
        "client_secret": SecretStr("test-secret"),
        "enable_mutations": False,
        "timeout_seconds": 30.0,
        "log_level": "INFO",
        "token_refresh_skew_seconds": 60.0,
        "api_base_url": DEFAULT_BASE_URL,
    }
    base.update(overrides)
    return Settings.model_construct(_fields_set=None, **base)


def _make_client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url=DEFAULT_BASE_URL)


async def test_token_manager_exchanges_client_credentials() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"access_token": "abc", "token_type": "bearer", "expires_in": 3600},
        )

    transport = httpx.MockTransport(handler)
    async with _make_client(transport) as http:
        manager = FlightdeckTokenManager(http=http, settings=_settings())
        token = await manager.get_token()

    assert token == "abc"
    assert len(captured) == 1
    request = captured[0]
    assert request.url.path.endswith("/partner/oauth/token")
    body = request.read().decode()
    assert "client_credentials" in body
    assert "test-client" in body
    assert "test-secret" in body


async def test_token_manager_reuses_unexpired_token() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"access_token": "abc", "token_type": "Bearer", "expires_in": 3600},
        )

    async with _make_client(httpx.MockTransport(handler)) as http:
        manager = FlightdeckTokenManager(http=http, settings=_settings())
        first = await manager.get_token()
        second = await manager.get_token()

    assert first == second == "abc"
    assert calls == 1


async def test_token_manager_refreshes_inside_skew() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"access_token": f"tok{calls}", "token_type": "bearer", "expires_in": 1.0},
        )

    async with _make_client(httpx.MockTransport(handler)) as http:
        manager = FlightdeckTokenManager(
            http=http,
            settings=_settings(token_refresh_skew_seconds=5.0),
        )
        first = await manager.get_token()
        second = await manager.get_token()

    assert calls == 2
    assert first == "tok1"
    assert second == "tok2"


async def test_token_manager_serializes_concurrent_refresh() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return httpx.Response(
            200,
            json={"access_token": "abc", "token_type": "bearer", "expires_in": 3600},
        )

    async with _make_client(httpx.MockTransport(handler)) as http:
        manager = FlightdeckTokenManager(http=http, settings=_settings())
        results = await asyncio.gather(*[manager.get_token() for _ in range(10)])

    assert calls == 1
    assert results == ["abc"] * 10


async def test_token_manager_rejects_non_bearer_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "abc", "token_type": "mac", "expires_in": 100},
        )

    async with _make_client(httpx.MockTransport(handler)) as http:
        manager = FlightdeckTokenManager(http=http, settings=_settings())
        with pytest.raises(FlightdeckAuthenticationError):
            await manager.get_token()


async def test_token_manager_invalidate_forces_new_exchange() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"access_token": f"tok{calls}", "token_type": "bearer", "expires_in": 3600},
        )

    async with _make_client(httpx.MockTransport(handler)) as http:
        manager = FlightdeckTokenManager(http=http, settings=_settings())
        await manager.get_token()
        manager.invalidate()
        await manager.get_token(force_refresh=True)

    assert calls == 2


def test_cached_token_expiry() -> None:
    from dopesecurity.mcp_server.auth import CachedToken

    now = time.monotonic()
    expired = CachedToken(access_token="x", expires_at_monotonic=now - 1)
    fresh = CachedToken(access_token="x", expires_at_monotonic=now + 60)
    assert expired.is_expired(now=now)
    assert not fresh.is_expired(now=now)
