"""Thin async wrapper around an MCP ClientSession for integration tests.

The harness spawns the local `dopesecurity-mcp-server` over stdio (with
mutations enabled) configured for the dedicated apac.acme.test tenant on
the internal Flightdeck environment, exposes a typed `call_tool` that
returns parsed JSON, and tracks created tenant objects so tests can be
self-cleaning even on failure.

These tests REQUIRE the apac.acme.test tenant. Running them against any
other tenant will mutate state on that tenant and probably fail.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import structlog
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

log = structlog.get_logger("dopemcp.integration.harness")


# ---------------------------------------------------------------------------
# Hardcoded tenant configuration
#
# These tests target a single shared sandbox tenant (apac.acme.test on the
# internal Flightdeck environment). They are intentionally NOT configurable
# per environment: we want every developer and every CI run to hit the same
# data so scenarios stay reproducible and the cleanup contract holds.
# ---------------------------------------------------------------------------

TENANT_BASE_URL = "https://api.flightdeck.internal.swg.ai/v1"
TENANT_NAME = "apac.acme.test"
TENANT_CLIENT_ID = "e481a103408a981615ea4117ab3781f2"
TENANT_CLIENT_SECRET_ENV = "DOPE_MCP_TESTS_CLIENT_SECRET"
TEST_USER_EMAIL = "dope@pb7q.onmicrosoft.com"
TEST_GROUP_EMAIL = "Retail@pb7q.onmicrosoft.com"

CRED_HINT = (
    f"Set {TENANT_CLIENT_SECRET_ENV} to the OAuth client secret for the "
    f"{TENANT_NAME} sandbox tenant (client id {TENANT_CLIENT_ID}) on the "
    f"internal Flightdeck environment ({TENANT_BASE_URL}). The secret is "
    f"shared in the team password manager."
)


class MissingCredentialsError(RuntimeError):
    """Raised when the tenant client secret is not in the environment."""


class ToolError(RuntimeError):
    """Raised when an MCP tool call returns isError=True."""

    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message


@dataclass(frozen=True)
class IntegrationConfig:
    client_secret: str
    base_url: str = TENANT_BASE_URL
    client_id: str = TENANT_CLIENT_ID
    log_level: str = "WARNING"
    test_user_email: str = TEST_USER_EMAIL
    test_group_email: str = TEST_GROUP_EMAIL

    @classmethod
    def from_env(cls) -> IntegrationConfig:
        secret = os.environ.get(TENANT_CLIENT_SECRET_ENV)
        if not secret:
            raise MissingCredentialsError(
                f"{TENANT_CLIENT_SECRET_ENV} is not set. {CRED_HINT}"
            )
        return cls(
            client_secret=secret,
            log_level=os.environ.get("DOPE_LOG_LEVEL", "WARNING"),
        )

    def server_env(
        self,
        *,
        enable_mutations: bool = True,
        enable_destructive: bool = True,
    ) -> dict[str, str]:
        return {
            "DOPE_CLIENT_ID": self.client_id,
            "DOPE_CLIENT_SECRET": self.client_secret,
            "DOPE_BASE_URL": self.base_url,
            "DOPE_ENABLE_MUTATIONS": "true" if enable_mutations else "false",
            "DOPE_ENABLE_DESTRUCTIVE": "true" if enable_destructive else "false",
            "DOPE_LOG_LEVEL": self.log_level,
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        }


@dataclass
class Cleaner:
    """Tracks objects created by a test so they can be torn down at the end.

    Cleanup is best-effort: failures are logged and swallowed so a single
    teardown error never masks the underlying test failure.
    """

    mcp: McpHarness
    policies: list[str] = field(default_factory=list)
    custom_categories: list[str] = field(default_factory=list)

    def track_policy(self, name: str) -> None:
        self.policies.append(name)

    def track_custom_category(self, name: str) -> None:
        self.custom_categories.append(name)

    async def run(self) -> None:
        for name in reversed(self.policies):
            try:
                await self.mcp.call("delete_policy", {"policy_name": name})
            except Exception as exc:  # noqa: BLE001
                log.warning("cleanup.delete_policy.failed", name=name, error=str(exc))
        for name in reversed(self.custom_categories):
            try:
                await self.mcp.call(
                    "delete_custom_category",
                    {"custom_category_name": name},
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "cleanup.delete_custom_category.failed",
                    name=name,
                    error=str(exc),
                )


@dataclass
class McpHarness:
    """Wraps an open MCP ClientSession with helpers for the dope tools."""

    session: ClientSession
    config: IntegrationConfig

    async def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Call a tool and return its structuredContent dict.

        Raises `ToolError` if the server reports `isError=True`. If the
        underlying error looks like a credential rejection, the message
        is augmented with the credential hint to make triage easier.
        """
        result = await self.session.call_tool(name, dict(arguments or {}))
        if result.isError:
            text = _extract_text(result.content) or "tool reported isError without text"
            if "invalid_client" in text or "client credentials" in text:
                text = f"{text}\n\n{CRED_HINT}"
            raise ToolError(name, text)
        if result.structuredContent is None:
            raise AssertionError(
                f"tool {name} returned no structuredContent; got content={result.content!r}"
            )
        return result.structuredContent

    async def list_tool_names(self) -> set[str]:
        listed = await self.session.list_tools()
        return {t.name for t in listed.tools}

    async def list_all_policy_names(self) -> set[str]:
        names: set[str] = set()
        cursor: str | None = None
        while True:
            args: dict[str, Any] = {}
            if cursor is not None:
                args["after"] = cursor
            page = await self.call("list_policies", args)
            for p in page.get("policies", []):
                names.add(p["policy_name"])
            page_info = page.get("page_info") or {}
            if not page_info.get("has_next_page"):
                break
            cursor = page_info.get("end_cursor")
            if not cursor:
                break
        return names

    async def list_all_custom_category_names(self) -> set[str]:
        names: set[str] = set()
        cursor: str | None = None
        while True:
            args: dict[str, Any] = {}
            if cursor is not None:
                args["after"] = cursor
            page = await self.call("list_custom_categories", args)
            for c in page.get("custom_categories", []):
                names.add(c["name"])
            page_info = page.get("page_info") or {}
            if not page_info.get("has_next_page"):
                break
            cursor = page_info.get("end_cursor")
            if not cursor:
                break
        return names


def _extract_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def make_tag(scenario: str) -> str:
    """Build a unique, recognizable name prefix for objects created in a test."""
    return f"mcp-it-{scenario}-{uuid.uuid4().hex[:8]}"


@asynccontextmanager
async def open_harness(
    config: IntegrationConfig,
    *,
    enable_mutations: bool = True,
    enable_destructive: bool = True,
) -> AsyncIterator[McpHarness]:
    """Spawn the local MCP server and yield a connected harness."""

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "dopesecurity.mcp_server"],
        env=config.server_env(
            enable_mutations=enable_mutations,
            enable_destructive=enable_destructive,
        ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield McpHarness(session=session, config=config)


@asynccontextmanager
async def integration(
    config: IntegrationConfig,
) -> AsyncIterator[tuple[McpHarness, Cleaner]]:
    """Open a harness AND a tracked cleaner in a single task.

    Tests use this directly to avoid the anyio cross-task cancel-scope
    issue that triggers when stdio_client's setup and teardown run in
    different pytest-asyncio fixture tasks.
    """
    async with open_harness(config) as mcp:
        cleaner = Cleaner(mcp=mcp)
        try:
            yield mcp, cleaner
        finally:
            await cleaner.run()
