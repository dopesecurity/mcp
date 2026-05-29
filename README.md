# dopesecurity-mcp-server

The Dope MCP is a local [Model Context Protocol](https://modelcontextprotocol.io)
server that lets an AI assistant talk to your dope.security tenant —
look at endpoints, read and tweak policies, and curate custom URL
categories. It wraps most of the Flightdeck partner API, runs on your
machine, and is **read-only out of the box**: nothing changes in your
tenant until you explicitly turn writes on. It's currently in beta, we
hope you enjoy using it.

## Installation

Installation is via `uvx`.

Runs the server on demand. Nothing is installed globally.

**Prerequisites**

1. Install `uv` — see [Astral's install guide](https://docs.astral.sh/uv/getting-started/installation/).
2. Install a Python runtime with `uv`:

   ```sh
   uv python install 3.11
   ```

**MCP client config**

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
        "DOPE_ENABLE_DESTRUCTIVE": "false"
      }
    }
  }
}
```

## Three tiers of access

The tool surface is gated by two environment variables, both `false`
by default. Tools that aren't enabled by the active combination are
**not registered** at all — they don't exist on the MCP wire.

| `DOPE_ENABLE_MUTATIONS` | `DOPE_ENABLE_DESTRUCTIVE` | What the agent can do                                                                                                                            |
| ----------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `false`                 | `false`                   | **Read-only.** Inspect endpoints, policies, custom categories. Cannot modify the tenant.                                                         |
| `true`                  | `false`                   | **Read + write.** Per-entry creates, updates, upserts, assigns, unassigns, and per-entry deletes. Cannot drop a whole policy or wipe a section.  |
| `true`                  | `true`                    | **Read + write + destructive.** Adds whole-policy drops, whole-section resets to base, whole-custom-category deletes, and wipe-all-URLs.         |
| `false`                 | `true`                    | Invalid — the server refuses to start.                                                                                                           |

Flightdeck RBAC still applies on top of whichever tier you enable:
even when a tool is registered, Flightdeck may reject the call because
your OAuth client's role doesn't permit it. Start with read-only,
flip to mutations when you trust the agent's workflow, and only enable
destructive when you explicitly want the agent to be able to start
over.

## Configuration reference

| Env var                  | CLI flag               | Default | Description                                                                                  |
| ------------------------ | ---------------------- | ------- | -------------------------------------------------------------------------------------------- |
| `DOPE_CLIENT_ID`         | —                      | —       | API client ID issued from the dope console. **Required.**                                  |
| `DOPE_CLIENT_SECRET`     | —                      | —       | API client secret issued from the dope console. **Required.**                              |
| `DOPE_ENABLE_MUTATIONS`  | `--enable-mutations`   | `false` | Expose write tools that modify tenant state.                                                 |
| `DOPE_ENABLE_DESTRUCTIVE`| `--enable-destructive` | `false` | Additionally expose destructive tools (whole-policy drops, whole-section resets). Requires mutations. |
| `DOPE_TIMEOUT_SECONDS`   | `--timeout-seconds`    | `30`    | HTTP timeout for Flightdeck calls.                                                           |
| `DOPE_LOG_LEVEL`         | `--log-level`          | `INFO`  | Log verbosity (logs go to stderr only).                                                      |

`DOPE_CLIENT_ID` and `DOPE_CLIENT_SECRET` should be provided as
environment variables. You can grab the credentials from the
[dope console](https://inflight.dope.security/dope.console/settings/api-client-credentials).

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

## Developing

### Setup and verification

From the repository root:

```sh
make install      # uv sync --locked
make check        # lint + typecheck + unit tests
make integration-tests  # requires DOPE_MCP_TESTS_CLIENT_SECRET
uv run dopesecurity-mcp-server --help
```

Run `make help` to see all available targets.

### Known limitations

- `assign_policy_principals` and `unassign_policy_principals` are
  read-merge-write on top of Flightdeck's overwrite-only assignments
  endpoint, so concurrent edits to the same policy may be clobbered.
- Pagination is cursor-based; the mcp server does not auto-fetch all pages.

### Flightdeck routes deliberately omitted from MCP

Some Flightdeck partner API routes are intentionally **not** exposed as
MCP tools and will not be added. This is the list — treat it as a
"don't bother proposing this" register.

- `PUT /custom_categories/{name}/urls` — overwrite-all semantics. An
  agent calling this with a partial list silently destroys every URL it
  didn't mention. Use `add_urls_to_custom_category`,
  `delete_single_url_from_custom_category`, and
  `delete_all_urls_from_custom_category` instead, which force the agent
  to state intent explicitly.

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
