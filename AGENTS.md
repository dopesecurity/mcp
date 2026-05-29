# AGENTS.md

Guidance for working in this repo (`dopesecurity-mcp-server`), a local MCP
server for the dope.security Flightdeck partner API.

## Scope discipline (apply to every change)

- Make the smallest change that solves the task. Do not refactor, rename,
  or "tidy" code that is not part of the task.
- Do not add features, configuration knobs, or abstractions that were not
  requested.
- Do not add error handling, retries, or fallbacks for conditions that
  cannot happen here. Trust internal callers; only validate at the tool
  boundary.
- If the task as written is ambiguous, ask one clarifying question
  instead of guessing. Stop and ask before introducing a new dependency,
  a new module, or a new top-level pattern.

## Never

- Never add a second HTTP library; all HTTP goes through
  `flightdeck/client.py` (httpx).
- Never read env vars outside `config.py` / `pydantic-settings`. Import
  the constant.
- Never accept credentials as CLI flags or tool arguments.
- Never log or echo tokens, headers, request bodies, or tool argument
  secrets.
- Never auto-paginate. Pass `next_cursor` back to the caller and let the
  LLM decide.
- Never cache Flightdeck responses; only the OAuth token is cached
  (`auth.py`).
- Never use `print()` in runtime code. Use `structlog.get_logger()`.
  (stdout is the MCP transport.)
- Never use bare `except:` or `except Exception` outside the tool
  entrypoint.
- Never use wildcard imports (`from x import *`).
- Never add a write/mutation tool that registers unconditionally — gate
  on `DOPE_ENABLE_MUTATIONS`.
- Never silence a warning to make tests pass; `filterwarnings = ["error"]`
  is intentional.
- Never mock `structlog`/loggers and never assert on log lines in tests.

## Layout

- `src/dopesecurity/mcp_server/` — server entrypoint (`__main__.py`,
  `server.py`), `config.py`, `auth.py`, `errors.py`, `schemas.py`.
- `src/dopesecurity/mcp_server/tools/` — MCP tool registration layer
  (`endpoints`, `policies`, `custom_categories`). Thin: validates input,
  delegates to a service, shapes the response.
- `src/dopesecurity/mcp_server/services/` — business logic for each tool
  family (`endpoints`, `policies`, `custom_categories`). All Flightdeck
  calls go through here.
- `src/dopesecurity/mcp_server/flightdeck/` — HTTP client (`client.py`)
  and shared Pydantic models (`models.py`) for the Flightdeck API.
- `src/dopesecurity/mcp_server/tests/` — unit tests (HTTP mocked via
  `httpx`), live next to the code.
- `tests/integration/` — deterministic MCP-over-stdio integration tests
  against the `apac.acme.test` sandbox tenant on internal Flightdeck.
  See [`tests/integration/README.md`](tests/integration/README.md).
- `docs/` — design notes, OpenAPI spec (`partner_api.yaml`), and
  implementation/integration plans.

## Toolchain

- Python ≥ 3.11, managed with `uv` (see `uv.lock`).
- `mcp`, `httpx`, `pydantic` v2, `pydantic-settings`, `structlog`.
- Lint: ruff. Types: mypy strict on `dopesecurity.mcp_server`.
- Tests: pytest + pytest-asyncio (`asyncio_mode = "auto"`,
  `filterwarnings = ["error"]`).

## Commands (run from repo root)

- Install: `uv sync` (or `make install`)
- Unit tests: `uv run pytest src` (or `make unit-tests`)
  - Single test: `uv run pytest src -k '<name>'`
- Integration tests: `make integration-tests`
  (requires `DOPE_MCP_TESTS_CLIENT_SECRET`; see
  [`tests/integration/README.md`](tests/integration/README.md))
- Lint: `uv run ruff check .` (`make lint`); auto-fix: `make format`
- Types: `uv run mypy src` (`make typecheck`)
- All checks: `make check` (lint + typecheck + unit tests; does NOT run
  integration tests)
- Run server: `uv run dopesecurity-mcp-server --help`
- MCP Inspector against the local server: `make inspect`

Always run `make check` from the repo root before declaring a change
complete. Run `make integration-tests` when changing the tool surface,
HTTP client, or anything that affects on-tenant behavior — and you have
the sandbox secret.

## Conventions

### Operational

- **Read-only by default.** Write tools register only when
  `DOPE_ENABLE_MUTATIONS=true` (or `--enable-mutations`). When adding
  tools, preserve this split — see `tools/` modules for the pattern.
- **Tools vs. services.** Keep `tools/` thin (schema + dispatch). Put
  HTTP orchestration, pagination logic, and Flightdeck-specific quirks
  in `services/`.
- **Credentials come from env only** (`DOPE_CLIENT_ID`,
  `DOPE_CLIENT_SECRET`). Auth uses OAuth client-credentials with cached
  tokens (`auth.py`).
- **Logging:** use `structlog.get_logger()`; logs go to stderr only
  (stdout is the MCP transport). `DOPE_LOG_FILE` may also tee to a file
  for local debugging. See "Logging events" below.
- **HTTP:** go through `flightdeck/client.py`. Respect
  `DOPE_TIMEOUT_SECONDS`. Pagination is cursor-based; do not auto-page.
- **Schemas:** define tool inputs/outputs as Pydantic models in
  `schemas.py` or alongside the tool; keep mypy strict-clean.
- **Errors:** map Flightdeck failures via `errors.py`; surface
  user-meaningful messages without leaking internals.

### Python style

- Prefer plain functions and Pydantic models over classes. Use a class
  only when you need state or a protocol implementation. No inheritance
  hierarchies.
- No metaclasses, no decorator factories, no `getattr`/`setattr` dynamic
  dispatch. Be boring and explicit.
- Type-annotate every function signature and public attribute. Use
  `list[str]` / `dict[str, X]` / `X | None` (3.10+ syntax), not
  `typing.List` / `Optional`.
- Async all the way down for any code that touches the network. No
  `asyncio.run()` inside library code; no `requests`; no sync-over-async
  bridges.
- Imports: stdlib, third-party, local — three groups, ruff-isort
  enforced.
- Errors: raise typed exceptions from `errors.py`; do not return error
  strings, do not return `None` to mean "failed". One exception class
  per failure mode the user can act on.
- Pydantic v2 only. `BaseModel` for tool I/O and Flightdeck DTOs. No
  `dataclass` + manual validation.
- No new global state. Per-request state goes through function
  arguments.

### Single source of truth (placement rules)

- All HTTP calls → `flightdeck/client.py`. Routes/services call the
  client; nothing else hits the network.
- All env vars → `config.py` (read once, exported as typed constants).
- All Flightdeck DTOs → `flightdeck/models.py` (Pydantic). Tool I/O
  models live in `schemas.py` or next to the tool.
- All MCP tool registration → `tools/<family>.py`. One file per resource
  family, mirroring `services/<family>.py`.
- All error mapping (Flightdeck status → user-facing error) →
  `errors.py`.

### Logging events

- Use `structlog.get_logger(__name__)` at module scope.
- Event names use the `domain.action_state` pattern:
  `policies.create_started`, `policies.create_completed`,
  `policies.create_failed`.
- Pass context as kwargs, not f-strings:
  `logger.info("policies.create_started", policy_id=pid)`.
- Never log secrets, tokens, raw headers, or full request/response
  bodies. Log identifiers, status codes, durations, sizes.

## Tests

- Cover one behavior per test. Name tests after the behavior, not the
  function.
- Mock at the HTTP boundary (`httpx`), never at the service or client
  layer. If you can't, the abstraction is wrong — fix it instead.
- Do not write a test that imports private/underscore-prefixed names; if
  you need it, the API is wrong.
- A failing test means the code is wrong by default. Do not "fix" tests
  by relaxing assertions or adding `pytest.skip`.
- Do not delete or weaken an existing test to make a new feature pass.
  If a test must change, explain why in the commit.

### Unit testing

- Live under `src/dopesecurity/mcp_server/tests/`; collected by default
  via `testpaths = ["src"]` in `pyproject.toml`.
- Use real `structlog.get_logger()`; do not mock loggers and do not
  assert on log lines.
- `filterwarnings = ["error"]` is on — fix warnings, don't silence them.
- For new tools, add both a service-level test (HTTP behavior, mocked
  via `httpx`) and a tool-surface test (registration + schema),
  mirroring the existing `test_*_service.py` / `test_*_tools.py` pairs.
- Update `test_tool_surface.py` if the registered tool set changes.

### Integration testing

- Live under `tests/integration/`; **not** collected by `make check` or
  `uv run pytest src`. Run explicitly with `make integration-tests`.
- Drive the local server over MCP stdio (no LLM in the loop) against
  the `apac.acme.test` sandbox tenant on
  `https://api.flightdeck.internal.swg.ai/v1`. Tenant URL, client id,
  test user, and test group are hardcoded in
  [`tests/integration/harness.py`](tests/integration/harness.py).
- Required env: `DOPE_MCP_TESTS_CLIENT_SECRET` (shared in the team
  password manager). Without it, every test fails up front with the
  credential hint.
- Tests open the harness with `async with integration(cfg) as (mcp,
  cleaner)` to keep `stdio_client` / `ClientSession` lifecycle in a
  single asyncio task (avoids anyio "cancel scope in a different task").
- Every created object uses `make_tag("<scenario>")` so names are
  unique and recognizable, and is registered with
  `cleaner.track_policy(...)` / `cleaner.track_custom_category(...)`
  immediately so teardown deletes it even on failure.
- Assert on tool errors with `pytest.raises(ToolError)` from
  `tests.integration.harness`.

## When adding X, copy the canonical example

- New read tool       → mirror `tools/endpoints.py` +
  `services/endpoints.py:list_endpoints`.
- New write tool      → mirror `tools/policies.py` for the
  `DOPE_ENABLE_MUTATIONS` gate.
- New paginated call  → mirror `services/<…>.py`'s cursor passthrough;
  do NOT auto-page.
- New error mapping   → mirror an existing entry in `errors.py`.
- New unit test pair  → mirror `test_<x>_service.py` (HTTP mocked) +
  `test_<x>_tools.py` (surface).
- New integration test → mirror `tests/integration/test_<x>.py` and use
  `make_tag()` + `cleaner.track_*` immediately.

## When changing tool surface

- Update the tool list in `README.md`.
- Keep read vs. write registration consistent with
  `DOPE_ENABLE_MUTATIONS`.
- Update or add tests in `test_tool_surface.py` (unit) and
  `tests/integration/test_surface.py` (integration) if the registered
  set changes.
- Run `make integration-tests` before merging surface changes.

## Definition of done

A change is not done until ALL of these are true:

1. `make check` is green (lint + mypy strict + unit tests).
2. New behavior is covered by a unit test (and integration test if it
   touches Flightdeck).
3. If the tool surface changed: `test_tool_surface.py` and
   `tests/integration/test_surface.py` are updated, `README.md` tool
   list is updated, and `make integration-tests` is green.
4. No new TODO/FIXME comments without a tracking issue.
5. No new `# type: ignore` or `# noqa` without a one-line reason
   comment.

Do not declare done before running these. Report failures verbatim; do
not paraphrase.
