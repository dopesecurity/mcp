# Plan: Agent-Driven MCP Integration Scenarios

## Overview

Build an automated integration-test suite that exercises the
`dopesecurity-mcp-server` end-to-end by driving an LLM agent (Amp CLI in
non-interactive mode) through a curated set of natural-language scenarios.
Each scenario is a markdown prompt that instructs the agent to use the dope
MCP tools to accomplish a small, self-cleaning workflow (e.g. "list
policies, create a test policy, modify a restriction, verify, delete").

This complements unit tests: unit tests verify code correctness against
mocked HTTP; these scenarios verify that the **registered tool surface,
schemas, descriptions, and error messages are usable by a real agent against
a real Flightdeck tenant**.

## Goals

- Cover every tool exposed by the MCP server (read and write) at least once.
- Use natural-language prompts, not direct tool calls — we want to validate
  that the agent can pick the right tool from its description.
- Run unattended in CI (or on demand) against a dedicated sandbox tenant.
- Each scenario must be self-contained and self-cleaning so they can run in
  any order and leave no residue.
- Produce a machine-readable PASS/FAIL result per scenario plus a human-
  readable transcript for debugging.

## Non-goals

- Replacing the existing `pytest` unit suite.
- Coverage metrics or fuzzing of tool inputs (a separate deterministic
  harness can do that).
- Testing Amp itself, or any other MCP host.
- Performance or load testing.

## Architecture

```diagram
╭──────────────────────╮      ╭───────────────────────╮
│ scenarios/*.md       │      │ sandbox tenant        │
│ (one prompt per file)│      │ (dope.security)       │
╰──────────┬───────────╯      ╰───────────▲───────────╯
           │                              │ HTTPS
           ▼                              │
╭──────────────────────╮   stdio   ╭──────┴────────────╮
│ pytest runner        │──spawns──▶│ amp -x            │
│ tests/integration/   │           │ (LLM + MCP client)│
╰──────────┬───────────╯           ╰──────┬────────────╯
           │                              │ stdio
           │                              ▼
           │                       ╭───────────────────╮
           │                       │ dopesecurity-     │
           │                       │ mcp-server        │
           │                       │ (uv run, local)   │
           │                       ╰───────────────────╯
           │
           ▼
   PASS/FAIL + transcript
```

### Components

- **Scenario files** (`tests/integration/scenarios/*.md`): plain-English
  prompts. Each ends with an instruction telling the agent to print exactly
  one line of the form `RESULT: PASS` or `RESULT: FAIL: <reason>` as the
  final line of its response.
- **Amp settings file** (`tests/integration/amp-settings.json`): an Amp
  configuration that registers the local checkout of the MCP server with
  `DOPE_ENABLE_MUTATIONS=true` and points at the sandbox tenant's
  credentials (read from the runner's environment, never committed).
- **Runner** (`tests/integration/test_scenarios.py`): a pytest module that
  parametrizes over every `scenarios/*.md` file. For each scenario it:
  1. Spawns `amp -x --settings-file …` with the scenario file as stdin.
  2. Captures stdout, stderr, and exit code with a generous timeout.
  3. Asserts the final stdout line matches `RESULT: PASS`.
  4. Writes the full transcript to `tests/integration/_artifacts/<scenario>.log`
     for failure triage.
- **Make target** (`make integration-tests`): convenience wrapper that
  checks required env vars are set and invokes
  `uv run pytest tests/integration -m integration`.

### Why Amp CLI

- Already the user's primary MCP host, so scenarios double as ergonomics
  smoke tests for the real product.
- `amp -x` reads from stdin and exits when done — pytest-friendly.
- `--settings-file` lets us pin a per-suite MCP configuration without
  touching the developer's user-level Amp config.
- Avoids us reimplementing an LLM driver, prompt loop, or tool-call parser.

## Sandbox Tenant Requirements

A dedicated, non-production Flightdeck tenant is required because scenarios
mutate state. The tenant must:

- Have OAuth client credentials with full read+write scope on policies and
  custom categories.
- Have at least one pre-existing endpoint (so endpoint search returns
  non-empty results); scenarios must not depend on a specific endpoint ID.
- Tolerate test artifacts being created and deleted continuously. All
  scenario-created objects use a recognizable name prefix
  (`mcp-it-<scenario>-<uuidshort>`) so stragglers from a crashed run can be
  swept by a janitor scenario.

Credentials are passed to the runner via env vars:

- `DOPE_CLIENT_ID`
- `DOPE_CLIENT_SECRET`
- `DOPE_INTEGRATION_BASE_URL` (optional — overrides default Flightdeck URL
  for staging environments; consumed by the server's existing internal base
  URL setting, not added as new public config)

The runner refuses to start if these are unset, so the suite never
accidentally runs against a developer's main tenant.

## Scenario Catalogue (initial)

Each bullet is one scenario file. Every scenario is self-cleaning unless
noted.

### Endpoints (read-only)

1. **`endpoints_search_basic.md`** — list endpoints with no filter, then
   re-run with `query`, with `status`, and with two filters at once
   (expecting a tool error). Verifies single-filter validation.

### Policies (read)

2. **`policies_read_all.md`** — list policies, pick the first, and call
   every read tool on it: `get_policy_assignments`,
   `get_policy_restrictions`, `get_policy_exceptions`,
   `get_policy_url_bypass`, `get_policy_application_bypass_entries`.
   Verify each returns a structured response.

### Policies (write — full lifecycle)

3. **`policy_lifecycle.md`** — `create_policy` → `list_policies` (confirm
   present) → `delete_policy` → `list_policies` (confirm absent).
4. **`policy_assignments_roundtrip.md`** — create policy → assign a
   principal → `get_policy_assignments` (confirm) → unassign → confirm
   removed → delete policy.
5. **`policy_restrictions_roundtrip.md`** — create policy → read
   restrictions → `update_policy_restrictions` for one category → re-read
   and confirm change → `reset_policy_restrictions_to_base` → confirm reset
   → delete policy.
6. **`policy_category_exceptions_roundtrip.md`** — create policy →
   `replace_policy_category_exceptions` for one category → confirm via
   `get_policy_exceptions` → replace with empty list → confirm cleared →
   delete policy.
7. **`policy_url_bypass_roundtrip.md`** — create policy →
   `upsert_policy_url_bypass` with two entries → confirm via
   `get_policy_url_bypass` → `delete_policy_url_bypass_entries` for one →
   confirm one remains → `reset_policy_url_bypass_to_base` → confirm reset
   → delete policy.
8. **`policy_application_bypass_roundtrip.md`** — create policy →
   `upsert_policy_application_bypass` → confirm via
   `get_policy_application_bypass_entries` → re-upsert with reduced state
   (since per-entry delete is not supported) → confirm shrink →
   `reset_policy_application_bypass_to_base` → confirm reset → delete
   policy.

### Custom categories (read + write — full lifecycle)

9. **`custom_category_lifecycle.md`** — `create_custom_category` →
   `list_custom_categories` (confirm present) → `add_urls_to_custom_category`
   with three URLs → `get_custom_category_urls` (confirm) →
   `delete_single_url_from_custom_category` → confirm two remain →
   `delete_all_urls_from_custom_category` → confirm empty →
   `delete_custom_category` → confirm absent.

### Cross-cutting

10. **`error_surfaces.md`** — invoke `get_policy_restrictions` with a
    bogus policy ID, `delete_custom_category` with a bogus ID, and confirm
    the agent receives clear, non-leaky error messages (no tokens, no raw
    upstream traceback). The scenario passes when the agent reports
    user-friendly errors for all attempts.
11. **`janitor.md`** — list all policies and custom categories, delete any
    whose name matches the `mcp-it-` prefix. Run first in CI to clean up
    after crashed prior runs; safe to re-run.

## Scenario File Format

Each markdown file follows a fixed shape so the agent behaves predictably
and the runner can grade the result:

```md
# Scenario: <human-readable title>

## Goal
<one-paragraph description of what to accomplish>

## Steps
1. …
2. …
3. …

## Cleanup
<explicit teardown instructions; required even if the scenario failed mid-way>

## Result
After cleanup, print exactly one final line:
- `RESULT: PASS` if every step's verification matched expectations.
- `RESULT: FAIL: <short reason>` otherwise.
Do not print anything after that line.
```

A short shared preamble is prepended by the runner (not stored in the
scenario file) instructing the agent to: only use dope MCP tools, never
invent IDs, prefix all created object names with the scenario tag, and do
cleanup even on partial failure.

## Runner Behavior

- Per-scenario timeout: 5 minutes (configurable via env).
- Concurrency: scenarios run **serially by default** to avoid tenant-side
  race conditions; a `--workers N` opt-in can be added later once we
  confirm scenarios are isolated by name prefix.
- Marked with `@pytest.mark.integration` and skipped unless either
  `DOPE_RUN_INTEGRATION=1` is set or pytest is invoked with
  `-m integration`.
- On failure, attaches the captured transcript to the pytest output and
  preserves it under `tests/integration/_artifacts/`.
- Exit code is the standard pytest exit code so CI just consumes it.

## CI Wiring

- New GitHub Actions workflow `integration.yml`, triggered on:
  - `workflow_dispatch` (manual button).
  - Nightly schedule.
  - Optionally on PRs labelled `run-integration`.
- Job steps:
  1. `uv sync`.
  2. Install Amp CLI (pinned version).
  3. Run `make integration-tests` with sandbox credentials from GitHub
     Secrets.
  4. Upload `tests/integration/_artifacts/` as a workflow artifact.

## Success Criteria

Done means all of the following are true:

- `tests/integration/scenarios/` contains one markdown file per scenario in
  the catalogue above, each conforming to the file format.
- `make integration-tests` runs the full suite locally against a sandbox
  tenant when `DOPE_CLIENT_ID` / `DOPE_CLIENT_SECRET` /
  `DOPE_RUN_INTEGRATION=1` are set, and is a no-op skip otherwise.
- A failing scenario fails the pytest run with a transcript attached.
- The nightly GitHub Actions workflow runs the suite and uploads
  artifacts.
- Every tool listed in `README.md` is exercised by at least one scenario;
  this is enforced by a meta-test that parses `README.md` and the scenario
  files and fails if a tool name appears in the README's tool tables but in
  none of the scenarios.

## Out of Scope / Future Work

- Deterministic, non-LLM tool-level fuzzing harness (separate plan).
- Multi-tenant or multi-region scenarios.
- Metrics, cost tracking, or model-quality grading of agent transcripts.
- Parallel scenario execution.
