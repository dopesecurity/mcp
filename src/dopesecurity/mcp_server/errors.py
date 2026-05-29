"""Internal exception hierarchy and normalized error model."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import structlog

_logger = structlog.get_logger("dopesecurity.mcp_server.errors")


# --- Detail extraction helpers ------------------------------------------------


# Keys we look at inside a Flightdeck error envelope to find a human-readable
# description of what went wrong. Ordered by preference.
_DETAIL_MESSAGE_KEYS: tuple[str, ...] = (
    "message",
    "detail",
    "description",
    "error",
    "reason",
)


def _extract_detail_messages(details: Any) -> list[str]:
    """Pull human-readable messages out of a Flightdeck-style error body.

    Flightdeck typically returns ``{"errors": [{"code": "...", "message": "..."}]}``
    on 4xx responses but some endpoints flatten it to a top-level
    ``{"message": "..."}``. This helper tolerates both shapes and returns a
    de-duplicated list of messages, preserving order.
    """

    if not isinstance(details, Mapping):
        return []

    messages: list[str] = []

    errors = details.get("errors")
    if isinstance(errors, list):
        for entry in errors:
            if not isinstance(entry, Mapping):
                continue
            for key in _DETAIL_MESSAGE_KEYS:
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    messages.append(value.strip())
                    break

    if not messages:
        for key in _DETAIL_MESSAGE_KEYS:
            value = details.get(key)
            if isinstance(value, str) and value.strip():
                messages.append(value.strip())
                break

    # De-dupe while preserving order.
    return list(dict.fromkeys(messages))


def _enrich_message(base_message: str, details: Any) -> str:
    """Append per-error detail messages to ``base_message`` when present."""

    detail_messages = _extract_detail_messages(details)
    if not detail_messages:
        return base_message
    joined = "; ".join(detail_messages)
    if joined in base_message:
        return base_message
    return f"{base_message}: {joined}"


def _format_details_block(details: Any) -> str | None:
    """Render ``details`` as a compact JSON block suitable for surfacing to
    the agent. Returns ``None`` when there is nothing useful to show."""

    if details is None:
        return None
    try:
        rendered = json.dumps(details, default=str, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        rendered = repr(details)
    if not rendered or rendered in ("null", "{}", "[]", '""'):
        return None
    return f"Details: {rendered}"


# --- Public model -------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedError:
    """A concise, agent-safe error shape surfaced through MCP tool failures."""

    code: str
    message: str
    details: Any | None = field(default=None)


class DopesecurityMCPError(Exception):
    """Base exception type for the MCP server.

    The exception's string form embeds both an enriched message (with any
    per-error detail messages extracted from ``details``) and a JSON
    ``Details: {...}`` block. FastMCP surfaces ``str(exc)`` to the caller, so
    this is what the agent sees on a failed tool call.
    """

    code: str = "internal_error"
    message: str = "An internal error occurred"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Any | None = None,
        code: str | None = None,
    ) -> None:
        base = message if message is not None else self.message
        self._message = _enrich_message(base, details)
        self._details = details
        if code is not None:
            self.code = code
        super().__init__(self._message)

    def __str__(self) -> str:
        block = _format_details_block(self._details)
        if block is None:
            return self._message
        return f"{self._message}\n\n{block}"

    @property
    def normalized(self) -> NormalizedError:
        return NormalizedError(code=self.code, message=self._message, details=self._details)


# --- Flightdeck client boundary errors ---------------------------------------


class FlightdeckError(DopesecurityMCPError):
    """Base class for errors raised at the Flightdeck HTTP boundary."""

    code = "flightdeck_error"
    message = "Flightdeck API error"


class FlightdeckAuthenticationError(FlightdeckError):
    code = "flightdeck_authentication_error"
    message = "Flightdeck rejected the credentials"


class FlightdeckAuthorizationError(FlightdeckError):
    code = "flightdeck_authorization_error"
    message = "Flightdeck denied the request"


class FlightdeckNotFoundError(FlightdeckError):
    code = "flightdeck_not_found"
    message = "Flightdeck resource not found"


class FlightdeckValidationError(FlightdeckError):
    code = "flightdeck_validation_error"
    message = "Flightdeck rejected the request as invalid"


class FlightdeckConflictError(FlightdeckError):
    code = "flightdeck_conflict"
    message = "Flightdeck reported a conflict"


class FlightdeckServerError(FlightdeckError):
    code = "flightdeck_server_error"
    message = "Flightdeck returned a server error"


class FlightdeckTransportError(FlightdeckError):
    code = "flightdeck_transport_error"
    message = "Failed to reach Flightdeck"


# --- Domain errors ------------------------------------------------------------


class PolicyNotFoundError(DopesecurityMCPError):
    code = "policy_not_found"
    message = "Policy not found"


class AssignmentConflictError(DopesecurityMCPError):
    code = "assignment_conflict"
    message = "User or group is already assigned to another policy"


class InheritedPolicyMutationError(DopesecurityMCPError):
    code = "inherited_policy_mutation"
    message = "Policy currently inherits from base; reset before mutating"


class InvalidPrincipalError(DopesecurityMCPError):
    code = "invalid_principal"
    message = "One or more principals are invalid"


class MutationDisabledError(DopesecurityMCPError):
    code = "mutation_disabled"
    message = "Mutations are disabled. Enable them with --enable-mutations or DOPE_ENABLE_MUTATIONS=true."


def to_tool_error(error: Exception) -> NormalizedError:
    """Convert any exception into a normalized error suitable for tool surfaces."""

    # WARNING: logs full exception (with traceback, message, and details)
    # to aid debugging of credential and transport failures. Remove before
    # production.
    if isinstance(error, DopesecurityMCPError):
        _logger.error(
            "tool.error.normalized",
            exc_type=type(error).__name__,
            code=error.code,
            message=str(error),
            details=error.normalized.details,
            exc_info=error,
        )
        return error.normalized
    _logger.error(
        "tool.error.unhandled",
        exc_type=type(error).__name__,
        message=str(error),
        exc_info=error,
    )
    return NormalizedError(code="internal_error", message="An internal error occurred")
