"""Flightdeck OAuth client-credentials token manager."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from dopesecurity.mcp_server.config import Settings
from dopesecurity.mcp_server.errors import (
    FlightdeckAuthenticationError,
    FlightdeckServerError,
    FlightdeckTransportError,
)
from dopesecurity.mcp_server.flightdeck.models import TokenResponse  # noqa: TID252

TOKEN_PATH = "/partner/oauth/token"


@dataclass
class CachedToken:
    access_token: str
    expires_at_monotonic: float

    def is_expired(self, *, now: float) -> bool:
        return now >= self.expires_at_monotonic


class FlightdeckTokenManager:
    """Caches a Flightdeck bearer token and refreshes it before expiry."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._http = http
        self._settings = settings
        self._logger = logger or structlog.get_logger("dopesecurity.mcp_server.auth")
        self._lock = asyncio.Lock()
        self._cached: CachedToken | None = None

    def invalidate(self) -> None:
        """Discard the cached token so the next call exchanges credentials again."""

        self._logger.info("auth.token.invalidate", had_cached=self._cached is not None)
        self._cached = None

    async def get_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh:
            current = self._cached
            if current is not None and not current.is_expired(now=time.monotonic()):
                self._logger.debug(
                    "auth.token.cache_hit",
                    expires_in=max(current.expires_at_monotonic - time.monotonic(), 0.0),
                )
                return current.access_token

        async with self._lock:
            if not force_refresh:
                current = self._cached
                if current is not None and not current.is_expired(now=time.monotonic()):
                    self._logger.debug("auth.token.cache_hit_after_lock")
                    return current.access_token
            self._logger.info(
                "auth.token.exchange_start",
                force_refresh=force_refresh,
                base_url=str(self._http.base_url),
                token_path=TOKEN_PATH,
                client_id=self._settings.client_id,
            )
            token = await self._exchange()
            self._cached = token
            self._logger.info(
                "auth.token.exchange_success",
                expires_at_monotonic=token.expires_at_monotonic,
                seconds_until_expiry=max(
                    token.expires_at_monotonic - time.monotonic(), 0.0
                ),
            )
            return token.access_token

    async def _exchange(self) -> CachedToken:
        body = {
            "grant_type": "client_credentials",
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret.get_secret_value(),
        }
        # WARNING: logging the full body (including the client_secret) is
        # intentional for credential debugging; remove before production.
        self._logger.debug(
            "auth.token.request",
            url=str(httpx.URL(self._http.base_url).join(TOKEN_PATH)),
            body=body,
        )
        try:
            response = await self._http.post(TOKEN_PATH, json=body)
        except httpx.TransportError as exc:
            self._logger.exception(
                "auth.token.transport_error",
                exc_type=type(exc).__name__,
                exc_message=str(exc),
                request_url=str(getattr(exc, "request", None) and exc.request.url),
            )
            raise FlightdeckTransportError(
                f"Failed to reach Flightdeck token endpoint: {type(exc).__name__}: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - log everything else too
            self._logger.exception(
                "auth.token.unexpected_request_error",
                exc_type=type(exc).__name__,
                exc_message=str(exc),
            )
            raise

        # WARNING: response body and headers may contain tokens or hints
        # about credential failures; logged on purpose for debugging.
        self._logger.info(
            "auth.token.response",
            status=response.status_code,
            headers=dict(response.headers),
            body_text=response.text,
            body_json=_safe_json(response),
        )

        if response.status_code in (400, 401, 403):
            details = _safe_json(response)
            self._logger.error(
                "auth.token.rejected",
                status=response.status_code,
                details=details,
                body_text=response.text,
            )
            raise FlightdeckAuthenticationError(
                f"Flightdeck rejected the client credentials (status {response.status_code}): "
                f"{response.text}",
                details=details,
            )
        if response.status_code >= 500:
            details = _safe_json(response)
            self._logger.error(
                "auth.token.server_error",
                status=response.status_code,
                details=details,
                body_text=response.text,
            )
            raise FlightdeckServerError(
                f"Flightdeck token endpoint returned a server error (status "
                f"{response.status_code}): {response.text}",
                details=details,
            )
        if response.status_code != 200:
            details = _safe_json(response)
            self._logger.error(
                "auth.token.unexpected_status",
                status=response.status_code,
                details=details,
                body_text=response.text,
            )
            raise FlightdeckAuthenticationError(
                f"Unexpected token response status {response.status_code}: {response.text}",
                details=details,
            )

        try:
            parsed = TokenResponse.model_validate(response.json())
        except Exception as exc:  # noqa: BLE001 - normalize parse failures
            self._logger.exception(
                "auth.token.parse_failed",
                exc_type=type(exc).__name__,
                exc_message=str(exc),
                body_text=response.text,
            )
            raise FlightdeckAuthenticationError(
                f"Token response could not be parsed: {type(exc).__name__}: {exc}",
            ) from exc

        if parsed.token_type.lower() != "bearer":
            self._logger.error(
                "auth.token.unsupported_token_type",
                token_type=parsed.token_type,
            )
            raise FlightdeckAuthenticationError(
                f"Unsupported token_type {parsed.token_type!r}",
            )

        skew = self._settings.token_refresh_skew_seconds
        expires_at = time.monotonic() + max(parsed.expires_in - skew, 0.0)
        # WARNING: full access token logged for debugging.
        self._logger.debug(
            "auth.token.parsed",
            token_type=parsed.token_type,
            expires_in=parsed.expires_in,
            skew=skew,
            access_token=parsed.access_token,
        )
        return CachedToken(access_token=parsed.access_token, expires_at_monotonic=expires_at)


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
