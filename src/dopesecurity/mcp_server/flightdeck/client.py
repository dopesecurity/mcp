"""Authenticated Flightdeck partner API HTTP client."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx
import structlog

from dopesecurity.mcp_server.auth import FlightdeckTokenManager
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


def _encode_segment(value: str) -> str:
    return quote(value, safe="")


class FlightdeckClient:
    """Thin async HTTP client for the Flightdeck partner API."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        token_manager: FlightdeckTokenManager,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._http = http
        self._tokens = token_manager
        self._logger = logger or structlog.get_logger("dopesecurity.mcp_server.flightdeck")

    # ---- generic request -----------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        return await self._send(method, path, params=params, json=json)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        json: Any | None,
    ) -> Any:
        token = await self._tokens.get_token()
        try:
            response = await self._do(method, path, params=params, json=json, token=token)
        except httpx.TransportError as exc:
            self._logger.exception(
                "flightdeck.transport_error",
                method=method,
                path=path,
                exc_type=type(exc).__name__,
                exc_message=str(exc),
            )
            raise FlightdeckTransportError(
                f"Failed to reach Flightdeck: {method} {path}: {type(exc).__name__}: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - log and re-raise
            self._logger.exception(
                "flightdeck.unexpected_request_error",
                method=method,
                path=path,
                exc_type=type(exc).__name__,
                exc_message=str(exc),
            )
            raise

        if response.status_code == 401:
            self._logger.warning(
                "flightdeck.received_401_retrying",
                method=method,
                path=path,
                body_text=response.text,
            )
            self._tokens.invalidate()
            token = await self._tokens.get_token(force_refresh=True)
            try:
                response = await self._do(method, path, params=params, json=json, token=token)
            except httpx.TransportError as exc:
                self._logger.exception(
                    "flightdeck.transport_error_on_retry",
                    method=method,
                    path=path,
                    exc_type=type(exc).__name__,
                    exc_message=str(exc),
                )
                raise FlightdeckTransportError(
                    f"Failed to reach Flightdeck: {method} {path}: "
                    f"{type(exc).__name__}: {exc}",
                ) from exc

        try:
            return self._handle_response(response)
        except Exception as exc:
            self._logger.exception(
                "flightdeck.response_error",
                method=method,
                path=path,
                status=response.status_code,
                exc_type=type(exc).__name__,
                exc_message=str(exc),
                body_text=response.text,
            )
            raise

    async def _do(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        json: Any | None,
        token: str,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"}
        # WARNING: full bearer token, params, and request body logged on
        # purpose for debugging credential issues; remove before production.
        self._logger.debug(
            "flightdeck.request",
            method=method,
            path=path,
            params=dict(params) if params is not None else None,
            json=json,
            authorization=headers["Authorization"],
        )
        response = await self._http.request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
        )
        self._logger.info(
            "flightdeck.response",
            method=method,
            path=path,
            status=response.status_code,
            headers=dict(response.headers),
            body_text=response.text,
        )
        return response

    @staticmethod
    def _handle_response(response: httpx.Response) -> Any:
        status = response.status_code
        if 200 <= status < 300:
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return None

        details = _safe_json(response)
        if status == 400:
            # Flightdeck returns 400 (not 409) for assignment conflicts on
            # PUT /policies/{name}/assignments — see partner_api.yaml.
            if _looks_like_assignment_conflict(details):
                raise AssignmentConflictError(
                    "User or group already assigned to another policy",
                    details=details,
                )
            raise FlightdeckValidationError(
                "Flightdeck rejected the request as invalid",
                details=details,
            )
        if status == 401:
            raise FlightdeckAuthenticationError(
                "Flightdeck rejected the request",
                details=details,
            )
        if status == 403:
            raise FlightdeckAuthorizationError(
                "Flightdeck denied the request",
                details=details,
            )
        if status == 404:
            raise FlightdeckNotFoundError(
                "Flightdeck resource not found",
                details=details,
            )
        if status == 409:
            if _looks_like_assignment_conflict(details):
                raise AssignmentConflictError(
                    "User or group already assigned to another policy",
                    details=details,
                )
            raise FlightdeckConflictError(
                "Flightdeck reported a conflict",
                details=details,
            )
        if 500 <= status < 600:
            raise FlightdeckServerError(
                f"Flightdeck server error (status {status})",
                details=details,
            )
        raise FlightdeckValidationError(
            f"Unexpected Flightdeck response status {status}",
            details=details,
        )

    # ---- endpoints -----------------------------------------------------------

    async def search_endpoints(self, params: Mapping[str, Any]) -> Any:
        return await self._send("GET", "/endpoints/search", params=params, json=None)

    # ---- policies ------------------------------------------------------------

    async def list_policies(self, params: Mapping[str, Any]) -> Any:
        return await self._send("GET", "/policies", params=params, json=None)

    async def create_policy(self, policy_name: str) -> Any:
        return await self._send(
            "POST",
            f"/policies/{_encode_segment(policy_name)}",
            params=None,
            json=None,
        )

    async def delete_policy(self, policy_name: str) -> Any:
        return await self._send(
            "DELETE",
            f"/policies/{_encode_segment(policy_name)}",
            params=None,
            json=None,
        )

    async def get_policy_content(self, policy_name: str) -> Any:
        return await self._send(
            "GET",
            f"/policies/{_encode_segment(policy_name)}/content",
            params=None,
            json=None,
        )

    async def update_policy_content_restrictions(
        self, policy_name: str, body: Mapping[str, Any]
    ) -> Any:
        return await self._send(
            "PUT",
            f"/policies/{_encode_segment(policy_name)}/content/restrictions",
            params=None,
            json=body,
        )

    async def update_policy_content_exceptions(
        self, policy_name: str, body: Mapping[str, Any]
    ) -> Any:
        return await self._send(
            "PUT",
            f"/policies/{_encode_segment(policy_name)}/content/exceptions",
            params=None,
            json=body,
        )

    async def get_policy_assignments(self, policy_name: str) -> Any:
        return await self._send(
            "GET",
            f"/policies/{_encode_segment(policy_name)}/assignments",
            params=None,
            json=None,
        )

    async def update_policy_assignments(
        self, policy_name: str, body: Mapping[str, Any]
    ) -> Any:
        return await self._send(
            "PUT",
            f"/policies/{_encode_segment(policy_name)}/assignments",
            params=None,
            json=body,
        )

    async def get_policy_url_bypass(self, policy_name: str) -> Any:
        return await self._send(
            "GET",
            f"/policies/{_encode_segment(policy_name)}/bypass/urls",
            params=None,
            json=None,
        )

    async def upsert_policy_url_bypass(
        self, policy_name: str, body: Mapping[str, Any]
    ) -> Any:
        return await self._send(
            "PUT",
            f"/policies/{_encode_segment(policy_name)}/bypass/urls",
            params=None,
            json=body,
        )

    async def delete_policy_url_bypass_entries(
        self, policy_name: str, names: Sequence[str]
    ) -> Any:
        return await self._send(
            "DELETE",
            f"/policies/{_encode_segment(policy_name)}/bypass/urls",
            params=None,
            json={"data": {"custom": {"urls": list(names)}}},
        )

    async def get_policy_application_bypass(self, policy_name: str) -> Any:
        return await self._send(
            "GET",
            f"/policies/{_encode_segment(policy_name)}/bypass/applications",
            params=None,
            json=None,
        )

    async def upsert_policy_application_bypass(
        self, policy_name: str, body: Mapping[str, Any]
    ) -> Any:
        return await self._send(
            "PUT",
            f"/policies/{_encode_segment(policy_name)}/bypass/applications",
            params=None,
            json=body,
        )

    async def delete_policy_application_bypass_entries(
        self,
        policy_name: str,
        *,
        mac: Sequence[str] | None,
        windows: Sequence[str] | None,
    ) -> Any:
        custom: dict[str, list[str]] = {}
        if mac is not None:
            custom["mac"] = list(mac)
        if windows is not None:
            custom["windows"] = list(windows)
        return await self._send(
            "DELETE",
            f"/policies/{_encode_segment(policy_name)}/bypass/applications",
            params=None,
            json={"data": {"custom": custom}},
        )

    # ---- custom categories ---------------------------------------------------

    async def list_custom_categories(self, params: Mapping[str, Any]) -> Any:
        return await self._send("GET", "/custom_categories", params=params, json=None)

    async def create_custom_category(self, custom_category_name: str) -> Any:
        return await self._send(
            "POST",
            f"/custom_categories/{_encode_segment(custom_category_name)}",
            params=None,
            json=None,
        )

    async def delete_custom_category(self, custom_category_name: str) -> Any:
        return await self._send(
            "DELETE",
            f"/custom_categories/{_encode_segment(custom_category_name)}",
            params=None,
            json=None,
        )

    async def get_custom_category_urls(self, custom_category_name: str) -> Any:
        return await self._send(
            "GET",
            f"/custom_categories/{_encode_segment(custom_category_name)}/urls",
            params=None,
            json=None,
        )

    async def add_urls_to_custom_category(
        self, custom_category_name: str, urls: Sequence[str]
    ) -> Any:
        return await self._send(
            "POST",
            f"/custom_categories/{_encode_segment(custom_category_name)}/urls",
            params=None,
            json={"data": {"urls": list(urls)}},
        )

    async def delete_all_urls_from_custom_category(self, custom_category_name: str) -> Any:
        return await self._send(
            "DELETE",
            f"/custom_categories/{_encode_segment(custom_category_name)}/urls",
            params=None,
            json=None,
        )

    async def delete_single_url_from_custom_category(
        self, custom_category_name: str, encoded_url: str
    ) -> Any:
        # `encoded_url` is expected pre-encoded by the caller; pass it through verbatim.
        return await self._send(
            "DELETE",
            f"/custom_categories/{_encode_segment(custom_category_name)}/url/{encoded_url}",
            params=None,
            json=None,
        )


def _safe_json(response: httpx.Response) -> Any | None:
    try:
        return response.json()
    except ValueError:
        return None


def _looks_like_assignment_conflict(details: Any | None) -> bool:
    if not isinstance(details, Mapping):
        return False
    errors = details.get("errors")
    if not isinstance(errors, list):
        return False
    for entry in errors:
        if isinstance(entry, Mapping):
            code = entry.get("code")
            message = entry.get("message")
            if isinstance(code, str) and "assign" in code.lower():
                return True
            if isinstance(message, str) and "already assigned" in message.lower():
                return True
    return False
