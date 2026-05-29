# MCP Research Notes For dope.security

Last updated: 2026-04-30

## Goal

Capture the MCP implementation guidance and framework tradeoffs most relevant to building a dope.security MCP server on top of the Flightdeck partner API.

## Executive Takeaways

- MCP is a client-server protocol for exposing tools, resources, and prompts to AI hosts such as Claude Desktop, VS Code, and similar products.
- For a dope.security integration, the first useful surface will be tools, not prompts or complex resources. The partner API is already action-oriented and maps naturally to MCP tools.
- MCP has two transports that matter here:
  - `stdio` for local, single-client usage where the host launches the server as a subprocess.
  - `streamable-http` for remote or multi-client usage over HTTP.
- For production remote deployments, MCP guidance points toward HTTP transport plus OAuth 2.1 style authorization at the transport layer.
- The biggest implementation choice is language and framework:
  - Python has the strongest official high-level path today because the official Python SDK includes `FastMCP` and explicitly documents streamable HTTP and auth hooks.
  - TypeScript has a strong official SDK, but remote HTTP usage is lower-level and requires more session and transport wiring.
  - TypeScript `FastMCP` looks productive and feature-rich, but it is a community framework rather than the official SDK.
- Best initial recommendation: build v1 with the official Python SDK using `FastMCP`, start with a tool-focused server, and keep remote auth and partner API credentials server-managed.
- Recommended server shape: keep `FastMCP` as a thin transport layer, build shared dependencies in the SDK's lifespan context, and put Flightdeck-specific logic in a small service layer plus API client.
- Recommended dependency placement: settings, `httpx.AsyncClient`, token manager, and domain services should be created once per process in the lifespan hook and accessed from tools through typed app context.
- Recommended Python package shape: use a normal `src/` layout with separate modules for `tools`, `services`, `flightdeck` client/auth, and configuration, but avoid extra repository or framework layers that only wrap the partner API again.
- Recommended error model: normalize Flightdeck HTTP failures into a small set of domain errors, return concise agent-safe tool errors for expected failures, and reserve MCP protocol errors for actual protocol or transport faults.

## MCP Basics That Matter

### Architecture

Official MCP docs describe three participants:

- Host: the AI application, such as Claude Desktop or VS Code.
- Client: the host-side connector that maintains a connection to one MCP server.
- Server: the program that exposes capabilities.

MCP is split into two layers:

- Data layer: JSON-RPC lifecycle, capability negotiation, tools, resources, prompts, notifications.
- Transport layer: `stdio` or `streamable-http`, including auth behavior.

This distinction matters because most application logic lives in tools, while deployment and security choices live in the transport.

### Core Primitives

- Tools: executable functions. Best fit for REST-backed operations, searches, updates, and actions.
- Resources: read-only or file-like data that clients can inspect or embed.
- Prompts: reusable prompt templates.

For dope.security, most of the partner API should initially map to tools. A few read-heavy objects could later become resources, but that is optional for v1.

### Transport Guidance

#### stdio

Use when:

- The server is local.
- A desktop client launches it directly.
- You want the smallest possible first integration.

Important rule from the official docs:

- Never write non-protocol output to stdout.
- Log to stderr only.

#### streamable-http

Use when:

- The server is hosted remotely.
- Multiple users or clients need access.
- You want central auth, auditing, deployment, and revocation.

The official architecture docs describe streamable HTTP as the transport for remote servers and note that it supports standard HTTP auth patterns. Official Python SDK docs explicitly call streamable HTTP the recommended production transport, especially in stateless mode with JSON responses for scalability.

## Security And Auth Guidance

This matters more than usual here because dope.security is a security product and the eventual MCP server may expose administrative operations.

### Official Guidance

- Authorization is optional for MCP in general, but if HTTP transport is used, the protocol specifies an OAuth 2.1 style approach.
- For `stdio`, the official guidance is not to use the HTTP auth flow. Local credentials should come from the environment or local libraries.
- MCP servers must not accept a client token and simply pass it through to downstream APIs.
- MCP servers must validate that inbound tokens are meant for the MCP server itself.
- Least privilege is the intended model.
- Session identifiers must not be treated as authorization.

### Practical Implications For This Project

- The dope.security MCP server should own the partner API credential flow itself.
- The server should exchange `client_id` and `client_secret` for a Flightdeck bearer token and cache or refresh it internally.
- If we later expose the MCP server remotely, remote users should authenticate to the MCP server separately from the MCP server authenticating to the Flightdeck API.
- For mutating tools, assume human approval in the host UI is important even if the protocol does not force a specific UX.

## Debugging And Developer Workflow

The official recommendation for testing is the MCP Inspector.

Useful notes:

- It supports local stdio servers and remote HTTP servers.
- It shows tools, resources, prompts, schemas, results, and notifications.
- It can export `mcp.json` style launch config.
- It has its own security considerations because it can launch local processes. Keep it bound to localhost and do not disable its auth protections casually.

This should be part of the default development loop regardless of framework choice.

## Credential Provisioning For Local Users

The current question is narrower than full MCP transport auth:

- Users already have a dope.security `client_id` and `client_secret`.
- The MCP server will exchange those for Flightdeck bearer tokens.
- We want the best way for users to provide those credentials to a local MCP server.

### What Official Guidance Points To

The official MCP authorization guidance is clear on the main distinction:

- For `stdio` servers, do not use the HTTP OAuth authorization flow.
- Instead, local servers should retrieve credentials from the environment.

That lines up with how common MCP clients and tooling work:

- Claude Desktop local server config supports an `env` block.
- MCP Inspector supports environment variables via config files and `-e` flags.
- VS Code documents avoiding hardcoded secrets and recommends input variables or environment files.

### Recommended Pattern

For the dope.security server, the best default is:

1. The server accepts credentials only through environment variables.
2. The client launches the server with those environment variables set.
3. The server performs token exchange internally and never exposes the raw secret as a tool parameter.

Recommended variable names:

- `DOPE_CLIENT_ID`
- `DOPE_CLIENT_SECRET`

Optional future additions:

- `DOPE_API_BASE_URL`
- `DOPE_TOKEN_URL`
- `DOPE_TIMEOUT_SECONDS`

### Why Environment Variables Are The Right Default

- They align with MCP guidance for local `stdio` servers.
- They keep secrets out of the model-visible tool interface.
- They avoid putting secrets into command arguments, which are easier to leak via process listings and logs.
- They are supported by common MCP tooling.
- They keep the server implementation portable across Claude Desktop, VS Code, Inspector, and other clients.

### Preferred User Flows

#### Best Generic Flow

Use a user-local launcher or client config that injects only the two required environment variables into the MCP process.

This can be implemented in two common ways:

- user-local MCP config with an `env` section
- wrapper script that loads a `.env` file or secret store and then starts the server

This is the best overall recommendation because it keeps the server contract simple while staying compatible with different clients.

#### Simplest User Setup

Let users place the credentials in the MCP client's user-level config, not in a workspace-shared config.

Example shape for a local stdio config:

```json
{
  "mcpServers": {
    "dope-security": {
      "command": "uv",
      "args": ["run", "dopemcp"],
      "env": {
        "DOPE_CLIENT_ID": "your-client-id",
        "DOPE_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

This is acceptable for local-only setups if the config file is not shared or committed.

#### Better Team Setup

If the server config will live in a repo, do not commit the raw secret values. Instead:

- keep the checked-in config free of secrets
- use a wrapper script that loads per-user local env values
- or use client features such as env files, input variables, or secret interpolation where available

This is especially relevant for VS Code workspaces, because MCP config can be stored in `.vscode/mcp.json` and shared with a team.

### Recommended UX For The Server

The dope.security MCP server should:

- fail fast on startup or first authenticated request if `DOPE_CLIENT_ID` or `DOPE_CLIENT_SECRET` is missing
- emit a clear stderr-only error telling the user which variables must be set
- never accept `client_id` or `client_secret` as tool inputs
- never echo secrets in logs or error messages
- cache the exchanged access token internally until refresh is needed

Good startup error message shape:

```text
Missing required credentials. Set DOPE_CLIENT_ID and DOPE_CLIENT_SECRET in the MCP server environment.
```

### Anti-Patterns To Avoid

- Do not make `client_id` and `client_secret` part of tool schemas.
- Do not ask users to paste secrets into chat.
- Do not pass secrets as plain command-line args.
- Do not commit secrets in workspace MCP config.
- Do not log token exchange payloads or headers.

### Strong Recommendation For v1

For the first release, document one blessed local-auth path:

1. Users supply `DOPE_CLIENT_ID` and `DOPE_CLIENT_SECRET` via environment variables.
2. The MCP server reads them from process env.
3. The server exchanges them for bearer tokens internally.

If we want to reduce friction later, we can add an optional wrapper or setup command that writes a user-local config file or stores the secrets in the OS keychain. But the core server contract should still remain env-based.

## Delivering A Local Python MCP To Users

If we build this MCP in Python, the delivery question is really about how users get a runnable local command that an MCP client can launch over `stdio`.

### What The Ecosystem Recommends

The strongest current signals are:

- The official MCP reference servers recommend `uvx` for Python servers, and explicitly say `uvx` is recommended for ease of use and setup.
- The `uv` docs recommend `uvx` for most one-off or tool-style execution, and reserve `uv tool install` for cases where the executable should be persistently available on `PATH`.
- Common MCP client configs launch local servers by command name plus args, which fits a packaged Python CLI well.

That leads to a simple default:

- publish the server as a normal Python package
- expose a console script entry point
- tell users to run it with `uvx <package-name>` from their MCP client config

### Recommended Delivery Options

#### 1. PyPI Package + `uvx` Command

This is the best default for technical users.

What it looks like:

- publish to PyPI
- define a console entry point in `pyproject.toml`
- document an MCP config that uses `command: "uvx"`

Why it is the best default:

- It matches the official Python MCP server guidance.
- It gives users a zero-install or near-zero-install path after installing `uv`.
- It avoids asking users to clone the repo or manage virtualenvs manually.
- It works naturally with local `stdio` clients.

Recommended config shape:

```json
{
  "mcpServers": {
    "dope-security": {
      "command": "uvx",
      "args": ["dopemcp"],
      "env": {
        "DOPE_CLIENT_ID": "your-client-id",
        "DOPE_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

Implementation implication:

- the package name on PyPI can differ from the command name, but the command name should be short and stable
- for example, package `dopemcp` with script `dopemcp`

#### 2. PyPI Package + `uv tool install`

This is the best option when users want a persistent local command.

Example user flow:

```bash
uv tool install dopemcp
```

Then the MCP client config can use:

```json
{
  "mcpServers": {
    "dope-security": {
      "command": "dopemcp",
      "env": {
        "DOPE_CLIENT_ID": "your-client-id",
        "DOPE_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

Why this is useful:

- More stable for users who run the server frequently.
- Avoids repeated first-run resolution.
- Good for enterprise docs where a fixed installed executable is easier to reason about.

Tradeoff:

- Slightly more setup than `uvx`.

#### 3. Source Repo + `uv run`

This is best for development, contributors, and pre-release testing, not for the main user distribution path.

Example shape:

```json
{
  "mcpServers": {
    "dope-security-dev": {
      "command": "uv",
      "args": ["run", "dopemcp"],
      "env": {
        "DOPE_CLIENT_ID": "your-client-id",
        "DOPE_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

Why this is not the main recommendation:

- It assumes the user has the repo checked out.
- It couples usage to local project layout.
- It is great for us during development, but not ideal as the public install story.

#### 4. Local Wheel Or Git-Based Install For Early Access

Useful for previews before publishing to PyPI.

Options:

- install from a local wheel with `uv tool install dist/<wheel>.whl`
- run from git with `uvx --from git+https://... <command>`

This is useful for:

- dogfooding
- internal testing
- release candidates

But it is still a secondary delivery path.

#### 5. MCPB Bundle For One-Click Desktop Install

This is the optional path for less technical Claude Desktop users.

MCPB is the Anthropic bundle format for one-click installation of local MCP servers. The MCPB repo explicitly supports Python bundles and also has a newer `uv`-based runtime mode.

Why it is appealing:

- one-click installation in Claude Desktop
- friendlier configuration UX
- automatic updates and user-configurable variables in supported clients

Important caveat:

- the MCPB docs still recommend Node.js over Python to reduce installation friction
- traditional Python bundles are harder because portable bundling of compiled Python dependencies is limited
- the newer `uv` runtime support improves this story, but MCPB is still more client-specific than a plain PyPI package

Recommendation:

- do not make MCPB the only delivery path for v1
- consider it as an additional packaging target later if Claude Desktop ease-of-install becomes important

### Recommended Packaging Shape

For a Python MCP intended for local use, the package should look like a standard Python CLI tool.

That means:

- `pyproject.toml` with normal package metadata
- a console script entry point under `[project.scripts]`
- a README with MCP client config examples
- PyPI publishing as the main artifact

Example shape:

```toml
[project]
name = "dopemcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "mcp",
  "httpx"
]

[project.scripts]
dopemcp = "dopemcp.__main__:main"
```

### Documentation We Should Provide To Users

Whatever distribution method we choose, the package docs should include:

- a Claude Desktop config example
- a VS Code `mcp.json` example
- the required env vars for credentials
- a quick smoke test with MCP Inspector
- upgrade instructions

For `uvx`, the docs should be extremely explicit because it is still new to many users.

### Recommendation Summary

For this project, the best delivery strategy is:

1. Primary: publish a PyPI package with a `dopemcp` console script and recommend `uvx dopemcp` in local MCP configs.
2. Secondary: support `uv tool install dopemcp` for users who want a persistent command.
3. Development only: support `uv run dopemcp` from a checked-out repo.
4. Optional later: add an MCPB bundle if we want a smoother Claude Desktop installation story.

If we want one sentence to guide implementation:

- build it like a normal Python CLI package, distribute it on PyPI, and treat `uvx` as the default local MCP launch mechanism.

## Tool Granularity And Selection

One of the most important design questions is whether the MCP should expose:

- many narrow tools that mirror individual API endpoints or sub-operations
- a few broad tools that cover larger workflows

The best answer is neither extreme.

### What Current Guidance Suggests

Anthropic's tool-writing guidance says more tools do not automatically improve outcomes. A common mistake is wrapping raw APIs or existing software operations directly, even when those boundaries are not ergonomic for agents. Their guidance favors tools that consolidate commonly chained work and align with user intent.

The AWS MCP guidance says essentially the same thing in more operational terms:

- granular, tool-per-API designs increase context usage, latency, and orchestration complexity
- coarse-grained, workflow-oriented tools simplify agent behavior by moving deterministic orchestration into the tool
- but tools can become too coarse if they take on multiple distinct user intents or too many parameters

The strongest practical heuristics from that guidance are:

- design tools around user workflows, not raw endpoints
- bundle operations that commonly occur together
- decompose tools that exceed roughly eight parameters or cover multiple distinct intents
- separate read and write operations
- avoid large numbers of near-duplicate tools because tool selection gets worse when names and purposes overlap

### Decision Rule

Prefer workflow-sized tools.

That means:

- bigger than a raw CRUD wrapper when a user intent usually spans multiple low-level calls
- smaller than a generic "do anything with a policy" tool when the operation space is heterogeneous

In practice, the right unit is usually:

- one tool per stable user intent
- one tool per state boundary
- one tool per mutation model

### Applying This To Flightdeck Policies

The policy API is already split into meaningful state boundaries:

- policy metadata and lifecycle
- content restrictions
- content exceptions
- assignments
- URL bypass
- application bypass

Those are not just transport details. They have different semantics:

- restrictions are partial updates and can reset inheritance
- exceptions are full replacement per category
- assignments replace provided lists while preserving omitted fields
- URL bypass has upsert and delete semantics plus inheritance reset
- application bypass mirrors URL bypass but has platform-specific structure

That makes a single `update_policy` tool a bad fit.

Why a single `update_policy` tool is likely worse:

- It would have too many optional branches and parameters.
- It would mix unrelated mutation semantics in one schema.
- The model would need to infer which submode to activate.
- Validation and error messages would be harder to make clear.
- Safety review becomes harder because one tool can change many unrelated aspects of policy state.

### Recommended Policy Tool Shape

For policy writes, prefer separate tools such as:

- `create_policy`
- `delete_policy`
- `update_policy_restrictions`
- `update_policy_exceptions`
- `update_policy_assignments`
- `upsert_policy_url_bypass`
- `delete_policy_url_bypass_entries`
- `upsert_policy_application_bypass`
- `delete_policy_application_bypass_entries`

For policy reads, prefer separate read tools such as:

- `list_policies`
- `get_policy_content`
- `get_policy_assignments`
- `get_policy_url_bypass`
- `get_policy_application_bypass`

This is more tools than a single mega-tool, but each one still maps to a clear user intent and a distinct mutation contract.

### Why This Boundary Is Better

It preserves the advantages of coarse-grained tools without going too far:

- Each tool corresponds to a real administrative task.
- Each tool can have a compact, purpose-built schema.
- Each tool can explain its own replacement or merge semantics clearly.
- Read and write paths stay separate.
- Destructive actions can carry stronger warnings and examples.
- The model is less likely to pick the wrong operation than if many nearly identical sub-tools exist.

### What To Avoid

#### Too Coarse

Avoid tools like:

- `update_policy`
- `modify_policy`
- `manage_policy`

These names hide too many different behaviors behind one interface.

#### Too Fine

Also avoid exploding the surface into tools like:

- `set_policy_category_restriction`
- `set_policy_custom_category_restriction`
- `set_policy_category_exception_for_user`
- `set_policy_category_exception_for_group`
- `toggle_policy_default_url_bypass_entry`
- `add_policy_custom_url_bypass_entry`
- `remove_policy_custom_url_bypass_entry`

This pushes too much orchestration back onto the model, increases tool count, and creates overlapping names that are easier to confuse.

### Recommended Granularity For This Project

For dope.security, the best v1 shape is:

- read tools that correspond to major readable resources
- write tools that correspond to major policy mutation families
- no generic catch-all write tool
- no ultra-atomic tool-per-field design

Stated simply:

- do not mirror every internal field mutation
- do not collapse all policy editing into one tool
- use one tool per meaningful admin workflow boundary

### A Good Mental Model

Use this test when deciding whether a tool boundary is right:

1. Would a human describe this as one admin action?
2. Do the underlying updates share the same semantics?
3. Can the schema stay understandable without a long list of mutually exclusive options?
4. Would splitting this tool force the model to make multiple calls in most realistic uses?

If the answers are yes, it is probably the right tool boundary.

### Concrete Recommendation For The Example Question

For the question "single `update_policy` tool or separate `update_policy_restrictions`, `update_policy_exceptions`, `update_policy_bypass`, etc.?"

Recommended answer:

- use separate tools for `update_policy_restrictions`, `update_policy_exceptions`, `update_policy_assignments`, and bypass operations
- do not use one catch-all `update_policy`

I would still split bypass further into URL and application bypass, because they have different payload structure and platform behavior.

So the recommended write surface is closer to a handful of medium-sized workflow tools than either one giant tool or dozens of tiny tools.

## Mutation Semantics: Replace vs Add/Remove

Another important design choice is whether MCP write tools should prefer:

- overwrite or replace semantics, similar to `PUT`
- incremental action semantics, like add, remove, upsert, or delete

Again, the best answer is mixed and should follow user intent plus safety.

### General Recommendation

For agent-facing tools, prefer the least surprising mutation model.

That usually means:

- use incremental add, remove, upsert, and delete tools when users usually want to change part of a collection
- reserve full replace semantics for cases where the natural admin intent is explicitly "make the state exactly this"

Why this is usually better for agents:

- full replacement is more destructive if the model omits an existing entry
- incremental tools are easier to reason about when a user says "add", "remove", "disable", or "assign"
- destructive intent is more explicit in tool names like `delete_*` or `unassign_*`
- overwrite tools often require the model to know the full current state before acting safely

### What Existing Guidance Implies

Anthropic's guidance emphasizes making tool purpose explicit and aligning tools with how agents naturally think about actions. AWS guidance emphasizes separating read and write operations, using sensible defaults, and making tool contracts easier for the model to use correctly.

Taken together, that points toward this rule:

- prefer explicit mutation verbs over hidden replacement semantics

If a tool replaces state, that should be obvious from the name and description.

### Applying This To Flightdeck

The underlying policy endpoints already show that not all mutation families behave the same way:

- [`/policies/{policy_name}/content/exceptions`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L642-L726) replaces the exception set for each submitted category
- [`/policies/{policy_name}/assignments`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L727-L898) replaces provided user or group lists
- [`/policies/{policy_name}/bypass/urls`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L899-L1193) supports upsert plus separate delete
- application bypass follows the same general pattern as URL bypass

Those semantics are fine at the REST layer, but they are not always ideal to expose directly to an agent.

### Recommended MCP Pattern

#### Prefer Incremental Tools For Collection Editing

For collections where admins usually add or remove a few entries, prefer action-oriented tools.

Examples:

- `assign_policy_users_and_groups`
- `unassign_policy_users_and_groups`
- `upsert_policy_url_bypass`
- `delete_policy_url_bypass_entries`
- `upsert_policy_application_bypass`
- `delete_policy_application_bypass_entries`

These are safer than a generic replace-all tool because they reduce accidental loss of unrelated entries.

#### Use Replace Semantics Only When The Domain Is Naturally Replace-Oriented

Some domains are naturally expressed as "set the rule state for this slice of policy."

Examples:

- `update_policy_restrictions`
- `replace_policy_category_exceptions`

These can still be good tools, but the replacement behavior should be explicit in the name and description.

For exceptions in particular, I would avoid a vague name like `update_policy_exceptions` if the behavior is actually full replacement per category. A clearer name such as `replace_policy_category_exceptions` is safer and more honest.

#### Avoid Hidden Replace Semantics Behind Neutral Names

Tool names like these are risky:

- `update_policy_assignments`
- `update_policy_exceptions`

They sound merge-like, but the underlying API may remove omitted items.

If we keep these names, the description must say very clearly:

- submitted lists replace existing values for the provided scope
- omitted entries may be removed for that scope

But in many cases it is better to express the intent directly in the tool name.

### Concrete Recommendation For dope.security

For v1, I would use this rule:

- use add/remove/upsert/delete semantics for assignments and bypasses
- use explicit replace semantics for restrictions and category exception sets when that matches the domain model
- do not expose ambiguous overwrite behavior behind a generic `update_*` tool unless the description is extremely explicit

In practical terms, this means I would lean toward tools like:

- `set_policy_restrictions`
- `replace_policy_category_exceptions`
- `assign_policy_principals`
- `unassign_policy_principals`
- `upsert_policy_url_bypass`
- `delete_policy_url_bypass_entries`
- `upsert_policy_application_bypass`
- `delete_policy_application_bypass_entries`

### A Simple Heuristic

Use this question:

1. If the model leaves out an existing item, would that omission silently delete something important?

If yes, prefer add/remove or make replacement explicit in the tool name.

2. Does the user naturally think in terms of "set the full state"?

If yes, replace semantics may be the right tool.

3. Does the user naturally think in terms of "add this", "remove that", or "toggle these"?

If yes, expose incremental tools.

### Direct Answer To The Question

For MCP tools, it is usually better to prefer explicit add/remove/upsert/delete semantics over hidden overwrite semantics.

Use full replacement only when:

- the operation is naturally replace-oriented
- the scope is narrow and obvious
- the destructive behavior is explicit in the tool contract

So for this project:

- bypasses and assignments should lean POST/DELETE-style in spirit
- restrictions can be set directly
- exceptions should probably use an explicitly named replace-style tool rather than a vague update tool

## Naming And Casing Conventions

There is some guidance here, but not a single universal rule like "MCP requires snake_case."

### What The MCP Spec Says

The MCP tools spec gives constraints on tool names, but not one mandatory naming style.

Current tool-name guidance in the spec is roughly:

- tool names should be case-sensitive
- tool names should use ASCII letters, digits, underscore, hyphen, and dot
- tool names should not contain spaces or punctuation beyond those separators

So the protocol allows styles like:

- `get_user`
- `getUser`
- `admin.tools.list`

That means the main requirement is not camelCase versus snake_case. The main requirement is clarity, consistency, and compatibility.

### What The Best-Practice Guidance Says

Anthropic's tool-writing guidance emphasizes:

- make names reflect natural task boundaries
- avoid ambiguity
- use explicit parameter names like `user_id` rather than vague ones like `user`
- choose namespacing patterns consistently

AWS's MCP guidance is more explicit about naming shape and recommends:

- a consistent naming standard
- `domain_noun_verb` style names such as `github_issue_create`

That recommendation strongly points toward underscore-separated names for tools.

### Practical Conclusion

There is no strong official guidance saying camelCase is wrong.

But there is strong practical guidance saying:

- pick one style
- keep it consistent
- favor names that are easy for models to scan and disambiguate

For this kind of server, snake_case is the safest choice.

Why:

- It fits the Python implementation language.
- It aligns with many spec examples and common tool ecosystems.
- It works well with domain-prefixed naming like `policy_restrictions_set` or `policy_url_bypass_upsert`.
- It avoids mixed-style friction between tool names and parameter names.

### Recommended Convention For dope.security

Use:

- snake_case for tool names
- snake_case for input parameter names
- snake_case for output field names that we define ourselves

Examples:

- `policy_restrictions_set`
- `policy_category_exceptions_replace`
- `policy_principals_assign`
- `policy_url_bypass_upsert`

Parameter examples:

- `policy_name`
- `category_name`
- `custom_category_name`
- `user_emails`
- `group_emails`

### What To Do About The Underlying API's Existing Casing

The Flightdeck API uses camelCase in parts of the wire format, such as `inheritsFromBase` and `hasNextPage`.

For the MCP layer, I would not automatically expose those exact field names if we are designing a model-facing schema from scratch.

Better approach:

- translate external API casing into our own consistent MCP schema
- keep the translation inside the server implementation

For example:

- REST field `inheritsFromBase` becomes MCP field `inherits_from_base`
- REST field `hasNextPage` becomes MCP field `has_next_page`

This makes the MCP interface internally consistent, even if the downstream API is not.

### When To Preserve Original Casing

Preserve API-native casing only when there is a strong reason, such as:

- users already know the downstream API well and expect that exact shape
- the tool is intentionally a thin API wrapper
- a field name must match an external contract exactly

That is not the direction we have been taking here. We are designing an agent-friendly interface, not a raw API mirror.

### Recommendation Summary

For this server:

- choose snake_case for all MCP-facing names
- avoid mixing camelCase and snake_case in tool schemas
- translate the underlying API's camelCase fields internally rather than leaking them into the MCP contract

So the answer to "is there guidance?" is:

- yes on consistency and clarity
- weak on one mandatory casing style
- practical recommendation: use snake_case end-to-end in the MCP layer

## Framework And SDK Options

### Option 1: Official Python SDK With FastMCP

What the docs show:

- `FastMCP` is the high-level server API in the official Python SDK.
- Tools can be declared directly from Python functions.
- Streamable HTTP is directly supported.
- Official docs show `stateless_http=True` and `json_response=True` as the recommended production shape.
- Auth settings and token verification hooks are part of the documented Python path.

Why this is strong:

- Lowest boilerplate for wrapping REST calls as tools.
- Best documented path for remote production deployment among the options reviewed.
- Good fit for a server that mainly brokers an external REST API.
- Easier to add server-side token caching, request normalization, and auth checks without building transport plumbing by hand.

Tradeoffs:

- If the team strongly prefers TypeScript, this adds a language decision.
- Some ecosystem examples still mix older low-level MCP patterns with newer FastMCP patterns, so version discipline matters.

Assessment:

- Best default choice unless there is an organizational reason to standardize on Node.

### Option 2: Official TypeScript SDK

What the docs show:

- Strong official support for stdio and streamable HTTP.
- Straightforward tool registration with schemas.
- Remote HTTP mode is possible, but session management is more manual.
- The SDK is closer to the protocol and gives more control.

Why this is strong:

- Official SDK.
- Strong fit if we want a Node distribution story or already expect surrounding JavaScript tooling.
- Explicit, low-magic implementation.

Tradeoffs:

- More ceremony than Python `FastMCP`.
- Remote deployment requires more wiring around transports, sessions, and Express or Node HTTP integration.

Assessment:

- Good choice if Node or TypeScript is a project constraint.
- Slightly slower path to a clean v1 than Python `FastMCP`.

### Option 3: TypeScript FastMCP

What the docs show:

- Opinionated framework on top of the official TypeScript SDK.
- Built-in handling for tools, resources, prompts, sessions, auth-related features, and inspection-friendly workflows.
- Strong local developer experience and quick start.

Why this is strong:

- Likely the fastest TypeScript developer experience.
- Good feature coverage for remote servers.
- Attractive if we want TypeScript without hand-rolling transport details.

Tradeoffs:

- Not the official SDK.
- Adds framework dependency and potential lag against spec or SDK changes.

Assessment:

- Best TypeScript path if developer speed matters more than staying directly on the official SDK.
- Still not my first recommendation for this project unless the team wants TS specifically.

## Options That Look Less Relevant Right Now

- FastAPI-to-MCP style generators are a poor fit because we are not exposing an existing in-process FastAPI service. We are wrapping an external partner API.
- Heavier enterprise gateways and hosting layers are premature until there is a confirmed remote multi-user deployment need.
- Prompt-heavy or resource-heavy designs are probably overbuilt for the first version.

## dope.security-Specific Implementation Notes

The current repo contains the Flightdeck partner OpenAPI spec in `docs/partner_api.yaml`.

The API shape suggests these early design decisions:

- Authentication is via OAuth client credentials at `/partner/oauth/token`.
- Most endpoints require bearer auth.
- The surface area is compact and domain-focused:
  - endpoint search
  - policies
  - policy content and restrictions
  - policy assignments
  - policy bypass URLs and applications
  - custom categories and category URLs
- Several list endpoints are cursor-paginated.

### Implications For The MCP Surface

#### Start With Tools

Likely first tools:

- `search_endpoints`
- `list_policies`
- `get_policy`
- `get_policy_content`
- `list_custom_categories`
- `get_custom_category`
- `list_custom_category_urls`

Possible second-wave mutating tools:

- create or update policy-related entities
- assign policy
- add or remove bypass URLs
- create custom category
- add or remove category URLs

#### Be Conservative With Mutations

- Separate read tools from write tools clearly.
- Make descriptions very explicit for mutating operations.
- Expect host-side human confirmation to matter for write operations.

#### Keep Pagination Simple

- Accept `cursor` and `limit` when the underlying API requires it.
- Consider a thin convenience layer like `fetch_all=false` with a strict cap if clients benefit from it.
- Do not hide pagination in a way that risks huge result sets.

#### Keep Credentials Server-Side

- The MCP server should handle partner token acquisition and refresh internally.
- The model should never see `client_secret`.

#### Add Strong Server Instructions

MCP supports server instructions. For this API, that can later include guidance like:

- search before mutate
- prefer read-only tools unless the user asks to change state
- summarize impact before invoking write tools

## Recommended Python/FastMCP Server Architecture

### Core Design Principles

- Use `FastMCP` as the MCP transport and tool-registration layer, not as the place where business logic lives.
- Build the server around the official Python SDK lifespan pattern: initialize shared dependencies once, yield a typed app context, and let tool handlers pull dependencies from `ctx.request_context.lifespan_context`.
- Keep tools thin and agent-facing: they should expose good names, docstrings, and normalized schemas, then delegate almost immediately to service methods.
- Keep the Flightdeck client close to the wire format, but keep the MCP-facing contract normalized and snake_case.
- Avoid introducing a separate repository abstraction. The partner API client already is the data-access boundary for v1.

### Recommended Project Layout

Use a normal `src/` package layout and keep the first cut small.

```text
pyproject.toml
src/dopemcp/
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

- `server.py`: create the `FastMCP` instance, define the lifespan hook, register tool modules, and expose a single `create_server()` factory.
- `__main__.py`: load settings and run the default local `stdio` server.
- `config.py`: environment-backed settings and startup validation.
- `auth.py`: Flightdeck token exchange and refresh logic.
- `flightdeck/client.py`: raw HTTP calls, request construction, response parsing, and upstream error mapping.
- `services/*.py`: workflow-oriented operations used by tools.
- `tools/*.py`: MCP tool definitions grouped by domain.

This is intentionally one layer shallower than a full enterprise clean-architecture template. For this project, transport, services, and API client are enough.

### Layer Boundaries

#### Tool Layer

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

That means a tool should usually look conceptually like:

1. read the typed app context from `ctx`
2. call one service method
3. return a normalized result or raise a concise user-safe error

#### Service Layer

The service layer should own:

- workflow semantics that are better expressed for agents than the raw REST API
- any read-modify-write logic needed to turn replace-style REST endpoints into safer MCP operations
- normalization between Flightdeck wire shapes and MCP-facing models
- domain rules around inheritance, mutation safety, and conflict handling

For example:

- incremental MCP assignment tools may need to call [`get policy assignments`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L727-L804), merge changes, then call [`update policy assignments`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L805-L898)
- explicit replace-style exception tools can map more directly to [`/policies/{policy_name}/content/exceptions`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L642-L726)
- URL and application bypass services can wrap the existing upsert and delete endpoints more directly because the underlying API already has the right mutation family

The service layer is where the MCP becomes agent-friendly instead of acting like a raw API mirror.

#### Flightdeck API Client Layer

The API client layer should own:

- base URL handling
- request serialization and headers
- bearer token acquisition from the auth layer
- raw response parsing
- conversion of upstream HTTP failures into a small internal exception set

It should stay close to the partner API documented in [the OpenAPI spec](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml), including endpoint-specific request shapes like:

- [`/endpoints/search`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L126-L270)
- [`/policies/{policy_name}/content/restrictions`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L560-L641)
- [`/policies/{policy_name}/bypass/urls`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L899-L1193)
- [`/policies/{policy_name}/bypass/applications`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L1194-L1439)
- [`/custom_categories`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L1440-L1880)

### FastMCP Composition Pattern

The official Python SDK examples strongly point toward using lifespan as the composition root.

Recommended shape:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import FastMCP


@dataclass
class AppContext:
    settings: Settings
    token_manager: FlightdeckTokenManager
    flightdeck: FlightdeckClient
    endpoints: EndpointsService
    policies: PoliciesService
    custom_categories: CustomCategoriesService


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
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

Why this is the right place for dependency wiring:

- it follows the official SDK pattern for shared resources
- it gives a single `httpx` connection pool for all tool calls
- it keeps startup validation close to server boot
- it works for local `stdio` now and still fits streamable HTTP later

### Domain Structure For This API

The domain split should follow the partner API's real state boundaries, but it does not need to explode into a class per endpoint.

Recommended first cut:

- `EndpointsService`: search and pagination helpers for endpoint inventory
- `PoliciesService`: policy reads plus mutation methods grouped by restrictions, exceptions, assignments, URL bypass, and application bypass
- `CustomCategoriesService`: category CRUD plus category URL operations

Within `PoliciesService`, keep separate methods for the mutation families that already behave differently in the API:

- restrictions from [`/content/restrictions`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L560-L641)
- exceptions from [`/content/exceptions`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L642-L726)
- assignments from [`/assignments`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L727-L898)
- URL bypass from [`/bypass/urls`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L899-L1193)
- application bypass from [`/bypass/applications`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L1194-L1439)

That gives enough semantic separation without creating a new top-level package for every route.

### Config And Credential Handling

The settings layer should be environment-first and explicit.

Recommended settings fields:

- `DOPE_CLIENT_ID`
- `DOPE_CLIENT_SECRET`
- `DOPE_API_BASE_URL` with default `https://api.flightdeck.dope.security/v1`
- `DOPE_TOKEN_URL` with a default that points to the Flightdeck token endpoint
- `DOPE_TIMEOUT_SECONDS`
- `DOPE_TOKEN_REFRESH_SKEW_SECONDS`

Recommended implementation pattern:

- use `pydantic-settings` `BaseSettings`
- use `SecretStr` for `client_secret`
- set `extra='forbid'` so misspelled config does not silently pass through
- set `env_ignore_empty=True` so empty env vars do not masquerade as valid secrets

Important guidance for this project:

- keep the public contract env-based even if local development optionally supports `.env`
- fail clearly if credentials are missing
- log configuration problems to stderr only
- never expose the credential fields in tool schemas or return values

### Token Management

Use a dedicated `FlightdeckTokenManager` owned by the lifespan context.

Responsibilities:

- exchange `client_id` and `client_secret` against [`/partner/oauth/token`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L40-L125)
- cache `access_token`, `token_type`, and computed expiration time in memory
- refresh a little before expiry using a configurable skew
- protect refresh with an `asyncio.Lock` so concurrent tool calls do not stampede the token endpoint
- invalidate and retry once on an upstream `401` when there is evidence the bearer token expired

Recommended v1 behavior:

- process-local in-memory token cache is sufficient for local `stdio`
- the same design is still acceptable for early remote HTTP deployments, with each worker maintaining its own cache
- do not externalize token storage unless multi-process coordination or token issuance rate becomes a real problem

This is a place where a small dedicated abstraction is worth it. Token refresh and invalidation are real shared concerns, not speculative abstraction.

### Schema Normalization

The MCP layer should define its own response and input models instead of leaking Flightdeck's wire format directly.

Recommended rule:

- the API client may parse camelCase payloads from Flightdeck
- service results and MCP tool outputs should use snake_case
- conversion between the two should happen below the tool layer

Examples:

- upstream `inheritsFromBase` becomes MCP `inherits_from_base`
- upstream `hasNextPage` becomes MCP `has_next_page`
- pagination wrappers can be simplified if the MCP contract benefits from flatter naming

This keeps the tool surface internally consistent and avoids mixed casing across the server.

### Error Shaping

The error model should have two levels: upstream normalization and tool-facing presentation.

Recommended internal exception set at the API client boundary:

- `FlightdeckAuthenticationError`
- `FlightdeckAuthorizationError`
- `FlightdeckNotFoundError`
- `FlightdeckValidationError`
- `FlightdeckConflictError`
- `FlightdeckServerError`
- `FlightdeckTransportError`

On top of that, the service layer can raise more specific domain errors when the distinction matters to tool UX, such as:

- `PolicyNotFoundError`
- `AssignmentConflictError`
- `InheritedPolicyMutationError`
- `InvalidPrincipalError`

Presentation guidance for tools:

- expected user-actionable failures should become concise tool errors
- tool errors should mention the affected object and the actionable reason
- raw upstream payloads should only be surfaced when they add user value and do not risk leaking secrets
- reserve MCP protocol errors for actual MCP protocol problems, not normal business failures

This is especially important for endpoints whose errors carry meaningful semantics, such as:

- conflict details in [`update policy assignments`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L805-L898)
- validation failures for category exceptions in [`update policy content exceptions`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L642-L726)
- inheritance-related write failures in [`delete custom URL bypass entries`](file:///Users/ldc/repos/dopemcp/docs/partner_api.yaml#L1108-L1193)

### Transport And Entrypoint Design

Keep one server factory and two transport modes.

Recommended pattern:

- `__main__.py` runs local `stdio` by default
- `server.py` exposes `create_server()` so tests and alternate entrypoints can build the same server
- a later remote entrypoint can call `mcp.run(transport="streamable-http")`
- if the server is later mounted into Starlette or FastAPI, keep that in a separate ASGI entrypoint rather than mixing HTTP framework code into the default local CLI

For the eventual remote path, the current official guidance still favors:

- `streamable-http`
- `stateless_http=True`
- `json_response=True`

That means the architecture should keep transport concerns at the edge so the service and API-client layers remain unchanged when the server grows from local stdio into remote HTTP.

### Logging And Observability

Recommended baseline:

- log to stderr only
- include tool name and request correlation identifiers where available
- never log secrets, bearer tokens, or token exchange payloads
- keep HTTP logging off or heavily redacted around auth calls

For v1, basic structured logs and good error messages are enough. Full tracing or audit infrastructure can wait for the remote deployment phase.

### Concrete Recommendation

For this project, the cleanest architecture is:

1. `FastMCP` server with typed lifespan context as the composition root.
2. One shared `httpx.AsyncClient` plus one dedicated token manager per process.
3. A small service layer grouped by `endpoints`, `policies`, and `custom_categories`.
4. Thin MCP tool modules that expose normalized snake_case contracts.
5. A Flightdeck client layer that owns raw HTTP and upstream error normalization.
6. No extra repository or plugin layers unless a second backend or major hosting requirement appears.

## Recommended Starting Point

If we want the fastest path to a correct and maintainable v1:

1. Use Python.
2. Use the official Python SDK with `FastMCP`.
3. Model the first release almost entirely as tools.
4. Start with local `stdio` for development and client compatibility.
5. Design the code so it can also run with `streamable-http` later.
6. Keep auth split into two concerns:
   - partner API client credentials managed internally by the server
   - separate MCP transport auth only if and when we expose the server remotely

Why this recommendation stands out:

- It aligns with official docs.
- It minimizes boilerplate.
- It keeps the first milestone focused on the dope.security domain instead of protocol plumbing.
- It leaves a clean path to remote deployment later.

## Open Questions To Resolve In Planning

- Is the first target host local only, or do we expect a remotely hosted MCP service?
- Should v1 include any mutating tools, or start read-only?
- Is Python acceptable for the project, or is TypeScript preferred for team or deployment reasons?
- Do we want one MCP server for all Flightdeck partner operations, or a narrower first server focused on endpoint and policy read workflows?
- How much normalization should the MCP layer do on top of the REST API versus staying close to the underlying endpoints?
- Should assignment tools ship as safer incremental `assign` and `unassign` MCP operations backed by read-modify-write logic, or should v1 expose a more direct replace-style assignment tool first?
- Do we want the first mutating tools to support a lightweight dry-run or impact-summary mode, or should confirmation stay entirely in the host UI?
- How much of the upstream pagination model should remain visible in tool outputs versus being lightly simplified for MCP consumers?

## Sources

- MCP architecture overview: https://modelcontextprotocol.io/docs/learn/architecture
- Build an MCP server: https://modelcontextprotocol.io/docs/develop/build-server
- MCP tools concept: https://modelcontextprotocol.io/docs/concepts/tools
- MCP SDK overview: https://modelcontextprotocol.io/docs/sdk
- MCP authorization spec: https://modelcontextprotocol.io/specification/draft/basic/authorization
- MCP security best practices: https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
- MCP authorization tutorial: https://modelcontextprotocol.io/docs/tutorials/security/authorization
- MCP Inspector docs: https://modelcontextprotocol.io/docs/tools/inspector
- Official TypeScript SDK: https://github.com/modelcontextprotocol/typescript-sdk
- Official Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Official Python SDK README and examples: https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md
- FastMCP Python docs: https://gofastmcp.com/getting-started/welcome
- FastMCP TypeScript repo: https://github.com/punkpeye/fastmcp
- Pydantic settings docs: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
