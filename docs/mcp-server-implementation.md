# Plan: dope.security MCP Server Implementation

## Overview

Build the v1 dope.security MCP server described in `docs/mcp-server-design.md` from an empty implementation repository. The first implementation should bootstrap a Python `src/` project, package it as `dopesecurity-mcp-server`, expose a `dopesecurity-mcp-server` console command, and run a local `stdio` MCPServer server backed by the Flightdeck partner API in `docs/partner_api.yaml`.

The implementation should keep MCPServer thin: configuration, auth, HTTP execution, domain workflows, MCP schemas, and tool registration live in separate modules. Read tools are always available; mutating tools are registered only when explicitly enabled by configuration.

## Success Criteria

Done means all of the following are true:

- The repository has a working Python package under `src/dopesecurity/mcp_server` with the console command `dopesecurity-mcp-server`.
- `uv run dopesecurity-mcp-server --help` works from the repository root and writes no non-protocol runtime output to stdout during normal server operation.
- The MCPServer server registers the exact v1 tool surface from `docs/mcp-server-design.md`; write tools are absent unless mutations are enabled.
- Flightdeck auth uses `DOPE_CLIENT_ID` and `DOPE_CLIENT_SECRET` from the environment only, caches bearer tokens, refreshes near expiry, and retries one request after a `401` forced refresh.
- Flightdeck HTTP errors are normalized into the internal error set described in the design document, preserving useful upstream `details` where present.
- Services implement the agent-friendly behavior described in the design document: endpoint single-filter validation, policy assignment merge/remove workflows, policy content derived reads, per-submitted-category restriction/exception updates, bypass inheritance reset, and custom category URL encoding.
- Customer-facing docs include `uvx dopesecurity-mcp-server`, required auth env vars, mutation gating, public configuration, sample `mcp.json`, read-only default behavior, and the known application bypass deletion limitation. Customer-facing docs do not document the internal base URL override.
- Verification from the repository root passes:

```sh
uv run pytest src
uv run ruff check .
uv run mypy src
```

## Design Decisions

- **Package manager/build:** use `uv` with a standard `pyproject.toml` and `hatchling` build backend. This matches the desired `uvx` distribution model and keeps bootstrap minimal.
- **Python version:** require Python `>=3.11` to support modern typing while keeping broad compatibility.
- **Tests live under `src`:** place tests in `src/dopesecurity/mcp_server/tests/` so the repo-standard command `uv run pytest src` discovers them.
- **Settings:** use `pydantic-settings` with env-backed settings plus a CLI override object. Secrets remain env-only and are never CLI flags.
- **Logging:** use `structlog` configured to stderr. Tests should use `structlog.get_logger()` rather than mocking logs, and should not assert log lines.
- **HTTP tests:** use `httpx.MockTransport` for unit tests instead of a live Flightdeck dependency.
- **Models:** keep wire-close Flightdeck models in `flightdeck/models.py` and MCP-facing/service models in `schemas.py`. The API client may accept/return typed dict-like JSON where full wire models would add unnecessary ceremony, but MCP-facing outputs must be snake_case Pydantic models.
- **Tool errors:** expected business/upstream failures are raised as concise tool errors with normalized messages/details. Protocol errors are not used for normal Flightdeck business failures.

## Out of Scope / Non-goals

- No remote `streamable-http` transport or ASGI app.
- No MCP transport authentication.
- No resources or prompts.
- No pagination convenience helper that fetches all pages.
- No tools outside the exact approved v1 list.
- No repository layer on top of the Flightdeck API client.
- No customer documentation for `DOPE_BASE_URL` or `--base-url`.
- No logging of bearer tokens, auth headers, request bodies, response bodies, client secrets, or user-provided secrets.

## Tasks

### Task 1: Bootstrap Python package, tooling, and test skeleton

**Files:** `pyproject.toml`, `README.md`, `src/dopesecurity/__init__.py`, `src/dopesecurity/mcp_server/__init__.py`, `src/dopesecurity/mcp_server/__main__.py`, `src/dopesecurity/mcp_server/py.typed`, `src/dopesecurity/mcp_server/tests/__init__.py`, `.gitignore`

**Depends on:** none

**Reference files:** `docs/mcp-server-design.md`, `docs/mcp-research.md`

#### Goal

Create the project foundation for a Python MCP package that can be installed and run with `uv`, while leaving business logic for later tasks.

#### Success criteria

- `pyproject.toml` defines project name `dopesecurity-mcp-server`, console script `dopesecurity-mcp-server = "dopesecurity.mcp_server.__main__:main"`, and package source under `src/`.
- Runtime dependencies include `mcp`, `httpx`, `pydantic`, `pydantic-settings`, and `structlog`.
- Dev dependencies include `pytest`, `pytest-asyncio`, `ruff`, and `mypy`.
- `README.md` has a short placeholder stating implementation is in progress; final customer docs are completed in a later task.
- `src/dopesecurity/mcp_server/__main__.py` exposes a synchronous `main(argv: Sequence[str] | None = None) -> int` that can be called by the console script and currently supports `--help` without starting the server.
- `uv run dopesecurity-mcp-server --help` exits successfully from the repository root.
- Verification commands pass from the repository root.

#### Constraints / non-goals

- Do not implement Flightdeck auth, clients, services, or tools in this task.
- Do not add remote transport dependencies.
- Do not place tests outside `src/`.
- Do not add customer-facing configuration examples yet beyond a short placeholder.

#### Spec

- Add `pyproject.toml` with:
  - `[project] name = "dopesecurity-mcp-server"`
  - initial version `0.1.0`
  - `requires-python = ">=3.11"`
  - script entry under `[project.scripts]`
  - `hatchling` build backend and package discovery for `src/dopesecurity`
  - Ruff configuration targeting Python 3.11 and source roots `src`
  - mypy configuration with `python_version = "3.11"`, `strict = true`, and package target `dopesecurity.mcp_server`
  - pytest configuration with `testpaths = ["src"]` and `asyncio_mode = "auto"`
- Add `.gitignore` entries for `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `dist/`, `*.egg-info/`, and `__pycache__/`.
- Add a minimal package with `__all__` where appropriate and `py.typed`.
- Implement `main()` using `argparse.ArgumentParser` with the program name `dopesecurity-mcp-server`; actual server startup is added in Task 4.

#### Tests

- Add a test module under `src/dopesecurity/mcp_server/tests/test_main.py` with:
  - `test_main_help_exits_successfully`: call `main(["--help"])`, expect `SystemExit` with code `0` or adapt `main` to return `0`; do not assert stdout content beyond successful behavior.

#### Verification

```sh
uv run pytest src
uv run ruff check .
uv run mypy src
uv run dopesecurity-mcp-server --help
```

### Task 2: Implement configuration, CLI overrides, logging, and normalized errors

**Files:** `src/dopesecurity/mcp_server/config.py`, `src/dopesecurity/mcp_server/errors.py`, `src/dopesecurity/mcp_server/__main__.py`, `src/dopesecurity/mcp_server/tests/test_config.py`, `src/dopesecurity/mcp_server/tests/test_errors.py`

**Depends on:** Task 1

**Reference files:** `docs/mcp-server-design.md`, `docs/mcp-research.md`

#### Goal

Implement startup configuration and error primitives shared by later auth/client/server work.

#### Success criteria

- Required secrets are read only from `DOPE_CLIENT_ID` and `DOPE_CLIENT_SECRET`.
- Public non-secret settings are configurable through env vars and CLI flags: mutation exposure, timeout seconds, and log level.
- Internal settings are supported through env vars and CLI flags but not documented in README in this task: token refresh skew and base URL.
- Empty env vars are ignored where appropriate; misspelled settings are rejected by Pydantic settings configuration.
- Logging is configured to stderr with `structlog`, and runtime code does not print non-protocol output to stdout.
- Internal exception classes match the design document's Flightdeck and domain error contract.
- Verification commands pass from the repository root.

#### Constraints / non-goals

- Do not accept client ID or client secret as CLI flags.
- Do not log or render secret values.
- Do not implement HTTP calls or MCP tools in this task.
- Do not add README customer examples for internal settings.

#### Spec

- In `config.py`, define:
  - `LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]` or an equivalent enum accepted by Pydantic.
  - `CliConfigOverrides` dataclass with optional fields: `enable_mutations: bool | None`, `timeout_seconds: float | None`, `log_level: str | None`, `token_refresh_skew_seconds: float | None`, `base_url: str | None`.
  - `Settings(BaseSettings)` with fields:
    - `client_id: str` mapped from `DOPE_CLIENT_ID`
    - `client_secret: SecretStr` mapped from `DOPE_CLIENT_SECRET`
    - `enable_mutations: bool = False` mapped from `DOPE_ENABLE_MUTATIONS`
    - `timeout_seconds: float = 30.0` mapped from `DOPE_TIMEOUT_SECONDS`, must be `> 0`
    - `log_level: LogLevel = "INFO"` mapped from `DOPE_LOG_LEVEL`
    - `token_refresh_skew_seconds: float = 60.0` mapped from `DOPE_TOKEN_REFRESH_SKEW_SECONDS`, must be `>= 0`
    - `api_base_url: str = "https://api.flightdeck.dope.security/v1"` mapped from `DOPE_BASE_URL`
  - `model_config = SettingsConfigDict(env_ignore_empty=True, extra="forbid")` or equivalent.
  - `load_settings(overrides: CliConfigOverrides | None = None) -> Settings` that applies CLI overrides after env parsing without allowing secret overrides.
  - `configure_logging(log_level: str) -> None` that configures `structlog` and standard logging to stderr.
- In `__main__.py`, extend argparse with:
  - `--enable-mutations` as a boolean flag
  - `--timeout-seconds FLOAT`
  - `--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}`
  - internal but supported flags `--token-refresh-skew-seconds FLOAT` and `--base-url URL`
  - no secret flags
- In `errors.py`, define:
  - `NormalizedError(code: str, message: str, details: Any | None = None)` as a dataclass or Pydantic model.
  - Base `DopesecurityMCPError(ToolError)` (from `mcp.server.mcpserver.exceptions`) with a `normalized: NormalizedError` property. Subclassing `ToolError` is what makes `MCPServer` surface the message to the caller.
  - Flightdeck boundary exceptions: `FlightdeckAuthenticationError`, `FlightdeckAuthorizationError`, `FlightdeckNotFoundError`, `FlightdeckValidationError`, `FlightdeckConflictError`, `FlightdeckServerError`, `FlightdeckTransportError`.
  - Domain exceptions: `PolicyNotFoundError`, `AssignmentConflictError`, `InheritedPolicyMutationError`, `InvalidPrincipalError`, `InvalidToolInputError` (tool-boundary Pydantic validation failures), plus a general `MutationDisabledError` if useful for service/tool guards.
  - `to_tool_error(error: Exception) -> NormalizedError` that converts known errors to normalized shape and unknown errors to a concise internal error without leaking internals.

#### Tests

- `test_settings_loads_required_env_and_defaults`: set required env vars with pytest `monkeypatch`; assert defaults from design.
- `test_settings_rejects_missing_credentials`: clear required env vars; assert validation fails with a message that names missing variables but does not include secret values.
- `test_cli_overrides_non_secret_settings`: env has defaults, overrides set mutations/timeout/log/skew/base URL; assert result reflects overrides.
- `test_secret_cannot_be_set_from_cli`: assert `CliConfigOverrides` has no secret fields and parser rejects unknown secret args.
- `test_empty_env_values_are_ignored`: empty optional env vars do not override defaults.
- `test_to_tool_error_preserves_details_for_known_errors`: create a known error with details; assert code/message/details are retained.

#### Verification

```sh
uv run pytest src -k 'config or errors or main'
uv run ruff check .
uv run mypy src
```

### Task 3: Implement Flightdeck token manager and HTTP API client

**Files:** `src/dopesecurity/mcp_server/auth.py`, `src/dopesecurity/mcp_server/flightdeck/__init__.py`, `src/dopesecurity/mcp_server/flightdeck/client.py`, `src/dopesecurity/mcp_server/flightdeck/models.py`, `src/dopesecurity/mcp_server/tests/test_auth.py`, `src/dopesecurity/mcp_server/tests/test_flightdeck_client.py`

**Depends on:** Task 2

**Reference files:** `docs/mcp-server-design.md`, `docs/partner_api.yaml`

#### Goal

Create the wire-close Flightdeck boundary: token exchange/caching/refresh and authenticated HTTP request execution with normalized upstream errors.

#### Success criteria

- Token exchange calls `POST /partner/oauth/token` with JSON `grant_type=client_credentials`, `client_id`, and `client_secret`.
- Tokens are cached until they are within `token_refresh_skew_seconds` of expiry.
- Concurrent token refreshes are protected by an async lock so simultaneous requests do not stampede the token endpoint.
- Authenticated Flightdeck requests include `Authorization: Bearer <token>`.
- A `401` response invalidates the cached token, forces one refresh, and retries the original request once.
- HTTP `401`, `403`, `404`, validation-style `400`, conflict-style `409`/assignment conflict payloads, `5xx`, and transport failures map to the internal exception set from Task 2.
- API response parsing strips no data at the client boundary unless the method contract explicitly says so; normalization into MCP-facing shape remains in services.
- Verification commands pass from the repository root.

#### Constraints / non-goals

- Do not add a repository layer.
- Do not implement service-level workflow behavior in the client.
- Do not log request bodies, response bodies, auth headers, bearer tokens, or client secrets.
- Do not call real Flightdeck in tests.

#### Spec

- In `flightdeck/models.py`, define small wire/client models as needed, including:
  - `TokenResponse(access_token: str, token_type: str, expires_in: float)`
  - `PageInfo(end_cursor: str | None = None, has_next_page: bool = False)` with aliases for `endCursor` if using Pydantic.
  - type aliases for `JsonObject = dict[str, Any]` and `JsonValue` if useful.
- In `auth.py`, define `CachedToken` and `FlightdeckTokenManager`:
  - constructor: `__init__(self, http: httpx.AsyncClient, settings: Settings, logger: structlog.stdlib.BoundLogger | None = None)`
  - `async def get_token(self, *, force_refresh: bool = False) -> str`
  - `def invalidate(self) -> None`
  - internal expiry uses `time.monotonic()` plus `expires_in` minus skew.
  - token response must have `token_type` equal to `bearer` case-insensitively.
- In `flightdeck/client.py`, define `FlightdeckClient`:
  - constructor: `__init__(self, http: httpx.AsyncClient, token_manager: FlightdeckTokenManager)`
  - generic `async def request(self, method: str, path: str, *, params: Mapping[str, Any] | None = None, json: Any | None = None) -> Any`
  - endpoint-specific methods matching `docs/partner_api.yaml` paths:
    - `search_endpoints(params: Mapping[str, Any])`
    - `list_policies(params: Mapping[str, Any])`
    - `create_policy(policy_name: str)`
    - `delete_policy(policy_name: str)`
    - `get_policy_content(policy_name: str)`
    - `update_policy_content_restrictions(policy_name: str, body: Mapping[str, Any])`
    - `update_policy_content_exceptions(policy_name: str, body: Mapping[str, Any])`
    - `get_policy_assignments(policy_name: str)`
    - `update_policy_assignments(policy_name: str, body: Mapping[str, Any])`
    - `get_policy_url_bypass(policy_name: str)`
    - `upsert_policy_url_bypass(policy_name: str, body: Mapping[str, Any])`
    - `delete_policy_url_bypass_entries(policy_name: str, names: Sequence[str])`
    - `get_policy_application_bypass(policy_name: str)`
    - `upsert_policy_application_bypass(policy_name: str, body: Mapping[str, Any])`
    - `list_custom_categories(params: Mapping[str, Any])`
    - `create_custom_category(custom_category_name: str)`
    - `delete_custom_category(custom_category_name: str)`
    - `get_custom_category_urls(custom_category_name: str)`
    - `add_urls_to_custom_category(custom_category_name: str, urls: Sequence[str])`
    - `delete_all_urls_from_custom_category(custom_category_name: str)`
    - `overwrite_custom_category_urls` (`PUT /custom_categories/{name}/urls`) was **not shipped at all** — neither as a client method nor as an MCP tool — to keep the URL-mutation surface limited to explicit add/remove/upsert semantics.
    - `delete_single_url_from_custom_category(custom_category_name: str, encoded_url: str)`
  - URL path variables must be URL-encoded by the client or by a private helper, except `encoded_url` is passed already encoded from the custom category service.
  - Upstream error details should be extracted from common Flightdeck shapes in `docs/partner_api.yaml` (`errors`, `message`, `details`, OAuth error fields) and attached to the normalized exception.

#### Tests

- `test_token_manager_exchanges_client_credentials`: mock token endpoint, assert request body has grant type/client ID/client secret and returned token is used.
- `test_token_manager_reuses_unexpired_token`: two `get_token()` calls produce one token request.
- `test_token_manager_refreshes_inside_skew`: token with short expiry/skew triggers refresh.
- `test_token_manager_serializes_concurrent_refresh`: concurrent `get_token()` calls share one token request.
- `test_client_adds_bearer_header`: mock API endpoint and assert bearer header is present.
- `test_client_retries_once_after_401`: first API response `401`, second succeeds; assert token forced refresh happened once.
- `test_client_maps_status_codes_to_errors`: parameterized status/payload cases for 400/401/403/404/409/500.
- `test_client_maps_transport_error`: mock transport raises `httpx.TransportError`; assert `FlightdeckTransportError`.
- `test_client_encodes_policy_path_segments`: policy name with space is encoded in path.

#### Verification

```sh
uv run pytest src -k 'auth or flightdeck_client'
uv run ruff check .
uv run mypy src
```

### Task 4: Implement MCPServer server composition and mutation-gated registration hooks

**Files:** `src/dopesecurity/mcp_server/server.py`, `src/dopesecurity/mcp_server/__main__.py`, `src/dopesecurity/mcp_server/tools/__init__.py`, `src/dopesecurity/mcp_server/services/__init__.py`, `src/dopesecurity/mcp_server/tests/test_server.py`

**Depends on:** Tasks 2, 3

**Reference files:** `docs/mcp-server-design.md`, official MCPServer lifespan pattern as summarized in the design document

#### Goal

Create the MCP composition root and CLI startup path without yet depending on concrete domain tools.

#### Success criteria

- `server.py` exposes `create_server(settings: Settings | None = None) -> MCPServer`.
- Lifespan creates exactly one shared `httpx.AsyncClient`, one `FlightdeckTokenManager`, one `FlightdeckClient`, and one typed `AppContext` per process.
- Tool modules are registered through domain registration functions that accept the `MCPServer` instance and mutation setting.
- Read registration is always invoked; write registration is invoked only when `settings.enable_mutations` is true.
- `__main__.py` loads settings from env plus CLI overrides, configures logging, creates the server, and runs `stdio` by default.
- Verification commands pass from the repository root.

#### Constraints / non-goals

- Do not implement remote HTTP transport.
- Do not create a FastAPI/Starlette app.
- Do not put business logic in `server.py`.
- Do not create real domain services until Tasks 6, 8, and 9; use import-safe placeholders only if necessary.

#### Spec

- In `server.py`, define:
  - `@dataclass(frozen=True) class AppContext` with fields `settings`, `token_manager`, `flightdeck`, `endpoints`, `policies`, `custom_categories`.
  - `@asynccontextmanager async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]` following the design document.
  - `def create_server(settings: Settings | None = None) -> MCPServer` that builds `MCPServer("dope.security Flightdeck", version=__version__, lifespan=...)` or equivalent SDK-supported constructor.
  - Private registration helper that imports and calls `register_endpoint_tools`, `register_policy_tools`, and `register_custom_category_tools` from the corresponding tool modules. If those modules do not yet exist, create stubs in this task or coordinate with dependent tasks.
- Make the lifespan use `httpx.AsyncClient(base_url=settings.api_base_url, timeout=settings.timeout_seconds)`.
- Make `__main__.py` call the SDK run method for stdio only after successful settings load.
- Provide an internal helper in `tools/__init__.py` for retrieving app context from a MCPServer `Context`, e.g. `def get_app_context(ctx: Context) -> AppContext`, with imports arranged to avoid circular imports.

#### Tests

- `test_create_server_returns_mcpserver_instance`: create settings with test credentials and assert server object is built.
- `test_lifespan_builds_shared_context`: enter lifespan and assert context has settings, token manager, client, and service placeholders/instances.
- `test_write_tools_not_registered_when_mutations_disabled`: monkeypatch registration functions or inspect registered tools if SDK allows; assert write registration path is skipped.
- `test_write_tools_registered_when_mutations_enabled`: same, assert write registration path is invoked.
- `test_cli_does_not_define_secret_flags`: parser rejects `--client-secret` and `--client-id`.

#### Verification

```sh
uv run pytest src -k 'server or main'
uv run ruff check .
uv run mypy src
```

### Task 5: Implement MCP-facing schemas and shared normalization helpers

**Files:** `src/dopesecurity/mcp_server/schemas.py`, `src/dopesecurity/mcp_server/tests/test_schemas.py`

**Depends on:** Task 2

**Reference files:** `docs/mcp-server-design.md`, `docs/partner_api.yaml`

#### Goal

Define stable snake_case MCP-facing models for inputs and outputs so services/tools share one contract.

#### Success criteria

- All MCP-facing field names are snake_case.
- Outputs strip top-level Flightdeck `data` wrappers before reaching tools.
- Dynamic API object maps for policy restrictions/exceptions are represented as list-based MCP models where the design requires it.
- Domain values such as restrictions, states, platforms, status values, and debug states are preserved exactly.
- Validation catches endpoint requests with more than one search/filter field before a Flightdeck call.
- Verification commands pass from the repository root.

#### Constraints / non-goals

- Do not encode raw Flightdeck camelCase into MCP-facing models except as Pydantic aliases for parsing.
- Do not add behavior that fetches additional pages automatically.
- Do not implement HTTP calls or MCPServer decorators in this task.

#### Spec

- In `schemas.py`, define Pydantic models for shared pagination and all tool input/output shapes. Minimum required models:
  - `PageInfo(end_cursor: str | None, has_next_page: bool)`
  - `SuccessResult(message: str | None = None)`
  - Endpoint search input/output: `EndpointSearchInput`, `EndpointItem`, `SearchEndpointsResult`
  - Policies: `PolicyItem`, `ListPoliciesResult`, `PolicyAssignmentsResult`, `PolicyUserAssignment`, `PolicyGroupAssignment`
  - Policy restrictions: `RestrictionItem`, `RestrictionsBlock`, `PolicyRestrictionsResult`, `RestrictionUpdate`, `UpdatePolicyRestrictionsInput`
  - Policy exceptions: `ExceptionItem`, `ExceptionCategoryItem`, `ExceptionsBlock`, `PolicyExceptionsResult`, `ExceptionUpdate`, `ExceptionCategoryUpdate`, `ReplacePolicyCategoryExceptionsInput`
  - URL bypass: `CustomUrlBypassItem`, `DefaultUrlBypassItem`, `PolicyUrlBypassResult`, `UpsertPolicyUrlBypassInput`
  - Application bypass: platform blocks for `mac` and `windows`, `PolicyApplicationBypassResult`, `UpsertPolicyApplicationBypassInput`
  - Custom categories: `CustomCategoryItem`, `ListCustomCategoriesResult`, `CustomCategoryUrlsResult`
- Endpoint allowed search/filter fields must be exactly: `query`, `email_id`, `device_name`, `user_id`, `os_version`, `status`, `debug_state`, `fallback_mode`, `location_id`, `agent_version`.
- Add helper functions:
  - `def strip_data(payload: Mapping[str, Any]) -> Mapping[str, Any]`
  - `def camel_to_snake_payload(value: Any) -> Any` only if needed for low-risk normalization.
  - `def endpoint_search_params(input: EndpointSearchInput) -> dict[str, Any]` mapping `query` to Flightdeck `id`, `email_id` to `emailId`, etc., preserving `first`, `after`, and `order`.
- Use Pydantic validation to enforce:
  - `first` positive when supplied.
  - endpoint search has zero or one non-pagination search/filter field.
  - lists such as URLs/names/principals are non-empty for mutating inputs where a no-op would be confusing.

#### Tests

- `test_endpoint_search_allows_zero_filter_fields`: no search fields returns only pagination/order params.
- `test_endpoint_search_allows_one_filter_field_and_maps_names`: `query="alice"` maps to `id=alice`.
- `test_endpoint_search_rejects_multiple_filter_fields`: e.g. `query` and `email_id` raises validation error.
- `test_page_info_parses_camel_case_aliases`: `endCursor` and `hasNextPage` parse to snake_case.
- `test_exception_item_normalizes_type_to_principal_type`: Flightdeck `type` alias becomes `principal_type`.
- `test_mutating_inputs_reject_empty_lists`: empty URL/name/principal lists fail where applicable.

#### Verification

```sh
uv run pytest src -k schemas
uv run ruff check .
uv run mypy src
```

### Task 6: Implement endpoint service and `search_endpoints` tool

**Files:** `src/dopesecurity/mcp_server/services/endpoints.py`, `src/dopesecurity/mcp_server/tools/endpoints.py`, `src/dopesecurity/mcp_server/server.py`, `src/dopesecurity/mcp_server/tests/test_endpoints_service.py`, `src/dopesecurity/mcp_server/tests/test_endpoints_tools.py`

**Depends on:** Tasks 4, 5

**Reference files:** `docs/mcp-server-design.md`, `docs/partner_api.yaml`

#### Goal

Implement the endpoint read surface with pre-call validation and MCP tool registration.

#### Success criteria

- `search_endpoints` supports `first`, `after`, `order`, and zero-or-one allowed search/filter fields.
- MCP field `query` maps to Flightdeck query parameter `id`.
- More than one search/filter field is rejected before calling Flightdeck.
- Tool output is snake_case and strips the top-level `data` wrapper.
- The endpoint tool is always registered regardless of mutation setting.
- Verification commands pass from the repository root.

#### Constraints / non-goals

- Do not add endpoint write tools.
- Do not implement fetch-all pagination.
- Do not expose raw Flightdeck camelCase fields at the MCP boundary.

#### Spec

- In `services/endpoints.py`, define `EndpointsService` with:
  - `__init__(self, flightdeck: FlightdeckClient)`
  - `async def search_endpoints(self, input: EndpointSearchInput) -> SearchEndpointsResult`
  - Build params using `endpoint_search_params(input)` from Task 5.
  - Call `flightdeck.search_endpoints(params)`.
  - Normalize `payload["data"]["endpoints"]` and `payload["data"]["pageInfo"]` into `SearchEndpointsResult`.
- In `tools/endpoints.py`, define:
  - `def register_endpoint_tools(mcp: MCPServer, *, enable_mutations: bool = False) -> None`
  - Register only `search_endpoints`.
  - Tool signature should use explicit keyword parameters rather than a generic dict when possible, matching the input fields in the design document.
  - Tool description must state that zero search fields lists endpoints and only one search/filter field may be supplied.
  - Retrieve service from typed lifespan context and call `EndpointsService.search_endpoints`.
- Update `server.py` imports/registration if Task 4 used stubs.

#### Tests

- `test_search_endpoints_service_lists_all`: no filter calls client with pagination/order only and returns normalized endpoint/page_info.
- `test_search_endpoints_service_maps_query_to_id`: service sends `id`, not `query`.
- `test_search_endpoints_service_rejects_multiple_filters_before_client_call`: client mock is not called.
- `test_search_endpoints_tool_registered`: created server includes `search_endpoints` in tools.
- `test_search_endpoints_tool_uses_lifespan_service`: invoke handler directly or through SDK test helper with fake context; assert normalized result.

#### Verification

```sh
uv run pytest src -k endpoints
uv run ruff check .
uv run mypy src
```

### Task 7: Implement policy service workflows

**Files:** `src/dopesecurity/mcp_server/services/policies.py`, `src/dopesecurity/mcp_server/tests/test_policies_service.py`

**Depends on:** Tasks 3, 5

**Reference files:** `docs/mcp-server-design.md`, `docs/partner_api.yaml`

#### Goal

Implement policy domain behavior independently of MCPServer decorators: listing, lifecycle, assignments, restrictions, exceptions, URL bypass, and application bypass.

#### Success criteria

- Service methods cover all policy read and write behavior needed by the v1 tools.
- Assignment write workflows read current assignments, merge/remove provided users/groups, de-duplicate, ignore missing unassignments, and write back the full assignment set.
- Restriction updates are per submitted category/custom category only; omitted categories remain unchanged.
- Restriction reset supports scopes `categories`, `custom_categories`, and `both` using the Flightdeck BaseInheritance request shape from `docs/partner_api.yaml`.
- Exception replacement is per submitted category/custom category only; empty exception lists clear exceptions for that category.
- URL bypass upsert/delete/reset and application bypass upsert/reset follow the design document and API spec.
- Derived reads return snake_case MCP schemas and preserve `inherits_from_base`, `custom`, `default`, `ssl_inspection`, `clash_count`, `updated_at`, and other important domain values.
- Verification commands pass from the repository root.

#### Constraints / non-goals

- Do not register MCP tools in this task.
- Do not implement application bypass per-entry deletion; preserve the documented v1 limitation.
- Do not fetch all policy pages automatically.
- Do not mutate inherited policy state except through explicit reset-to-base operations supported by the API.

#### Spec

- In `services/policies.py`, define `PoliciesService` with constructor `__init__(self, flightdeck: FlightdeckClient)` and methods:
  - `async def list_policies(self, *, first: int | None = None, after: str | None = None, order: Literal["asc", "desc"] | None = None) -> ListPoliciesResult`
  - `async def create_policy(self, policy_name: str) -> SuccessResult`
  - `async def delete_policy(self, policy_name: str) -> SuccessResult`
  - `async def get_assignments(self, policy_name: str) -> PolicyAssignmentsResult`
  - `async def assign_principals(self, policy_name: str, *, user_emails: Sequence[str] | None = None, group_emails: Sequence[str] | None = None) -> PolicyAssignmentsResult`
  - `async def unassign_principals(self, policy_name: str, *, user_emails: Sequence[str] | None = None, group_emails: Sequence[str] | None = None) -> PolicyAssignmentsResult`
  - `async def get_restrictions(self, policy_name: str) -> PolicyRestrictionsResult`
  - `async def update_restrictions(self, input: UpdatePolicyRestrictionsInput) -> PolicyRestrictionsResult | SuccessResult`
  - `async def reset_restrictions_to_base(self, policy_name: str, scope: Literal["categories", "custom_categories", "both"]) -> SuccessResult`
  - `async def get_exceptions(self, policy_name: str) -> PolicyExceptionsResult`
  - `async def replace_category_exceptions(self, input: ReplacePolicyCategoryExceptionsInput) -> PolicyExceptionsResult | SuccessResult`
  - `async def get_url_bypass(self, policy_name: str) -> PolicyUrlBypassResult`
  - `async def upsert_url_bypass(self, input: UpsertPolicyUrlBypassInput) -> PolicyUrlBypassResult | SuccessResult`
  - `async def delete_url_bypass_entries(self, policy_name: str, names: Sequence[str]) -> SuccessResult`
  - `async def reset_url_bypass_to_base(self, policy_name: str) -> SuccessResult`
  - `async def get_application_bypass(self, policy_name: str) -> PolicyApplicationBypassResult`
  - `async def upsert_application_bypass(self, input: UpsertPolicyApplicationBypassInput) -> PolicyApplicationBypassResult | SuccessResult`
  - `async def reset_application_bypass_to_base(self, policy_name: str) -> SuccessResult`
- Assignment payload semantics:
  - Preserve the API's current `users` and `groups` data not targeted by the operation.
  - For assign, union existing emails with provided emails and sort deterministically or preserve existing order then append new values deterministically.
  - For unassign, remove provided emails and leave other principals unchanged.
  - Empty/no provided principal lists should raise validation/domain error before calling Flightdeck.
- Policy content derived read semantics:
  - `get_restrictions` calls `get_policy_content` and transforms `categories.restrictions` and `customCategories.restrictions` maps into `items` lists without exceptions.
  - `get_exceptions` calls `get_policy_content` and transforms each category/custom category's exceptions map into list items with `principal` and `principal_type` normalized from API `type`.
- Restriction write semantics:
  - Convert submitted list items into Flightdeck object maps keyed by category/custom category name.
  - Include only sections supplied by the input.
  - For reset-to-base, use the API's `BaseInheritance` shape exactly as described in `docs/partner_api.yaml`.
- Exception write semantics:
  - Convert submitted category list into nested maps keyed by category name and principal.
  - Empty exception list creates an empty map for that submitted category.
  - Include only submitted categories/custom categories.
- Bypass reset semantics:
  - URL reset and application reset use the corresponding API reset/inheritance request shape from `docs/partner_api.yaml`.

#### Tests

- `test_list_policies_normalizes_page_info_and_items`: asserts `policyName` -> `policy_name`, `sslInspection` -> `ssl_inspection`, `clashCount` -> `clash_count`.
- `test_assign_principals_merges_and_deduplicates`: existing and new users/groups produce one update with full de-duplicated sets.
- `test_unassign_principals_ignores_missing`: missing user/group in input does not error and is absent from output.
- `test_assignment_no_inputs_rejected_before_client_call`: no user/group emails raises validation/domain error.
- `test_get_restrictions_omits_exceptions`: content payload with exceptions returns only restriction fields.
- `test_get_exceptions_normalizes_principal_type`: API `type` becomes `principal_type`.
- `test_update_restrictions_sends_only_submitted_categories`: omitted categories/custom categories are absent from request body.
- `test_reset_restrictions_to_base_scopes`: parameterized scopes produce correct BaseInheritance body sections.
- `test_replace_category_exceptions_replaces_per_submitted_category`: submitted category body includes only that category.
- `test_replace_category_exceptions_empty_list_clears_category`: empty exceptions becomes empty map for that category.
- `test_url_bypass_delete_sends_names`: names are sent according to API spec.
- `test_application_bypass_reset_uses_inheritance_body`: reset body matches API spec.

#### Verification

```sh
uv run pytest src -k policies_service
uv run ruff check .
uv run mypy src
```

### Task 8: Register policy MCP tools with mutation gating

**Files:** `src/dopesecurity/mcp_server/tools/policies.py`, `src/dopesecurity/mcp_server/server.py`, `src/dopesecurity/mcp_server/tests/test_policies_tools.py`, `src/dopesecurity/mcp_server/tests/test_server.py`

**Depends on:** Tasks 4, 7

**Reference files:** `docs/mcp-server-design.md`, `docs/partner_api.yaml`

#### Goal

Expose the policy service through the approved v1 MCP policy tools with clear tool descriptions and write-tool mutation gating.

#### Success criteria

- Read tools always registered: `list_policies`, `get_policy_assignments`, `get_policy_restrictions`, `get_policy_exceptions`, `get_policy_url_bypass`, `get_policy_application_bypass_entries`.
- Write tools registered only when mutations are enabled: `create_policy`, `delete_policy`, `assign_policy_principals`, `unassign_policy_principals`, `update_policy_restrictions`, `reset_policy_restrictions_to_base`, `replace_policy_category_exceptions`, `upsert_policy_url_bypass`, `delete_policy_url_bypass_entries`, `reset_policy_url_bypass_to_base`, `upsert_policy_application_bypass`, `reset_policy_application_bypass_to_base`.
- Mutating tool descriptions explicitly state they modify tenant state.
- `replace_policy_category_exceptions` description explicitly states replacement is per submitted category, not whole-policy replacement.
- URL bypass tool descriptions explicitly explain `custom` vs `default` entries.
- Application bypass deletion limitation is not hidden or contradicted by tool descriptions.
- Tool failures present concise normalized errors for expected Flightdeck/domain failures.
- Verification commands pass from the repository root.

#### Constraints / non-goals

- Do not implement service logic in tool handlers.
- Do not register write tools when `enable_mutations=False`.
- Do not add policy tools beyond the exact approved list.
- Do not expose raw Flightdeck request/response maps in tool signatures.

#### Spec

- In `tools/policies.py`, define:
  - `def register_policy_tools(mcp: MCPServer, *, enable_mutations: bool = False) -> None`
  - Inner async functions decorated with `@mcp.tool(...)` or the SDK's equivalent registration API.
  - Read tool handlers that retrieve `PoliciesService` from context and call the corresponding service methods.
  - Write tool handlers only inside an `if enable_mutations:` block.
- Tool signatures should use explicit parameters matching the design. Examples:
  - `async def list_policies(ctx: Context, first: int | None = None, after: str | None = None, order: Literal["asc", "desc"] = "asc") -> ListPoliciesResult`
  - `async def assign_policy_principals(ctx: Context, policy_name: str, user_emails: list[str] | None = None, group_emails: list[str] | None = None) -> PolicyAssignmentsResult`
  - `async def reset_policy_restrictions_to_base(ctx: Context, policy_name: str, scope: Literal["categories", "custom_categories", "both"]) -> SuccessResult`
- Use `to_tool_error` from Task 2 to convert known exceptions. If the MCP SDK has a preferred exception type for tool failures, wrap normalized message/details into that type without converting business failures into protocol errors.
- Update `server.py` registration if needed so policy tools are included.

#### Tests

- `test_policy_read_tools_registered_when_mutations_disabled`: read tools present.
- `test_policy_write_tools_absent_when_mutations_disabled`: write tools absent.
- `test_policy_write_tools_present_when_mutations_enabled`: write tools present.
- `test_mutating_policy_descriptions_warn_about_tenant_state`: inspect descriptions if SDK supports it.
- `test_replace_exceptions_description_mentions_per_category_replacement`: inspect description.
- `test_url_bypass_descriptions_explain_custom_and_default`: inspect descriptions.
- `test_policy_tool_handler_calls_service`: direct handler/SDK invocation with fake service asserts parameters are passed through.
- `test_policy_tool_normalizes_expected_errors`: fake service raises known domain error; tool surfaces normalized concise error.

#### Verification

```sh
uv run pytest src -k 'policies_tools or server'
uv run ruff check .
uv run mypy src
```

### Task 9: Implement custom category service and MCP tools

**Files:** `src/dopesecurity/mcp_server/services/custom_categories.py`, `src/dopesecurity/mcp_server/tools/custom_categories.py`, `src/dopesecurity/mcp_server/server.py`, `src/dopesecurity/mcp_server/tests/test_custom_categories_service.py`, `src/dopesecurity/mcp_server/tests/test_custom_categories_tools.py`, `src/dopesecurity/mcp_server/tests/test_server.py`

**Depends on:** Tasks 4, 5

**Reference files:** `docs/mcp-server-design.md`, `docs/partner_api.yaml`

#### Goal

Implement the custom category read/write surface, including internal URL encoding for single-URL deletion and mutation-gated write tools.

#### Success criteria

- Read tools always registered: `list_custom_categories`, `get_custom_category_urls`.
- Write tools registered only when mutations are enabled: `create_custom_category`, `delete_custom_category`, `add_urls_to_custom_category`, `delete_all_urls_from_custom_category`, `delete_single_url_from_custom_category`.
- `delete_single_url_from_custom_category` URL-encodes the single URL internally before calling Flightdeck.
- `list_custom_categories` returns `custom_categories` and `page_info` in snake_case.
- `get_custom_category_urls` returns `urls`.
- Empty URL lists are rejected before calling Flightdeck.
- Verification commands pass from the repository root.

#### Constraints / non-goals

- Do not expose the API's overwrite-all-URLs endpoint as a v1 MCP tool.
- Do not implement fetch-all pagination.
- Do not register write tools when `enable_mutations=False`.

#### Spec

- In `services/custom_categories.py`, define `CustomCategoriesService` with:
  - `__init__(self, flightdeck: FlightdeckClient)`
  - `async def list_custom_categories(self, *, first: int | None = None, after: str | None = None, order: Literal["asc", "desc"] | None = None) -> ListCustomCategoriesResult`
  - `async def get_urls(self, custom_category_name: str) -> CustomCategoryUrlsResult`
  - `async def create(self, custom_category_name: str) -> SuccessResult`
  - `async def delete(self, custom_category_name: str) -> SuccessResult`
  - `async def add_urls(self, custom_category_name: str, urls: Sequence[str]) -> CustomCategoryUrlsResult | SuccessResult`
  - `async def delete_all_urls(self, custom_category_name: str) -> SuccessResult`
  - `async def delete_single_url(self, custom_category_name: str, url: str) -> SuccessResult`
- Use `urllib.parse.quote(url, safe="")` for `delete_single_url` before calling `flightdeck.delete_single_url_from_custom_category`.
- In `tools/custom_categories.py`, define:
  - `def register_custom_category_tools(mcp: MCPServer, *, enable_mutations: bool = False) -> None`
  - Register read handlers always and write handlers only when enabled.
  - Mutating descriptions must state they modify tenant state.
- Update `server.py` registration if needed.

#### Tests

- `test_list_custom_categories_normalizes_items_and_page_info`: asserts wrapper stripped and snake_case output.
- `test_get_custom_category_urls_returns_urls`: service normalizes API response.
- `test_add_urls_rejects_empty_list_before_client_call`: no client call.
- `test_delete_single_url_encodes_url`: `https://example.com/a?b=c` is passed encoded to client.
- `test_custom_category_read_tools_registered_when_mutations_disabled`: read tools present.
- `test_custom_category_write_tools_absent_when_mutations_disabled`: write tools absent.
- `test_custom_category_write_tools_present_when_mutations_enabled`: write tools present.

#### Verification

```sh
uv run pytest src -k custom_categories
uv run ruff check .
uv run mypy src
```

### Task 10: Final documentation, sample MCP config, and end-to-end verification

**Files:** `README.md`, `docs/mcp.json.example`, `src/dopesecurity/mcp_server/tests/test_tool_surface.py`

**Depends on:** Tasks 6, 8, 9

**Reference files:** `docs/mcp-server-design.md`, `docs/mcp-research.md`

#### Goal

Complete customer-facing documentation and add final verification that the server exposes the intended read-only and mutation-enabled tool surfaces.

#### Success criteria

- README documents installation via `uvx dopesecurity-mcp-server`.
- README documents `DOPE_CLIENT_ID` and `DOPE_CLIENT_SECRET` as required env vars and does not suggest passing secrets as tool inputs or CLI flags.
- README documents public non-secret configuration: `DOPE_ENABLE_MUTATIONS`, `DOPE_TIMEOUT_SECONDS`, `DOPE_LOG_LEVEL`, plus CLI flags `--enable-mutations`, `--timeout-seconds`, and `--log-level`.
- README and sample `mcp.json` document read-only-by-default behavior and mutation gating.
- README documents the known v1 limitation around custom application bypass entry deletion.
- README and sample `mcp.json` do not mention `DOPE_BASE_URL`, `--base-url`, `DOPE_TOKEN_REFRESH_SKEW_SECONDS`, or `--token-refresh-skew-seconds`.
- `docs/mcp.json.example` is valid JSON and uses `uvx` with package/command `dopesecurity-mcp-server`.
- Final tool surface test asserts the exact approved tool set in read-only and mutation-enabled modes.
- Full verification commands pass from the repository root.

#### Constraints / non-goals

- Do not document internal base URL or token refresh skew settings in customer-facing docs.
- Do not include real credentials or placeholder values that look like real secrets.
- Do not add remote transport docs for v1.

#### Spec

- Rewrite `README.md` with sections:
  - Overview
  - Installation
  - MCP client configuration
  - Required credentials
  - Read-only default and enabling mutations
  - Public configuration reference
  - Available tools grouped by domain and read/write status
  - Known limitations
  - Development and verification
- Add `docs/mcp.json.example` with shape:

```json
{
  "mcpServers": {
    "dope-security": {
      "command": "uvx",
      "args": ["dopesecurity-mcp-server"],
      "env": {
        "DOPE_CLIENT_ID": "your-client-id",
        "DOPE_CLIENT_SECRET": "your-client-secret",
        "DOPE_ENABLE_MUTATIONS": "false",
        "DOPE_LOG_LEVEL": "INFO",
        "DOPE_TIMEOUT_SECONDS": "30"
      }
    }
  }
}
```

- Add `test_tool_surface.py` with constants for the approved read and write tool names and tests:
  - `test_read_only_tool_surface_exact`: mutations disabled exposes only approved read tools.
  - `test_mutation_enabled_tool_surface_exact`: mutations enabled exposes approved read + write tools.
  - `test_customer_docs_do_not_mention_internal_settings`: read README/sample and assert internal names are absent.
  - `test_sample_mcp_json_is_valid`: parse sample JSON.

#### Tests

- Use the exact tool lists from `docs/mcp-server-design.md`:
  - Read tools: `search_endpoints`, `list_policies`, `get_policy_assignments`, `get_policy_restrictions`, `get_policy_exceptions`, `get_policy_url_bypass`, `get_policy_application_bypass_entries`, `list_custom_categories`, `get_custom_category_urls`.
  - Write tools: `create_policy`, `delete_policy`, `assign_policy_principals`, `unassign_policy_principals`, `update_policy_restrictions`, `reset_policy_restrictions_to_base`, `replace_policy_category_exceptions`, `upsert_policy_url_bypass`, `delete_policy_url_bypass_entries`, `reset_policy_url_bypass_to_base`, `upsert_policy_application_bypass`, `reset_policy_application_bypass_to_base`, `create_custom_category`, `delete_custom_category`, `add_urls_to_custom_category`, `delete_all_urls_from_custom_category`, `delete_single_url_from_custom_category`.

#### Verification

```sh
uv run pytest src
uv run ruff check .
uv run mypy src
uv run dopesecurity-mcp-server --help
```

## Execution Order

- **Wave 1:** Task 1.
- **Wave 2:** Tasks 2 and 5 can run in parallel after bootstrap, but Task 5 may need light adjustment if Task 2 changes shared error/config conventions.
- **Wave 3:** Tasks 3 and 4 can run in parallel after Task 2; Task 4 can use service/tool placeholders until domain tasks land.
- **Wave 4:** Tasks 6, 7, and 9 can run in parallel after their dependencies are met. Task 7 is the largest and riskiest task.
- **Wave 5:** Task 8 after Task 7 and Task 4.
- **Wave 6:** Task 10 after endpoint, policy, and custom category tools are registered.

## Complex / Risky Areas

- **Policy content transformations:** restrictions and exceptions are derived views over the same Flightdeck content payload, and write inputs intentionally differ from API object maps. Tests need strong fixtures from `docs/partner_api.yaml` examples.
- **Assignment updates are non-atomic:** the read-modify-write service should be explicit and deterministic, but concurrent external changes can still race. Tool descriptions should describe this as best-effort.
- **MCP SDK tool introspection:** tests may need small helper functions to inspect registered tools depending on the SDK's public API. Keep these helpers in tests only.
- **Error presentation:** the exact SDK exception type for tool failures should be selected during implementation, but normalized error content and non-protocol-business-error behavior are fixed by this plan.

## Assumptions To Review

- Tests are intentionally placed under `src/dopesecurity/mcp_server/tests/` to satisfy the repository instruction to run `uv run pytest src`.
- The distribution/package name and console command are both `dopesecurity-mcp-server`, matching the frozen design rather than the earlier research note's shorter `dopemcp` example.
- `httpx.MockTransport` is sufficient for unit coverage; no live Flightdeck integration tests are required for v1 implementation.
- Internal CLI flags for base URL and token refresh skew are supported by the code because the design recommends them, but they are deliberately excluded from customer-facing docs.
