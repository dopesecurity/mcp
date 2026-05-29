# Deterministic MCP integration tests

A pytest suite that drives the local `dopesecurity-mcp-server` over MCP
stdio against the **`apac.acme.test`** sandbox tenant on the **internal**
Flightdeck environment (`https://api.flightdeck.internal.swg.ai/v1`).
Each test calls tools directly through the MCP `ClientSession` (no LLM
in the loop) and asserts on structured results.

> ⚠️ These tests are pinned to the `apac.acme.test` tenant. The tenant
> URL, client id, default test user, and default test group are
> hardcoded in [`harness.py`](./harness.py). Do not point the suite at
> any other tenant — it mutates state aggressively and only this tenant
> is treated as disposable.

This complements:

- the unit tests under `src/.../tests/` (HTTP mocked), and
- the LLM-driven scenarios planned in
  [`docs/plans/integration-scenarios.md`](../../docs/plans/integration-scenarios.md).

## Running

```sh
DOPE_MCP_TESTS_CLIENT_SECRET=... make integration-tests
```

The only required environment variable:

| Env var                          | Purpose                                                                |
| -------------------------------- | ---------------------------------------------------------------------- |
| `DOPE_MCP_TESTS_CLIENT_SECRET`   | OAuth client secret for the `apac.acme.test` sandbox tenant. Shared in the team password manager. |

If the variable is missing, every test fails up front with a message
pointing at the password manager. If the secret is wrong, tools fail
with a 401 `invalid_client` `ToolError` annotated with the same hint.

There is no opt-in flag — when you collect this directory, the tests
run.

## Hardcoded tenant values

Defined in [`harness.py`](./harness.py):

- Base URL: `https://api.flightdeck.internal.swg.ai/v1`
- Tenant: `apac.acme.test`
- Client ID: `e481a103408a981615ea4117ab3781f2`
- Test user: `dope@pb7q.onmicrosoft.com`
- Test group: `Retail@pb7q.onmicrosoft.com`

## What gets created on the tenant

Every test artifact (policy, custom category, bypass entry, etc.) uses a
`mcp-it-<scenario>-<uuid8>` name prefix so it is easy to recognize and
sweep manually if a run crashes. The `cleaner` yielded by `integration()`
deletes any created policies and custom categories in teardown, even on
failure.

## Layout

- `harness.py` — hardcoded tenant config (`IntegrationConfig`,
  `MissingCredentialsError`, `CRED_HINT`), `McpHarness` (typed
  `call_tool` wrapper + pagination helpers), `Cleaner`, `open_harness()`
  which spawns the server via `mcp.client.stdio`, and the
  `integration()` context manager that yields `(mcp, cleaner)` in a
  single asyncio task.
- `conftest.py` — `integration_config` session fixture that loads the
  client secret from env and fails the run with the credential hint if
  it is missing.
- `test_surface.py` — verifies the spawned server exposes every expected
  tool over the wire.
- `test_endpoints.py` — `search_endpoints` (basic, paginated, multi-filter
  rejection).
- `test_policies.py` — full lifecycle, all read tools, assignments,
  restrictions, exceptions, URL bypass, application bypass, error
  surface for unknown policies.
- `test_custom_categories.py` — full lifecycle for custom categories
  (create, list, add URLs, delete single, delete all, delete category)
  plus error surface for unknown categories.

## Adding a new scenario

1. Pick the right `test_*.py` (or add a new one).
2. Take the `integration_config` fixture and open the harness with the
   `integration()` async context manager:

   ```python
   async def test_x(integration_config):
       async with integration(integration_config) as (mcp, cleaner):
           ...
   ```

   Opening the session inside the test (rather than via an async
   fixture) keeps `stdio_client` / `ClientSession` setup and teardown
   in the same asyncio task, which avoids the anyio "cancel scope in a
   different task" error.
3. If the scenario creates tenant state, call
   `cleaner.track_policy(name)` / `cleaner.track_custom_category(name)`
   right after creation — before any assertions that might raise — so
   teardown deletes them even on failure.
4. Use `make_tag("<short-scenario-id>")` for every created object so
   names are unique and recognizable.
5. Call tools via `mcp.call("<tool_name>", {...})`. The result is the
   structured JSON dict returned by the tool's Pydantic output model.
6. For tools that return `SuccessResult`, you can ignore the return.
7. To assert on tool errors, use:

   ```python
   with pytest.raises(ToolError):
       await mcp.call("…", {…})
   ```
