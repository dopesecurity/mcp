"""Tests for the server-level operating instructions."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from dopesecurity.mcp_server.config import DEFAULT_BASE_URL, Settings
from dopesecurity.mcp_server.instructions import INSTRUCTIONS
from dopesecurity.mcp_server.server import create_server


def _settings(*, enable_mutations: bool = False) -> Settings:
    return Settings.model_construct(
        _fields_set=None,
        client_id="test-client",
        client_secret=SecretStr("test-secret"),
        enable_mutations=enable_mutations,
        timeout_seconds=30.0,
        log_level="INFO",
        token_refresh_skew_seconds=60.0,
        api_base_url=DEFAULT_BASE_URL,
    )


@pytest.mark.parametrize("enable_mutations", [False, True])
def test_server_advertises_instructions(enable_mutations: bool) -> None:
    server = create_server(_settings(enable_mutations=enable_mutations))
    assert server.instructions == INSTRUCTIONS


def test_instructions_cover_the_key_rules() -> None:
    for needle in (
        "NEVER MAKE CHANGES WITHOUT EXPLICIT INSTRUCTION",
        "INVESTIGATE BEFORE DIAGNOSING ALLOW/BLOCK BEHAVIOR",
        "PREFER NARROW WRITES",
        "PAGINATION",
        "page_info.end_cursor",
        "POLICY PRECEDENCE",
        "add an exception for that principal",
    ):
        assert needle in INSTRUCTIONS, needle
