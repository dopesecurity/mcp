# Future work

Ideas considered but not scheduled. Each section is self-contained;
add new ones at the bottom.

## Agent Skills for complex dope.security workflows

Captured 2026-05-29.

### Why this is here

We want agents that drive this MCP to follow the dope.security customer
support team's recipes for multi-step workflows (e.g. "fix broken app
traffic", "allow a domain while blocking one URL pattern on it"). The
cross-cutting rules already live in
[`instructions.py`](../../src/dopesecurity/mcp_server/instructions.py)
and per-tool descriptions, but those don't carry full procedural
recipes. We considered four options for the procedural layer and
discarded three:

| Option | Verdict | Reason |
|---|---|---|
| MCP **prompts** | ❌ rejected | Project decision: not doing prompts. |
| **Compound / orchestrating tools** (one tool that does upsert app bypass + upsert url bypass internally) | ❌ deferred | Largest change; partial-failure semantics across Flightdeck endpoints need a separate design pass. |
| **`get-guidance` read tool** returning markdown | ❌ deferred | Works everywhere, but adds a tool to the surface and doesn't progressively disclose. |
| **Agent Skills** | ✅ recommended when revisited | Filesystem-based, near-universal agent support, progressive disclosure, 0 tool-surface impact. |

### What Agent Skills are

Filesystem-based knowledge units the client preloads at startup. Each
skill is a directory with a `SKILL.md` plus optional bundled files.

- **Level 1 (always loaded, ~100 tokens/skill):** YAML frontmatter
  (`name`, `description`). The `description` is the trigger string the
  agent matches against the user's intent.
- **Level 2 (loaded on activation, target <5k tokens):** `SKILL.md`
  body — the recipe.
- **Level 3 (loaded on demand, effectively unlimited):** additional
  bundled files referenced by `SKILL.md`.

References:
- <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview>
- <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices>
- <https://modelcontextprotocol.io/docs/develop/build-with-agent-skills>
- <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>

Client support is broad (Claude.ai, Claude Code, Claude Agent SDK,
Claude Developer Platform, VS Code agent mode, Amp, Codex CLI, and
others listed on the agent-skills overview).

### Concrete plan when we revisit

#### Layout

Ship in this repo under `skills/`:

```
skills/
├── dope-fix-broken-application/
│   └── SKILL.md
└── dope-allow-domain-block-action/
    └── SKILL.md
```

#### Skill #1: `dope-fix-broken-application`

Trigger when a user reports that an application's traffic is broken on
dope.security and we need to update bypass on a policy.

Recipe:

1. Confirm the policy name and the misbehaving application with the
   user.
2. Identify the macOS and Windows process names for the application
   (web-search if not already known) and the application's primary
   domains.
3. Confirm the lists with the user.
4. Call `upsert_policy_application_bypass` with **both**
   `mac` and `windows` non-empty (independent platforms — omitting one
   leaves traffic blocked there).
5. Call `upsert_policy_url_bypass` with the associated
   domains.
6. Confirm completion and remind the user that URL/application bypass
   is for broken-traffic restoration, not routine allow-listing.

#### Skill #2: `dope-allow-domain-block-action`

Trigger when a user wants to allow a domain while blocking one
specific URL pattern on that same domain (the Facebook / Messenger
example from best practices dump below).

Recipe:

1. Get the policy name, allow-target (domain), and block-target (URL
   pattern) from the user.
2. Create two custom categories with
   `create_custom_category` (one allow, one block).
3. Populate each via `add_urls_to_custom_category`.
   Wildcard rules per
   [`example/customcats.md`](../../example/customcats.md): leftmost
   wildcard in the domain, wildcards anywhere in path/query/fragment.
4. Attach restrictions on the target policy via
   `update_policy_restrictions` so the allow custom
   category is `ALLOW` and the block custom category is `BLOCK`.
5. Remind the user of dope.security's policy precedence (Bypass → CAC
   → Custom Categories → Dope Categories — see best practices dump below) so they understand why
   this works.

### Open decisions before implementing

1. **Delivery mechanism.** Three reasonable options:
   - (a) Repo-only: ship `skills/` in the repo; README documents how
     to symlink/copy into the user's agent skills location.
   - (b) CLI installer:
     `dopesecurity-mcp-server install-skills --target <path>` copies
     them.
   - (c) Both.

   (a) is the smallest change. (b) is easy to add later if customers
   ask.

2. **Testing strategy.** No existing pytest pattern for skill content.
   At minimum, a small test that parses each `SKILL.md` and validates
   the frontmatter (`name`, `description` present; name format
   constraints per spec; description ≤1024 chars).


# dump of best practices doc
**Policy Order**

The following is the order on how the policy is checked:

1. Bypass  
2. CAC  
3. Custom Categories  
4. Dope Categories

**Dope Categories**

Exceptions should always be used when allowing, blocking or setting a warning on a category for a user or a group  
Updating an entire category to allow, block or warning should only be done if the update needs to effect everyone assigned to the category

**Application and URL Bypass**

The application and URL bypass should only be used in the case where traffic from an application or a domain is broken  
The URL bypass list only accepts domains, it will not accept URLs.   
In bypass, wildcard is supported only in place of subdomain, and not supported in TLD. (\*.xyz.com is supported, but www.xyz.\* is not supported)  
When asked to fix an application that is reporting broken traffic you need to search the web for any windows and macOS processes associated with the application. Both the window and macOS processes then need to be added to application bypass. You should also search for any domains associated with the application and add these to the bypass list.

**Custom Categories**

Custom categories should always be used when a domain or domains needs to be given precedence over a dope category. For example if social media is blocked and you want to give access to LinkedIn you should create a custom category.  
Custom categories accept both domains and [URLs.](http://URLs.In) In the case of adding a domain, it’s recommended to include a wild card (\*).  
In custom categories, wildcard is supported in subdomain as well as in URL path. (\*.xyz.com, \*.xyz.com/path\* is supported)  
When the request is to only allow specific actions for a specific domain then an allow and block custom category will need to be created. For example, if social media is blocked but the admin wants to allow access to facebook but not allow posting to messenger, an allow custom category is created with the domain required to access facebook and a block category is created with the specific URL needed to block messenger access e.g. \*.[edge-chat.facebook.com](http://edge-chat.facebook.com) . 

**CAC Policy**

CAC is used where the customer wants to lock down a SaaS app to a set of domains or workspace IDs depending on the SaaS app
