# MCP Server Design

Last updated: 2026-04-30

## Overview

This document freezes the v1 design for a dope.security MCP server built on top of the Flightdeck partner API.

The goal is a local-first MCP server that customers can run via `uvx`, with a clean path to future remote deployment, while keeping the first release focused on tools and the Flightdeck domain rather than transport plumbing.

This is a design document only. It is not yet the implementation plan.

## Core Approach

- Use Python.
- Use the official MCP Python SDK with `MCPServer`.
- Run v1 over `stdio`.
- Distribute the server as `dopesecurity-mcp-server`.
- Expose tools only in v1.
- Keep `MCPServer` as a thin transport and tool-registration layer.
- Initialize shared dependencies once per process in the SDK lifespan hook and expose them through typed app context.
- Put Flightdeck-specific logic in a small service layer plus a wire-close API client.
- Keep the code structured so `streamable-http` can be added later without redesigning the tool layer.

## Packaging And Naming

- Distribution name: `dopesecurity-mcp-server`
- Console command: `dopesecurity-mcp-server`
- Python import package: `dopesecurity.mcp_server`

## Architecture

The implementation should stay thin and layered.

`MCPServer` should be the transport and tool-registration layer, not the place where business logic lives.
The server should use the official Python SDK lifespan pattern as its composition root: create shared dependencies once, yield a typed app context, and let tool handlers access that context from `ctx.request_context.lifespan_context`.

The first cut should have these layers:

- `settings`
  - environment parsing
  - CLI flag parsing
  - config validation
- `server`
  - `MCPServer` instance creation
  - lifespan hook
  - typed app context creation
  - tool module registration
- `auth`
  - client-credentials token exchange
  - token caching
  - token refresh
- `flightdeck_client`
  - HTTP request execution
  - request and response mapping
  - API error normalization
- `schemas`
  - MCP-facing input and output models
- `tools`
  - MCPServer tool registration
  - tool descriptions and annotations
  - derived tool behavior

The transport-specific bootstrap should stay isolated at the entrypoint.

The lifecycle and dependency model should be:

- one shared `httpx.AsyncClient` per process
- one dedicated `FlightdeckTokenManager` per process
- one typed app context yielded from lifespan
- domain services for `endpoints`, `policies`, and `custom_categories`

The API client is the data-access boundary for v1. We should not introduce a separate repository layer on top of it.

## Recommended Project Layout

Use a normal `src/` layout and keep the package shallow.

```text
pyproject.toml
src/dopesecurity/
  mcp_server/
    __init__.py
    __main__.py
    server.py
    config.py
    errors.py
    auth.py
    flightdeck/
      __init__.py
      client.py
      models.py
    services/
      __init__.py
      endpoints.py
      policies.py
      custom_categories.py
    tools/
      __init__.py
      endpoints.py
      policies.py
      custom_categories.py
```

Recommended responsibility split:

- `server.py`
  - create the `MCPServer` instance
  - define the lifespan hook
  - build the typed app context
  - register tool modules
  - expose a `create_server()` factory
- `__main__.py`
  - load settings
  - run the default local `stdio` server
- `config.py`
  - environment-backed settings and startup validation
- `auth.py`
  - Flightdeck token exchange, refresh, invalidation, and retry support
- `flightdeck/client.py`
  - raw HTTP calls, request construction, response parsing, and upstream error mapping
- `services/*.py`
  - workflow-oriented operations used by tools
- `tools/*.py`
  - MCP tool definitions grouped by domain

This is intentionally one layer shallower than a clean-architecture template. For this project, transport, services, and API client are enough.

## Lifespan Composition Pattern

The server should follow the official Python SDK lifespan pattern.

Recommended shape:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.mcpserver import MCPServer


@dataclass
class AppContext:
    settings: Settings
    token_manager: FlightdeckTokenManager
    flightdeck: FlightdeckClient
    endpoints: EndpointsService
    policies: PoliciesService
    custom_categories: CustomCategoriesService


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    settings = Settings()
    http = httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=settings.timeout_seconds,
    )
    token_manager = FlightdeckTokenManager(http=http, settings=settings)
    flightdeck = FlightdeckClient(http=http, token_manager=token_manager)
    try:
        yield AppContext(
            settings=settings,
            token_manager=token_manager,
            flightdeck=flightdeck,
            endpoints=EndpointsService(flightdeck),
            policies=PoliciesService(flightdeck),
            custom_categories=CustomCategoriesService(flightdeck),
        )
    finally:
        await http.aclose()
```

This keeps startup validation and shared resources in one place, gives a single connection pool for all tool calls, and works for local `stdio` now while still fitting a future HTTP transport.

## Layer Boundaries

### Tool Layer

The tool layer should own:

- MCP tool names and descriptions
- MCP-facing input schemas and field names
- lightweight translation from tool input to service calls
- lightweight translation from service results to MCP output models

The tool layer should not own:

- token exchange
- HTTP request construction
- read-modify-write logic against Flightdeck
- direct handling of raw Flightdeck error payloads

### Service Layer

The service layer should own:

- workflow semantics that are better expressed for agents than the raw REST API
- any read-modify-write logic needed to turn replace-style REST endpoints into safer MCP operations
- normalization between Flightdeck wire shapes and MCP-facing models
- domain rules around inheritance, mutation safety, and conflict handling

This is where the MCP becomes agent-friendly instead of acting like a raw API mirror.

### Flightdeck API Client Layer

The Flightdeck client layer should own:

- base URL handling
- request serialization and headers
- bearer token acquisition from the auth layer
- raw response parsing
- conversion of upstream HTTP failures into a small internal exception set

It should stay close to the partner API wire format. Normalization into MCP-facing shapes should happen below the tool layer, primarily in services and output models.

## Runtime Configuration

### Auth Configuration

Authentication values are env-only:

- `DOPE_CLIENT_ID`
- `DOPE_CLIENT_SECRET`

These should not be configurable through CLI flags or included in the sample `mcp.json`.

### Non-Secret Configuration

Non-secret runtime settings should be configurable in both places:

- environment variables
- CLI flags, so hosts can set them in `mcp.json`

The public non-secret settings are:

- mutation exposure
- HTTP timeout
- log level

The internal non-secret settings are:

- token refresh skew
- base URL override

Recommended env vars:

- `DOPE_ENABLE_MUTATIONS`
- `DOPE_TIMEOUT_SECONDS`
- `DOPE_LOG_LEVEL`

Recommended internal env vars:

- `DOPE_TOKEN_REFRESH_SKEW_SECONDS`
- `DOPE_BASE_URL`

Recommended CLI flags:

- `--enable-mutations`
- `--timeout-seconds`
- `--log-level`

Recommended internal CLI flags:

- `--token-refresh-skew-seconds`
- `--base-url`

### Internal-Only Base URL Override

The Flightdeck base URL should be configurable for internal and development use, but it should not be exposed in customer-facing documentation.

- Internal env var: `DOPE_BASE_URL`
- Internal CLI flag: `--base-url`

This override is supported so the server can target non-production environments, but the README and sample `mcp.json` should not advertise it.

### Settings Implementation

The settings layer should use `pydantic-settings`.

Recommended implementation choices:

- `BaseSettings` for environment-backed settings
- `SecretStr` for `DOPE_CLIENT_SECRET`
- `extra='forbid'` so misspelled config does not silently pass through
- `env_ignore_empty=True` so empty env vars do not masquerade as valid values

The public contract remains environment-first even if local development optionally supports `.env` loading.

### Defaults

- mutations disabled by default
- HTTP timeout default: `30` seconds
- log level default: `INFO`
- token refresh skew default: `60` seconds

## Token Lifecycle

The server manages Flightdeck bearer tokens internally through a dedicated `FlightdeckTokenManager` created in the lifespan context.

- Use one process-local token cache.
- Refresh when the token is within 60 seconds of expiry.
- Protect refresh with a lock so concurrent tool calls do not stampede the token endpoint.
- On a `401` from Flightdeck, do one forced refresh and one retry.
- If the retry fails, surface the upstream error.
- Never log tokens, auth headers, or client secrets.

This abstraction is justified because token refresh and invalidation are real shared concerns, not speculative layering.

## Logging And stdio Safety

- Never write non-protocol output to stdout.
- Log only to stderr.
- Keep default logs concise.
- Enable debug logging only when explicitly configured.
- Include tool name and request correlation identifiers where available.
- Do not log request bodies or response bodies if they may contain secrets or sensitive operational data.

Basic structured logs are enough for v1. Full tracing and audit infrastructure can wait for the remote deployment phase.

## Transport And Entrypoint Design

- `server.py` should expose `create_server()` so tests and alternate entrypoints can build the same server.
- `__main__.py` should run local `stdio` by default.
- A later remote entrypoint can call `mcp.run(transport="streamable-http")`.
- If the server is later mounted into Starlette or FastAPI, keep that in a separate ASGI entrypoint rather than mixing HTTP framework code into the default CLI.

## Tool Exposure And Mutation Gating

- Read tools are always registered.
- Write tools are registered only when mutations are enabled.
- Mutation exposure is controlled by config, not by the Flightdeck API.
- Even when write tools are exposed, Flightdeck may still reject calls with `403`.

Mutating tool descriptions should explicitly state that they modify tenant state.

## MCP Schema Conventions

### Inputs

- All MCP-facing input fields use snake_case.
- Path-derived identifiers use normal Python-style names.
- API-specific oddities should be normalized when it improves usability.

Examples:

- `policy_name`
- `custom_category_name`
- endpoint search API field `id` becomes MCP field `query`

### Outputs

- Strip the top-level API `data` wrapper.
- Convert all MCP-facing field names to snake_case.
- Preserve domain values exactly.
- Preserve important Flightdeck concepts explicitly.

Examples:

- `inherits_from_base`
- `custom`
- `default`
- `categories`
- `custom_categories`
- `page_info`
- `updated_at`
- `ssl_inspection`
- `clash_count`

### Dynamic Data Structures

Where the API uses object maps keyed by category names or principal identifiers, the MCP layer should prefer list-based schemas for writes and derived reads.

This improves model reliability and gives a more stable tool contract.

The API client may parse camelCase payloads from Flightdeck, but service results and MCP tool outputs should use snake_case consistently.

## v1 Tool Surface

### Policies

Read tools:

- `list_policies`
- `get_policy_assignments`
- `get_policy_restrictions`
- `get_policy_exceptions`
- `get_policy_url_bypass`
- `get_policy_application_bypass_entries`

Write tools:

- `create_policy`
- `delete_policy`
- `assign_policy_principals`
- `unassign_policy_principals`
- `update_policy_restrictions`
- `reset_policy_restrictions_to_base`
- `replace_policy_category_exceptions`
- `upsert_policy_url_bypass`
- `delete_policy_url_bypass_entries`
- `reset_policy_url_bypass_to_base`
- `upsert_policy_application_bypass`
- `reset_policy_application_bypass_to_base`

### Endpoints

Read tools:

- `search_endpoints`

### Custom Categories

Read tools:

- `list_custom_categories`
- `get_custom_category_urls`

Write tools:

- `create_custom_category`
- `delete_custom_category`
- `add_urls_to_custom_category`
- `delete_all_urls_from_custom_category`
- `delete_single_url_from_custom_category`

## Tool Behavior Decisions

### `search_endpoints`

- Supports pagination with `first`, `after`, and `order`.
- Accepts zero or one search or filter field.
- Zero search fields means list all endpoints.
- More than one search or filter field is rejected before calling Flightdeck.

Allowed search or filter fields:

- `query`
- `email_id`
- `device_name`
- `user_id`
- `os_version`
- `status`
- `debug_state`
- `fallback_mode`
- `location_id`
- `agent_version`

### `assign_policy_principals`

This is a derived convenience tool.

Input:

- `policy_name`
- optional `user_emails`
- optional `group_emails`

Behavior:

- read current assignments
- merge the supplied principals into the current assignment set
- de-duplicate
- write back the full assignment set

This tool is non-atomic and best-effort.

### `unassign_policy_principals`

This is a derived convenience tool.

Input:

- `policy_name`
- optional `user_emails`
- optional `group_emails`

Behavior:

- read current assignments
- remove the supplied principals
- ignore missing principals
- write back the full assignment set

This tool is non-atomic and best-effort.

### `get_policy_assignments`

Output:

- `users`
- `groups`

Each user contains:

- `email`
- `name`

Each group contains:

- `email`
- `name`
- `members_count`

### `get_policy_restrictions`

This is a derived read view over the policy content API.

Output:

- `categories`
  - `inherits_from_base`
  - `items`
- `custom_categories`
  - `inherits_from_base`
  - `items`

Each standard category item contains:

- `name`
- `restriction`
- optional `page`
- optional `description`

Each custom category item contains:

- `name`
- `restriction`
- optional `page`

No exceptions are included in this tool.

### `get_policy_exceptions`

This is a derived read view over the policy content API.

Output:

- `categories`
  - `inherits_from_base`
  - `items`
- `custom_categories`
  - `inherits_from_base`
  - `items`

Each category item contains:

- `name`
- `exceptions`

Each exception item contains:

- `principal`
- `restriction`
- optional `page`
- optional `name`
- optional `principal_type`

The MCP field `principal_type` is normalized from the API field `type`.

### `update_policy_restrictions`

This uses list-based MCP input rather than API object maps.

Input:

- `policy_name`
- optional `categories`
- optional `custom_categories`

Each `categories` item contains:

- `name`
- `restriction`
- optional `page`

Each `custom_categories` item contains:

- `name`
- `restriction`
- optional `page`

Only submitted categories are updated.
Omitted categories remain unchanged.

### `reset_policy_restrictions_to_base`

Input:

- `policy_name`
- `scope`

Allowed scope values:

- `categories`
- `custom_categories`
- `both`

### `replace_policy_category_exceptions`

This uses list-based MCP input.

Input:

- `policy_name`
- optional `categories`
- optional `custom_categories`

Each category item contains:

- `name`
- `exceptions`

Each exception contains:

- `principal`
- `restriction`
- optional `page`

Behavior:

- replacement is per submitted category only
- categories not included in the request remain unchanged
- an empty exception list clears all exceptions for that category

Tool descriptions should state clearly that this is per-category replacement, not whole-policy replacement.

### URL Bypass Tools

`get_policy_url_bypass` returns:

- `inherits_from_base`
- `custom`
- `default`

Each `custom` item contains:

- `name`
- optional `note`
- optional `updated_by`
- optional `updated_at`

Each `default` item contains:

- `name`
- `state`

`upsert_policy_url_bypass` accepts:

- `policy_name`
- optional `custom`
- optional `default`

`reset_policy_url_bypass_to_base` accepts:

- `policy_name`

`delete_policy_url_bypass_entries` accepts:

- `policy_name`
- `names`

Tool descriptions must explicitly explain the difference between `custom` and `default` entries.

### Application Bypass Tools

`get_policy_application_bypass_entries` returns:

- `inherits_from_base`
- `custom`
  - `mac`
  - `windows`
- `default`
  - `mac`
  - `windows`

`upsert_policy_application_bypass` accepts the same shape.

`reset_policy_application_bypass_to_base` accepts:

- `policy_name`

Known v1 limitation:

- the current tool list does not include per-entry deletion for custom application bypass entries
- if the underlying API remains unchanged, removing stale entries may require reset-to-base or overwrite-style behavior supported by the upsert semantics

This limitation should be documented.

### Custom Category Tools

`list_custom_categories` returns:

- `custom_categories`
- `page_info`

`get_custom_category_urls` returns:

- `urls`

`add_urls_to_custom_category` accepts:

- `custom_category_name`
- `urls`

`delete_all_urls_from_custom_category` accepts:

- `custom_category_name`

`delete_single_url_from_custom_category` accepts:

- `custom_category_name`
- `url`

The server should URL-encode the single URL internally before calling Flightdeck.

## Error Contract

The error model should have two levels: upstream normalization and tool-facing presentation.

Recommended internal exception set at the Flightdeck client boundary:

- `FlightdeckAuthenticationError`
- `FlightdeckAuthorizationError`
- `FlightdeckNotFoundError`
- `FlightdeckValidationError`
- `FlightdeckConflictError`
- `FlightdeckServerError`
- `FlightdeckTransportError`

The service layer may raise more specific domain errors when that improves tool UX, such as:

- `PolicyNotFoundError`
- `AssignmentConflictError`
- `InheritedPolicyMutationError`
- `InvalidPrincipalError`

Tool-boundary input validation failures (Pydantic `ValidationError` from a tool's input model) are raised as `InvalidToolInputError` (code `invalid_input`).

Tool failures should present a predictable normalized shape internally:

- `code`
- `message`
- optional `details`

The MCP layer should surface:

- concise top-level error messages
- structured details when the Flightdeck API provides them

Important cases to preserve in `details`:

- assignment conflicts
- invalid exception principals
- inheriting-policy delete restrictions
- invalid URL lists

The base `DopesecurityMCPError` subclasses `ToolError` from `mcp.server.mcpserver.exceptions`. `MCPServer` surfaces `str(exc)` only for `ToolError`; any other exception is reduced to a generic "Error executing tool <name>", so every user-meaningful failure must derive from the base error.

Expected business failures should become concise agent-safe tool errors. MCP protocol errors should be reserved for actual protocol or transport faults.

## Customer-Facing Documentation Scope

The README and sample `mcp.json` should include:

- install via `uvx dopesecurity-mcp-server`
- auth env vars
- mutation gating
- log level and timeout configuration
- sample `mcp.json`
- read-only by default behavior
- known v1 limitation around application bypass entry deletion

The README and sample `mcp.json` should not document the internal base URL override.

## Out Of Scope

- remote HTTP transport
- MCP transport auth
- resources and prompts
- pagination convenience helpers such as `fetch_all`
- tools outside the exact approved v1 list
- speculative parity tools not yet approved

## Status

This design is approved enough to use as the basis for planning, but planning has not started yet.
