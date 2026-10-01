"""Policy MCP tool registration."""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from pydantic import ValidationError

from dopesecurity.mcp_server.errors import InvalidToolInputError
from dopesecurity.mcp_server.schemas import (
    CustomApplicationPlatformUpdate,
    CustomUrlBypassUpdate,
    DefaultApplicationPlatformUpdate,
    DefaultUrlBypassUpdate,
    ExceptionCategoryUpdate,
    ListPoliciesResult,
    PolicyApplicationBypassResult,
    PolicyAssignmentsResult,
    PolicyExceptionsResult,
    PolicyRestrictionsResult,
    PolicyUrlBypassResult,
    ReplacePolicyCategoryExceptionsInput,
    RestrictionUpdate,
    SuccessResult,
    UpdatePolicyRestrictionsInput,
    UpsertPolicyApplicationBypassInput,
    UpsertPolicyUrlBypassInput,
)
from dopesecurity.mcp_server.tools import get_app_context


def register_policy_tools(
    mcp: MCPServer,
    *,
    enable_mutations: bool = False,
    enable_destructive: bool = False,
) -> None:
    """Register policy read tools (always), write tools (when mutations
    are enabled), and destructive tools (when both flags are enabled)."""

    _register_read_tools(mcp)
    if enable_mutations:
        _register_write_tools(mcp)
        if enable_destructive:
            _register_destructive_tools(mcp)


def _register_read_tools(mcp: MCPServer) -> None:
    @mcp.tool(
        name="list_policies",
        description=(
            "List Flightdeck policies. Cursor-paginated; ordered by policy name. "
            "Returns only summary metadata; use get_policy_assignments, "
            "get_policy_restrictions, get_policy_exceptions, get_policy_url_bypass, "
            "and get_policy_application_bypass_entries to read each layer of a "
            "specific policy."
        ),
    )
    async def list_policies(
        ctx: Context,
        first: int | None = None,
        after: str | None = None,
        order: Literal["asc", "desc"] = "asc",
    ) -> ListPoliciesResult:
        return await get_app_context(ctx).policies.list_policies(
            first=first, after=after, order=order
        )

    @mcp.tool(
        name="get_policy_assignments",
        description=(
            "Get the users and groups currently assigned to a policy. Returns only "
            "principal identities; for what those principals are actually allowed to "
            "do also read get_policy_restrictions, get_policy_exceptions, "
            "get_policy_url_bypass, and get_policy_application_bypass_entries."
        ),
    )
    async def get_policy_assignments(
        ctx: Context, policy_name: str
    ) -> PolicyAssignmentsResult:
        return await get_app_context(ctx).policies.get_assignments(policy_name)

    @mcp.tool(
        name="get_policy_restrictions",
        description=(
            "Derived read view of a policy's category and custom-category restrictions "
            "(the default BLOCK/ALLOW per category for this policy). This is only one "
            "of several layers that decide whether a URL is reachable. Does not "
            "include per-principal overrides "
            "(get_policy_exceptions), URL allowlists (get_policy_url_bypass), "
            "application allowlists (get_policy_application_bypass_entries), or "
            "custom-category contents (list_custom_categories, "
            "get_custom_category_urls). `inherits_from_base: true` on a section means "
            "the policy has no override and the effective restrictions come from the "
            "base policy."
        ),
    )
    async def get_policy_restrictions(
        ctx: Context, policy_name: str
    ) -> PolicyRestrictionsResult:
        return await get_app_context(ctx).policies.get_restrictions(policy_name)

    @mcp.tool(
        name="get_policy_exceptions",
        description=(
            "Derived read view of per-principal (user/group) exceptions that override "
            "the policy's default restriction for specific categories or custom "
            "categories. Returns only the exception layer; the default restrictions "
            "those exceptions override are in get_policy_restrictions. URL and "
            "application allowlists are separate again (get_policy_url_bypass, "
            "get_policy_application_bypass_entries)."
        ),
    )
    async def get_policy_exceptions(
        ctx: Context, policy_name: str
    ) -> PolicyExceptionsResult:
        return await get_app_context(ctx).policies.get_exceptions(policy_name)

    @mcp.tool(
        name="get_policy_url_bypass",
        description=(
            "Get a policy's URL bypass entries (URLs/hostnames that are allowed "
            "regardless of category restriction). `custom` entries are admin-defined; "
            "`default` entries are dope-provided with per-entry applied/ignored state. "
            "URL bypass is only one layer of access control; category and "
            "custom-category restrictions (get_policy_restrictions), per-principal "
            "exceptions (get_policy_exceptions), and the endpoint's own enforcement "
            "state (search_endpoints) can all independently affect what a user can "
            "reach."
        ),
    )
    async def get_policy_url_bypass(
        ctx: Context, policy_name: str
    ) -> PolicyUrlBypassResult:
        return await get_app_context(ctx).policies.get_url_bypass(policy_name)

    @mcp.tool(
        name="get_policy_application_bypass_entries",
        description=(
            "Get a policy's application bypass entries (applications exempt from "
            "inspection), split by platform (mac/windows). `custom` entries are "
            "admin-defined; `default` entries are dope-provided. Application bypass "
            "is independent of URL/category controls; see get_policy_restrictions, "
            "get_policy_exceptions, and get_policy_url_bypass for the other layers."
        ),
    )
    async def get_policy_application_bypass_entries(
        ctx: Context, policy_name: str
    ) -> PolicyApplicationBypassResult:
        return await get_app_context(ctx).policies.get_application_bypass(policy_name)


def _register_write_tools(mcp: MCPServer) -> None:
    @mcp.tool(
        name="create_policy",
        description=(
            "Create a new empty policy by name. The new policy inherits from base "
            "until restrictions/bypasses are configured on it. Modifies tenant state."
        ),
    )
    async def create_policy(
        ctx: Context, policy_name: str
    ) -> SuccessResult:
        return await get_app_context(ctx).policies.create_policy(policy_name)

    @mcp.tool(
        name="assign_policy_principals",
        description=(
            "Assign users and/or groups to a policy. Each entry must be the email "
            "address of a user or group that ALREADY exists in the Flightdeck "
            "tenant; this server does not currently expose a tool to enumerate "
            "users or groups, so callers must obtain valid emails out-of-band "
            "(e.g. existing assignments on another policy via "
            "get_policy_assignments). Reads current assignments and "
            "merges/de-duplicates the provided principals before writing back. "
            "Best-effort and non-atomic. Modifies tenant state."
        ),
    )
    async def assign_policy_principals(
        ctx: Context,
        policy_name: str,
        user_emails: list[str] | None = None,
        group_emails: list[str] | None = None,
    ) -> PolicyAssignmentsResult:
        return await get_app_context(ctx).policies.assign_principals(
            policy_name,
            user_emails=user_emails,
            group_emails=group_emails,
        )

    @mcp.tool(
        name="unassign_policy_principals",
        description=(
            "Remove users and/or groups from a policy's assignments. Each entry "
            "must be the email of a real user/group; principals not currently "
            "assigned are ignored. Best-effort and non-atomic. Modifies tenant "
            "state."
        ),
    )
    async def unassign_policy_principals(
        ctx: Context,
        policy_name: str,
        user_emails: list[str] | None = None,
        group_emails: list[str] | None = None,
    ) -> PolicyAssignmentsResult:
        return await get_app_context(ctx).policies.unassign_principals(
            policy_name,
            user_emails=user_emails,
            group_emails=group_emails,
        )

    @mcp.tool(
        name="update_policy_restrictions",
        description=(
            "Update restrictions on the submitted categories and custom categories "
            "only. Categories not included remain unchanged — this is the right tool "
            "for changing one or a few categories. At least one of `categories` or "
            "`custom_categories` must be provided. To change all category overrides "
            "back to inheriting from base instead, use reset_policy_restrictions_to_base. "
            "Modifies tenant state."
        ),
    )
    async def update_policy_restrictions(
        ctx: Context,
        policy_name: str,
        categories: list[RestrictionUpdate] | None = None,
        custom_categories: list[RestrictionUpdate] | None = None,
    ) -> SuccessResult:
        try:
            input = UpdatePolicyRestrictionsInput(
                policy_name=policy_name,
                categories=categories,
                custom_categories=custom_categories,
            )
        except ValidationError as exc:
            raise InvalidToolInputError(str(exc)) from exc
        return await get_app_context(ctx).policies.update_restrictions(input)

    @mcp.tool(
        name="replace_policy_category_exceptions",
        description=(
            "Replace per-principal exceptions for the SUBMITTED categories only. This is "
            "per-category replacement, NOT whole-policy replacement: categories not "
            "included remain unchanged. An empty exceptions list clears all exceptions "
            "for that category. Each `principal` must be the email of a user or "
            "group that ALREADY exists in the Flightdeck tenant — Flightdeck "
            "rejects the whole request with a Bad Request if any principal is "
            "unknown, and this server does not currently expose a tool to "
            "enumerate users or groups (callers must obtain valid emails "
            "out-of-band, e.g. via get_policy_exceptions on another policy). "
            "Modifies tenant state."
        ),
    )
    async def replace_policy_category_exceptions(
        ctx: Context,
        policy_name: str,
        categories: list[ExceptionCategoryUpdate] | None = None,
        custom_categories: list[ExceptionCategoryUpdate] | None = None,
    ) -> SuccessResult:
        try:
            input = ReplacePolicyCategoryExceptionsInput(
                policy_name=policy_name,
                categories=categories,
                custom_categories=custom_categories,
            )
        except ValidationError as exc:
            raise InvalidToolInputError(str(exc)) from exc
        return await get_app_context(ctx).policies.replace_category_exceptions(input)

    @mcp.tool(
        name="upsert_policy_url_bypass",
        description=(
            "Upsert URL bypass for a policy. `custom` entries are admin-defined and "
            "matched by name (existing entries are overwritten, unknown names added, "
            "unmentioned entries preserved). Each custom `name` must be a "
            "hostname or wildcard hostname only (e.g. example.com or "
            "*.example.com) — Flightdeck rejects values that include a "
            "scheme (http://, https://) or a path. Wildcards are only allowed in "
            "the leading subdomain position; patterns like www.example.* (wildcard "
            "in the TLD) are rejected. Use the optional `note` field for human "
            "context such as a full URL. `default` entries adjust the "
            "applied/ignored state of dope-provided entries. URL bypass is for "
            "unblocking traffic that is actually broken for an application or "
            "domain; to give a domain precedence over a Dope category (routine "
            "allow-listing, e.g. allow LinkedIn while social media is blocked), "
            "create a custom category instead. Modifies tenant state."
        ),
    )
    async def upsert_policy_url_bypass(
        ctx: Context,
        policy_name: str,
        custom: list[CustomUrlBypassUpdate] | None = None,
        default: list[DefaultUrlBypassUpdate] | None = None,
    ) -> SuccessResult:
        try:
            input = UpsertPolicyUrlBypassInput(
                policy_name=policy_name, custom=custom, default=default
            )
        except ValidationError as exc:
            raise InvalidToolInputError(str(exc)) from exc
        return await get_app_context(ctx).policies.upsert_url_bypass(input)

    @mcp.tool(
        name="delete_policy_url_bypass_entries",
        description=(
            "Delete custom URL bypass entries from a policy by name. Names are "
            "hostnames (no scheme, no path), matching the `name` field returned "
            "by get_policy_url_bypass under `custom`. Idempotent: unknown names "
            "are ignored. Inheriting policies cannot have entries deleted. "
            "Modifies tenant state."
        ),
    )
    async def delete_policy_url_bypass_entries(
        ctx: Context,
        policy_name: str,
        names: list[str],
    ) -> SuccessResult:
        return await get_app_context(ctx).policies.delete_url_bypass_entries(
            policy_name, names
        )

    @mcp.tool(
        name="upsert_policy_application_bypass",
        description=(
            "Upsert application bypass for a policy, split per platform (mac/windows). "
            "`custom` entries are admin-defined; `default` entries adjust dope-provided "
            "entries. An application is identified by its process name per platform, "
            "and the two platforms are independent — when bypassing a cross-platform "
            "app, add both the macOS and Windows process names (and typically the "
            "app's associated domains via upsert_policy_url_bypass as well), "
            "otherwise traffic stays blocked on the platform you omitted. "
            "Application bypass is for unblocking apps with actually broken "
            "traffic, not for routine allow-listing. Modifies tenant state. "
            "IMPORTANT: this is merge-only — submitted custom entries are added "
            "or updated, but custom entries NOT included in the call are "
            "preserved, not removed. Re-upserting a shorter list does NOT shrink "
            "the existing entries. To remove specific custom entries, use "
            "delete_policy_application_bypass_entries."
        ),
    )
    async def upsert_policy_application_bypass(
        ctx: Context,
        policy_name: str,
        custom: CustomApplicationPlatformUpdate | None = None,
        default: DefaultApplicationPlatformUpdate | None = None,
    ) -> SuccessResult:
        try:
            input = UpsertPolicyApplicationBypassInput(
                policy_name=policy_name, custom=custom, default=default
            )
        except ValidationError as exc:
            raise InvalidToolInputError(str(exc)) from exc
        return await get_app_context(ctx).policies.upsert_application_bypass(input)

    @mcp.tool(
        name="delete_policy_application_bypass_entries",
        description=(
            "Delete custom application bypass entries from a policy by name, "
            "per platform. Names match the `name` field returned by "
            "get_policy_application_bypass_entries under `custom.mac` / "
            "`custom.windows`. At least one of `mac` or `windows` must be a "
            "non-empty list. Idempotent: unknown names are ignored. Policies "
            "that inherit application bypass from the Base Policy cannot have "
            "entries deleted. Modifies tenant state."
        ),
    )
    async def delete_policy_application_bypass_entries(
        ctx: Context,
        policy_name: str,
        mac: list[str] | None = None,
        windows: list[str] | None = None,
    ) -> SuccessResult:
        return await get_app_context(ctx).policies.delete_application_bypass_entries(
            policy_name, mac=mac, windows=windows
        )


def _register_destructive_tools(mcp: MCPServer) -> None:
    @mcp.tool(
        name="delete_policy",
        description=(
            "DESTRUCTIVE. Delete a policy by name. Drops the policy and all of its "
            "restriction overrides, exceptions, and bypass entries. Never use as a "
            "diagnostic step. Before calling, confirm the exact target with the user "
            "and wait for an explicit yes. Modifies tenant state."
        ),
    )
    async def delete_policy(
        ctx: Context, policy_name: str
    ) -> SuccessResult:
        return await get_app_context(ctx).policies.delete_policy(policy_name)

    @mcp.tool(
        name="reset_policy_restrictions_to_base",
        description=(
            "DESTRUCTIVE / WHOLESALE. Discards every category restriction override "
            "on this policy at the chosen scope ('categories', 'custom_categories', "
            "or 'both') so the section inherits from base again. Use only when the "
            "user has explicitly asked to start over. Never use to investigate or "
            "change a single category — use update_policy_restrictions for that. "
            "Before calling, confirm the exact target with the user and wait for an "
            "explicit yes. Modifies tenant state."
        ),
    )
    async def reset_policy_restrictions_to_base(
        ctx: Context,
        policy_name: str,
        scope: Literal["categories", "custom_categories", "both"],
    ) -> SuccessResult:
        return await get_app_context(ctx).policies.reset_restrictions_to_base(
            policy_name, scope
        )

    @mcp.tool(
        name="reset_policy_url_bypass_to_base",
        description=(
            "DESTRUCTIVE / WHOLESALE. Drops all custom entries and default overrides "
            "on this policy's URL bypass and inherits from base again. Use only when "
            "the user has explicitly asked to start over. To remove specific entries, "
            "use delete_policy_url_bypass_entries; to change one, use "
            "upsert_policy_url_bypass. Before calling, confirm the exact target with "
            "the user and wait for an explicit yes. Modifies tenant state."
        ),
    )
    async def reset_policy_url_bypass_to_base(
        ctx: Context, policy_name: str
    ) -> SuccessResult:
        return await get_app_context(ctx).policies.reset_url_bypass_to_base(policy_name)

    @mcp.tool(
        name="reset_policy_application_bypass_to_base",
        description=(
            "DESTRUCTIVE / WHOLESALE. Drops all custom and default-override "
            "application bypass entries on this policy and inherits from base again. "
            "Use only when the user has explicitly asked to start over. To remove "
            "specific entries, use delete_policy_application_bypass_entries; to "
            "change one, use upsert_policy_application_bypass. Before calling, "
            "confirm the exact target with the user and wait for an explicit yes. "
            "Modifies tenant state."
        ),
    )
    async def reset_policy_application_bypass_to_base(
        ctx: Context, policy_name: str
    ) -> SuccessResult:
        return await get_app_context(ctx).policies.reset_application_bypass_to_base(
            policy_name
        )
