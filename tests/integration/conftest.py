"""Pytest fixtures for the MCP deterministic integration suite.

These tests talk to the dedicated `apac.acme.test` sandbox tenant on the
internal Flightdeck environment and mutate state. They run unconditionally
whenever the test path is collected — there is no opt-in flag.

Required environment:

    DOPE_MCP_TESTS_CLIENT_SECRET=<oauth client secret for apac.acme.test>

Run them with:

    DOPE_MCP_TESTS_CLIENT_SECRET=... uv run pytest tests/integration

If the secret is missing, every test fails with a clear hint pointing at
the team password manager. If the secret is wrong, tools fail with a
401 `invalid_client` ToolError that is annotated with the same hint.

Tests open the MCP harness themselves with `async with integration(cfg)`
to keep the stdio_client / ClientSession lifecycle in a single asyncio
task (otherwise anyio raises "cancel scope in a different task" during
fixture teardown).
"""

from __future__ import annotations

import pytest

from .harness import IntegrationConfig, MissingCredentialsError


@pytest.fixture(scope="session")
def integration_config() -> IntegrationConfig:
    try:
        return IntegrationConfig.from_env()
    except MissingCredentialsError as exc:
        pytest.fail(str(exc), pytrace=False)
