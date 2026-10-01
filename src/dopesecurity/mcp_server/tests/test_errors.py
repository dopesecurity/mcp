"""Tests for the normalized error helpers."""

from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dopesecurity.mcp_server.errors import (
    AssignmentConflictError,
    DopesecurityMCPError,
    FlightdeckAuthenticationError,
    FlightdeckAuthorizationError,
    FlightdeckConflictError,
    FlightdeckNotFoundError,
    FlightdeckServerError,
    FlightdeckTransportError,
    FlightdeckValidationError,
    InheritedPolicyMutationError,
    InvalidPrincipalError,
    MutationDisabledError,
    NormalizedError,
    PolicyNotFoundError,
    to_tool_error,
)


def test_to_tool_error_preserves_details_for_known_errors() -> None:
    details = {"errors": [{"field": "users", "message": "duplicate"}]}
    err = AssignmentConflictError("alice already assigned", details=details)

    normalized = to_tool_error(err)

    assert isinstance(normalized, NormalizedError)
    assert normalized.code == "assignment_conflict"
    # Per-error detail messages are folded into the normalized message so the
    # agent sees what actually went wrong, not just the generic class summary.
    assert normalized.message == "alice already assigned: duplicate"
    assert normalized.details == details


def test_to_tool_error_hides_unknown_errors() -> None:
    normalized = to_tool_error(RuntimeError("internal stacktrace details"))
    assert normalized.code == "internal_error"
    assert "stacktrace" not in normalized.message
    assert normalized.details is None


def test_known_error_classes_are_distinct() -> None:
    classes = {
        FlightdeckAuthenticationError,
        FlightdeckAuthorizationError,
        FlightdeckNotFoundError,
        FlightdeckValidationError,
        FlightdeckConflictError,
        FlightdeckServerError,
        FlightdeckTransportError,
        PolicyNotFoundError,
        AssignmentConflictError,
        InheritedPolicyMutationError,
        InvalidPrincipalError,
        MutationDisabledError,
    }
    codes = {cls.code for cls in classes}
    assert len(codes) == len(classes)
    assert all(issubclass(cls, DopesecurityMCPError) for cls in classes)


def test_validation_error_includes_per_error_message_in_str() -> None:
    details = {
        "errors": [
            {
                "code": "invalid_restriction",
                "message": "Invalid restriction 'IGNORE' for category 'Social Media'",
            }
        ]
    }
    err = FlightdeckValidationError(details=details)

    rendered = str(err)
    assert "Flightdeck rejected the request as invalid" in rendered
    assert "Invalid restriction 'IGNORE' for category 'Social Media'" in rendered
    # The details block round-trips as JSON so the agent can parse and reason
    # about the failure.
    assert "Details: " in rendered
    payload = rendered.split("Details: ", 1)[1]
    assert json.loads(payload) == details


def test_validation_error_includes_multiple_detail_messages() -> None:
    details = {
        "errors": [
            {"message": "Invalid restriction 'IGNORE' for category 'A'"},
            {"detail": "Invalid restriction 'IGNORE' for category 'B'"},
        ]
    }
    err = FlightdeckValidationError(details=details)

    msg = err.normalized.message
    assert "category 'A'" in msg
    assert "category 'B'" in msg


def test_error_str_omits_details_block_when_no_details() -> None:
    err = FlightdeckValidationError("custom message")
    assert str(err) == "custom message"


def test_error_does_not_double_append_when_message_already_has_detail() -> None:
    details = {"errors": [{"message": "duplicate"}]}
    err = AssignmentConflictError("alice already assigned: duplicate", details=details)

    assert err.normalized.message == "alice already assigned: duplicate"


def test_error_handles_top_level_message_envelope() -> None:
    details = {"message": "Policy 'X' is currently inherited from base"}
    err = FlightdeckValidationError(details=details)

    assert "Policy 'X' is currently inherited from base" in err.normalized.message


def test_error_handles_non_serializable_details() -> None:
    class Weird:
        def __repr__(self) -> str:
            return "<weird>"

    details = {"errors": [{"message": "boom"}], "obj": Weird()}
    err = FlightdeckValidationError(details=details)

    rendered = str(err)
    assert "boom" in rendered
    assert "Details: " in rendered


async def test_error_message_reaches_tool_caller() -> None:
    server = MCPServer("test")

    @server.tool(name="fails")
    async def fails() -> str:
        raise FlightdeckAuthenticationError(
            "Flightdeck rejected the client credentials (status 401)",
            details={"error": "invalid_client"},
        )

    with pytest.raises(ToolError, match="invalid_client"):
        await server.call_tool("fails", {})
