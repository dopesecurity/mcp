# dopesecurity-mcp-server

Local Model Context Protocol (MCP) server for the dope.security Flightdeck
partner API. Lets MCP-aware AI assistants list and search endpoints, manage
policies, and curate custom URL categories on a dope.security tenant.

## Overview

- Talks to the Flightdeck partner API at
  `https://api.flightdeck.dope.security/v1`.
- Runs locally over MCP `stdio`.
- **Read-only by default.** Write tools are exposed only when mutations are
  explicitly enabled.
- Authentication uses OAuth client-credentials (`DOPE_CLIENT_ID` /
  `DOPE_CLIENT_SECRET`). Tokens are cached and refreshed automatically.

## Installation

The recommended way to run the server in an MCP host is via `uvx`:

```sh
uvx dopesecurity-mcp-server --help
```

`uvx` is part of [uv](https://docs.astral.sh/uv/). Any MCP host that can spawn
a stdio process can launch the server.

## MCP client configuration

Add the server to your MCP client configuration:

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
        "DOPE_ENABLE_DESTRUCTIVE": "false",
        "DOPE_LOG_LEVEL": "INFO",
        "DOPE_TIMEOUT_SECONDS": "30"
      }
    }
  }
}
```

## Required credentials

Two environment variables must be set; they are never accepted as CLI flags or
tool arguments:

| Variable             | Required | Description                                |
| -------------------- | -------- | ------------------------------------------ |
| `DOPE_CLIENT_ID`     | yes      | OAuth client ID issued by the dope console |
| `DOPE_CLIENT_SECRET` | yes      | OAuth client secret                        |

The server never logs tokens, headers, request bodies, or secrets.

## Read-only default and two-tier write gating

The MCP tool surface is split into three tiers, each off by default:

1. **Read** — always registered. Listing, searching, and getting policy
   state. Cannot modify the tenant.
2. **Write** — registered when mutations are enabled. Per-entry
   creates, updates, upserts, assigns, unassigns, and per-entry
   deletes. Modifies tenant state but never drops a whole policy or
   wipes a whole section.
3. **Destructive** — registered only when **both** mutations and the
   destructive gate are enabled. Drops a whole policy or custom
   category, wipes every URL in a category, or resets a whole policy
   section back to base.

Tools are exposed according to the following flags:

| `DOPE_ENABLE_MUTATIONS` | `DOPE_ENABLE_DESTRUCTIVE` | Tools exposed |
| ----------------------- | ------------------------- | --------------- |
| `false`                 | `false`                   | read only       |
| `true`                  | `false`                   | read + write    |
| `true`                  | `true`                    | read + write + destructive |
| `false`                 | `true`                    | **server refuses to start** |


Even when write or destructive tools are exposed, Flightdeck may still
reject individual calls that exceed the caller's permissions.

## Public configuration reference

| Env var                  | CLI flag               | Default | Description                                                                                  |
| ------------------------ | ---------------------- | ------- | -------------------------------------------------------------------------------------------- |
| `DOPE_ENABLE_MUTATIONS`  | `--enable-mutations`   | `false` | Expose write tools that modify tenant state.                                                 |
| `DOPE_ENABLE_DESTRUCTIVE`| `--enable-destructive` | `false` | Additionally expose destructive tools (whole-policy drops, whole-section resets). Requires mutations. |
| `DOPE_TIMEOUT_SECONDS`   | `--timeout-seconds`    | `30`    | HTTP timeout for Flightdeck calls.                                                           |
| `DOPE_LOG_LEVEL`         | `--log-level`          | `INFO`  | Log verbosity (logs go to stderr only).                                                      |

## Available tools

### Endpoints (read-only)

| Tool                | Description                              |
| ------------------- | ---------------------------------------- |
| `search_endpoints`  | List or search endpoints (cursor paged). |

### Policies (read)

| Tool                                     | Description                              |
| ---------------------------------------- | ---------------------------------------- |
| `list_policies`                          | List all policies.                       |
| `get_policy_assignments`                 | Show users/groups assigned to a policy.  |
| `get_policy_restrictions`                | Show per-category restrictions.          |
| `get_policy_exceptions`                  | Show per-category exceptions.            |
| `get_policy_url_bypass`                  | List URL bypass entries.                 |
| `get_policy_application_bypass_entries`  | List application bypass entries.         |

### Policies (write — only when mutations enabled)

| Tool                                          | Description                                    |
| --------------------------------------------- | ---------------------------------------------- |
| `create_policy`                               | Create a new policy.                           |
| `assign_policy_principals`                    | Add users/groups to a policy.                  |
| `unassign_policy_principals`                  | Remove users/groups from a policy.             |
| `update_policy_restrictions`                  | Update per-category restrictions.              |
| `replace_policy_category_exceptions`          | Replace exceptions for the submitted category. |
| `upsert_policy_url_bypass`                    | Add or update URL bypass entries.              |
| `delete_policy_url_bypass_entries`            | Delete named URL bypass entries.               |
| `upsert_policy_application_bypass`            | Add or update application bypass entries.      |
| `delete_policy_application_bypass_entries`    | Delete named application bypass entries.       |

### Policies (destructive — only when both mutations and destructive are enabled)

| Tool                                       | Description                              |
| ------------------------------------------ | ---------------------------------------- |
| `delete_policy`                            | Delete a whole policy.                   |
| `reset_policy_restrictions_to_base`        | Reset all restrictions to Base.          |
| `reset_policy_url_bypass_to_base`          | Reset URL bypass to Base.                |
| `reset_policy_application_bypass_to_base`  | Reset application bypass to Base.        |

### Custom categories (read)

| Tool                       | Description                       |
| -------------------------- | --------------------------------- |
| `list_custom_categories`   | List all custom categories.       |
| `get_custom_category_urls` | List URLs in a custom category.   |

### Custom categories (write — only when mutations enabled)

| Tool                                  | Description                          |
| ------------------------------------- | ------------------------------------ |
| `create_custom_category`              | Create a new custom category.        |
| `add_urls_to_custom_category`         | Add URLs to a custom category.       |
| `delete_single_url_from_custom_category` | Remove one URL from a category.   |

### Custom categories (destructive — only when both mutations and destructive are enabled)

| Tool                                  | Description                          |
| ------------------------------------- | ------------------------------------ |
| `delete_custom_category`              | Delete a whole custom category.      |
| `delete_all_urls_from_custom_category`| Wipe every URL from a category.      |

## Flightdeck routes deliberately omitted from MCP

Some Flightdeck partner API routes are intentionally **not** exposed as
MCP tools and will not be added. This is the list — treat it as a
"don't bother proposing this" register.

- `PUT /custom_categories/{name}/urls` — overwrite-all semantics. An
  agent calling this with a partial list silently destroys every URL it
  didn't mention. Use `add_urls_to_custom_category`,
  `delete_single_url_from_custom_category`, and
  `delete_all_urls_from_custom_category` instead, which force the agent
  to state intent explicitly.

## Known limitations

- Pagination is cursor-based; the server does not auto-fetch all pages.
- Assignment write tools (`assign_policy_principals`,
  `unassign_policy_principals`) are best-effort and non-atomic: the server
  reads, merges, and writes back. Concurrent external changes can race.

## Development and verification

From the repository root:

```sh
uv sync
uv run pytest src
uv run ruff check .
uv run mypy src
uv run dopesecurity-mcp-server --help
```

### Running a local checkout from an MCP client

To point an MCP client (Amp, Claude Desktop, etc.) at your local checkout
instead of the published `uvx` package, replace the `command`/`args` so the
client launches the server through `uv run --directory`:

```json
{
  "mcpServers": {
    "dope-security-dev": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/dopemcp",
        "dopesecurity-mcp-server"
      ],
      "env": {
        "DOPE_CLIENT_ID": "your-client-id",
        "DOPE_CLIENT_SECRET": "your-client-secret",
        "DOPE_ENABLE_MUTATIONS": "true",
        "DOPE_ENABLE_DESTRUCTIVE": "true",
        "DOPE_LOG_LEVEL": "DEBUG"
      }
    }
  }
}
```

Replace `/absolute/path/to/dopemcp` with the path to your clone. The MCP
client spawns the server over stdio on demand.
