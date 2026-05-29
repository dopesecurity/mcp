"""Tests for the FlightdeckClient."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from dopesecurity.mcp_server.auth import FlightdeckTokenManager
from dopesecurity.mcp_server.config import DEFAULT_BASE_URL, Settings
from dopesecurity.mcp_server.errors import (
    AssignmentConflictError,
    FlightdeckAuthenticationError,
    FlightdeckAuthorizationError,
    FlightdeckConflictError,
    FlightdeckNotFoundError,
    FlightdeckServerError,
    FlightdeckTransportError,
    FlightdeckValidationError,
)
from dopesecurity.mcp_server.flightdeck.client import FlightdeckClient


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


def _token_response() -> dict[str, object]:
    return {"access_token": "tok", "token_type": "bearer", "expires_in": 3600}


async def _make_client(
    handler: httpx.MockTransport,
) -> tuple[httpx.AsyncClient, FlightdeckClient]:
    http = httpx.AsyncClient(transport=handler, base_url=DEFAULT_BASE_URL)
    tokens = FlightdeckTokenManager(http=http, settings=_settings())
    return http, FlightdeckClient(http=http, token_manager=tokens)


async def test_client_adds_bearer_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        seen.append(request)
        return httpx.Response(200, json={"data": {"endpoints": [], "pageInfo": {}}})

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        await client.search_endpoints({"first": 5})
    finally:
        await http.aclose()

    assert seen, "Expected an authenticated request"
    request = seen[0]
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.url.path.endswith("/endpoints/search")
    assert request.url.params["first"] == "5"


async def test_client_retries_once_after_401() -> None:
    api_calls = 0
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls, token_calls
        if request.url.path.endswith("/partner/oauth/token"):
            token_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"tok{token_calls}",
                    "token_type": "bearer",
                    "expires_in": 3600,
                },
            )
        api_calls += 1
        if api_calls == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"data": {}})

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        result = await client.list_policies({"first": 1})
    finally:
        await http.aclose()

    assert result == {"data": {}}
    assert api_calls == 2
    assert token_calls == 2  # initial + forced refresh


async def test_client_does_not_retry_more_than_once_on_repeated_401() -> None:
    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        api_calls += 1
        return httpx.Response(401, json={"error": "still expired"})

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        with pytest.raises(FlightdeckAuthenticationError):
            await client.list_policies({})
    finally:
        await http.aclose()

    assert api_calls == 2


@pytest.mark.parametrize(
    "status, expected",
    [
        (400, FlightdeckValidationError),
        (403, FlightdeckAuthorizationError),
        (404, FlightdeckNotFoundError),
        (409, FlightdeckConflictError),
        (500, FlightdeckServerError),
        (502, FlightdeckServerError),
    ],
)
async def test_client_maps_status_codes_to_errors(
    status: int, expected: type[Exception]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        return httpx.Response(status, json={"errors": [{"message": "boom"}]})

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        with pytest.raises(expected):
            await client.list_policies({})
    finally:
        await http.aclose()


async def test_client_maps_assignment_conflict_409() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        return httpx.Response(
            409,
            json={"errors": [{"message": "User already assigned to another policy"}]},
        )

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        with pytest.raises(AssignmentConflictError):
            await client.update_policy_assignments(
                "Engineering", {"users": [{"email": "a@example.com"}], "groups": []}
            )
    finally:
        await http.aclose()


async def test_client_maps_assignment_conflict_400() -> None:
    # Flightdeck documents this conflict shape under a 400 (not 409) on
    # PUT /policies/{name}/assignments — see partner_api.yaml.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        return httpx.Response(
            400,
            json={
                "errors": [
                    {
                        "message": "User/Group already assigned to another policy",
                        "details": {
                            "userGroupPolicyNames": {
                                "alex@example.com": "Marketing",
                            }
                        },
                    }
                ]
            },
        )

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        with pytest.raises(AssignmentConflictError):
            await client.update_policy_assignments(
                "Engineering", {"users": [{"email": "alex@example.com"}], "groups": []}
            )
    finally:
        await http.aclose()


async def test_client_maps_transport_error() -> None:
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path.endswith("/partner/oauth/token"):
            token_calls += 1
            return httpx.Response(200, json=_token_response())
        raise httpx.ConnectError("boom")

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        with pytest.raises(FlightdeckTransportError):
            await client.list_policies({})
    finally:
        await http.aclose()

    assert token_calls == 1


async def test_client_encodes_policy_path_segments() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        captured.append(request)
        return httpx.Response(200, json={"data": {}})

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        await client.get_policy_content("Engineering Team")
    finally:
        await http.aclose()

    assert captured
    assert captured[0].url.raw_path.endswith(b"/policies/Engineering%20Team/content")


async def test_client_delete_url_bypass_entries_sends_names() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        captured.append(request)
        return httpx.Response(204)

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        await client.delete_policy_url_bypass_entries("Default", ["a", "b"])
    finally:
        await http.aclose()

    request = captured[0]
    assert request.method == "DELETE"
    assert request.url.path.endswith("/policies/Default/bypass/urls")
    body = request.read()
    assert b'"urls"' in body
    assert b'"custom"' in body


async def test_client_delete_application_bypass_entries_sends_per_platform_body() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        captured.append(request)
        return httpx.Response(204)

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        await client.delete_policy_application_bypass_entries(
            "Default", mac=["Slack.app"], windows=None
        )
    finally:
        await http.aclose()

    request = captured[0]
    assert request.method == "DELETE"
    assert request.url.path.endswith("/policies/Default/bypass/applications")
    body = request.read()
    assert b'"mac"' in body
    assert b"Slack.app" in body
    assert b'"windows"' not in body


async def test_client_returns_none_for_empty_2xx_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        return httpx.Response(204)

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        result = await client.create_policy("Newbie")
    finally:
        await http.aclose()

    assert result is None


async def test_client_delete_single_url_passes_pre_encoded_value() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/partner/oauth/token"):
            return httpx.Response(200, json=_token_response())
        captured.append(request)
        return httpx.Response(204)

    http, client = await _make_client(httpx.MockTransport(handler))
    try:
        await client.delete_single_url_from_custom_category(
            "Gambling", "https%3A%2F%2Fexample.com%2Fa%3Fb%3Dc"
        )
    finally:
        await http.aclose()

    assert captured[0].url.raw_path.endswith(
        b"/custom_categories/Gambling/url/https%3A%2F%2Fexample.com%2Fa%3Fb%3Dc"
    )
