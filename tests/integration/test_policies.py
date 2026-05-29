"""Integration scenarios for policy tools (read + write)."""

from __future__ import annotations

import pytest

from .harness import (
    Cleaner,
    IntegrationConfig,
    McpHarness,
    ToolError,
    integration,
    make_tag,
)


async def _create_policy(mcp: McpHarness, cleaner: Cleaner, scenario: str) -> str:
    name = make_tag(scenario)
    await mcp.call("create_policy", {"policy_name": name})
    cleaner.track_policy(name)
    return name


async def test_list_policies_returns_structured_page(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, _cleaner):
        page = await mcp.call("list_policies", {"first": 5})
        assert isinstance(page.get("policies"), list)
        assert "page_info" in page


async def test_policy_lifecycle_create_list_delete(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, cleaner):
        name = await _create_policy(mcp, cleaner, "lifecycle")

        names = await mcp.list_all_policy_names()
        assert name in names

        await mcp.call("delete_policy", {"policy_name": name})
        cleaner.policies.remove(name)

        names = await mcp.list_all_policy_names()
        assert name not in names


async def test_policy_read_tools_on_fresh_policy(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, cleaner):
        name = await _create_policy(mcp, cleaner, "reads")

        assignments = await mcp.call("get_policy_assignments", {"policy_name": name})
        assert "users" in assignments
        assert "groups" in assignments

        restrictions = await mcp.call("get_policy_restrictions", {"policy_name": name})
        assert "categories" in restrictions
        assert "custom_categories" in restrictions

        exceptions = await mcp.call("get_policy_exceptions", {"policy_name": name})
        assert "categories" in exceptions
        assert "custom_categories" in exceptions

        url_bypass = await mcp.call("get_policy_url_bypass", {"policy_name": name})
        assert "custom" in url_bypass
        assert "default" in url_bypass

        app_bypass = await mcp.call(
            "get_policy_application_bypass_entries", {"policy_name": name}
        )
        assert "custom" in app_bypass
        assert "default" in app_bypass


async def test_policy_assignments_roundtrip(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, cleaner):
        name = await _create_policy(mcp, cleaner, "assign")
        user = integration_config.test_user_email

        after_assign = await mcp.call(
            "assign_policy_principals",
            {"policy_name": name, "user_emails": [user]},
        )
        assert any(u["email"] == user for u in after_assign["users"])

        after_unassign = await mcp.call(
            "unassign_policy_principals",
            {"policy_name": name, "user_emails": [user]},
        )
        assert all(u["email"] != user for u in after_unassign["users"])


async def test_policy_restrictions_update_and_reset(
    integration_config: IntegrationConfig,
) -> None:
    """Set and read back every restriction state at least once.

    Flightdeck enforces per-category restriction validity: standard
    categories accept ALLOW/BLOCK/WARNING but reject IGNORE, while
    custom categories also accept IGNORE. This test creates a custom
    category up-front so every state has somewhere it can land, then
    scans both the inherited standard categories and the inherited
    custom categories until each of ALLOW, BLOCK, WARNING, and IGNORE
    has been successfully applied to at least one category and read
    back. After each state is verified, restrictions are reset to base.
    """
    states: list[str] = ["ALLOW", "BLOCK", "WARNING", "IGNORE"]

    async with integration(integration_config) as (mcp, cleaner):
        # IGNORE only applies to custom categories, so make sure at least
        # one exists on the tenant for this scenario.
        custom_cat = make_tag("restr-cc")
        await mcp.call(
            "create_custom_category", {"custom_category_name": custom_cat}
        )
        cleaner.track_custom_category(custom_cat)

        name = await _create_policy(mcp, cleaner, "restr")
        base = await mcp.call("get_policy_restrictions", {"policy_name": name})
        # (kind, name) pairs across both standard and custom categories
        candidates: list[tuple[str, str]] = [
            ("categories", c["name"]) for c in base["categories"]["items"]
        ] + [
            ("custom_categories", c["name"])
            for c in base["custom_categories"]["items"]
        ]
        if not candidates:
            pytest.skip("tenant policy has no inherited categories to toggle")

        verified: dict[str, tuple[str, str]] = {}

        for state in states:
            last_error: ToolError | None = None
            for kind, cat_name in candidates:
                try:
                    await mcp.call(
                        "update_policy_restrictions",
                        {
                            "policy_name": name,
                            kind: [{"name": cat_name, "restriction": state}],
                        },
                    )
                except ToolError as exc:
                    last_error = exc
                    # Flightdeck returns 400 with detail
                    # "Invalid restriction '<state>' for category '<name>'",
                    # which is now folded into the surfaced error message.
                    assert "Invalid restriction" in exc.message
                    continue
                after = await mcp.call(
                    "get_policy_restrictions", {"policy_name": name}
                )
                after_item = next(
                    i for i in after[kind]["items"] if i["name"] == cat_name
                )
                assert after_item["restriction"] == state, (
                    f"set restriction={state} on {kind}/{cat_name!r} but read "
                    f"back {after_item['restriction']}"
                )
                verified[state] = (kind, cat_name)
                # Reset so the next state has a clean slate to assert on.
                await mcp.call(
                    "reset_policy_restrictions_to_base",
                    {"policy_name": name, "scope": "both"},
                )
                break
            else:
                raise AssertionError(
                    f"no standard or custom category on this policy accepted "
                    f"restriction={state!r}; last error: {last_error}"
                )

        assert set(verified.keys()) == set(states), (
            f"unverified states: {set(states) - set(verified.keys())}"
        )


async def test_policy_category_exceptions_replace_and_clear(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, cleaner):
        name = await _create_policy(mcp, cleaner, "exc")
        restrictions = await mcp.call("get_policy_restrictions", {"policy_name": name})
        items = restrictions["categories"]["items"]
        if not items:
            pytest.skip("tenant policy has no categories to set exceptions on")
        cat_name = items[0]["name"]
        user = integration_config.test_user_email

        await mcp.call(
            "replace_policy_category_exceptions",
            {
                "policy_name": name,
                "categories": [
                    {
                        "name": cat_name,
                        "exceptions": [{"principal": user, "restriction": "ALLOW"}],
                    }
                ],
            },
        )
        after = await mcp.call("get_policy_exceptions", {"policy_name": name})
        cat_block = next(
            c for c in after["categories"]["items"] if c["name"] == cat_name
        )
        assert any(e["principal"] == user for e in cat_block["exceptions"])

        await mcp.call(
            "replace_policy_category_exceptions",
            {
                "policy_name": name,
                "categories": [{"name": cat_name, "exceptions": []}],
            },
        )
        cleared = await mcp.call("get_policy_exceptions", {"policy_name": name})
        cat_block = next(
            (c for c in cleared["categories"]["items"] if c["name"] == cat_name), None
        )
        assert cat_block is None or cat_block["exceptions"] == []


async def test_policy_url_bypass_upsert_delete_reset(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, cleaner):
        name = await _create_policy(mcp, cleaner, "url")
        # Bypass `name` must be a valid domain/IP/URL pattern, so embed the
        # tag inside a fake subdomain rather than using it raw.
        # Flightdeck lowercases bypass names, so use lowercase up front.
        a = f"{make_tag('urla')}.example.com"
        b = f"{make_tag('urlb')}.example.com"

        await mcp.call(
            "upsert_policy_url_bypass",
            {
                "policy_name": name,
                "custom": [
                    {"name": a, "note": "test A"},
                    {"name": b, "note": "test B"},
                ],
            },
        )
        after = await mcp.call("get_policy_url_bypass", {"policy_name": name})
        custom_names = {e["name"] for e in after["custom"]}
        assert {a, b}.issubset(custom_names)

        await mcp.call(
            "delete_policy_url_bypass_entries",
            {"policy_name": name, "names": [a]},
        )
        shrunk = await mcp.call("get_policy_url_bypass", {"policy_name": name})
        shrunk_names = {e["name"] for e in shrunk["custom"]}
        assert a not in shrunk_names
        assert b in shrunk_names

        await mcp.call("reset_policy_url_bypass_to_base", {"policy_name": name})
        reset = await mcp.call("get_policy_url_bypass", {"policy_name": name})
        reset_names = {e["name"] for e in reset["custom"]}
        assert b not in reset_names


async def test_policy_application_bypass_upsert_and_reset(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, cleaner):
        name = await _create_policy(mcp, cleaner, "app")
        app_name = make_tag("app")

        await mcp.call(
            "upsert_policy_application_bypass",
            {
                "policy_name": name,
                "custom": {"mac": [{"name": app_name, "note": "test"}]},
            },
        )
        after = await mcp.call(
            "get_policy_application_bypass_entries", {"policy_name": name}
        )
        mac_names = {e["name"] for e in after["custom"]["mac"]}
        assert app_name in mac_names

        await mcp.call(
            "reset_policy_application_bypass_to_base", {"policy_name": name}
        )
        reset = await mcp.call(
            "get_policy_application_bypass_entries", {"policy_name": name}
        )
        reset_mac_names = {e["name"] for e in reset["custom"]["mac"]}
        assert app_name not in reset_mac_names


async def test_policy_application_bypass_delete_entries(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, cleaner):
        name = await _create_policy(mcp, cleaner, "appdel")
        a = make_tag("a-app")
        b = make_tag("b-app")
        w = make_tag("w-app")

        await mcp.call(
            "upsert_policy_application_bypass",
            {
                "policy_name": name,
                "custom": {
                    "mac": [
                        {"name": a, "note": "A"},
                        {"name": b, "note": "B"},
                    ],
                    "windows": [{"name": w, "note": "W"}],
                },
            },
        )
        after = await mcp.call(
            "get_policy_application_bypass_entries", {"policy_name": name}
        )
        mac_names = {e["name"] for e in after["custom"]["mac"]}
        win_names = {e["name"] for e in after["custom"]["windows"]}
        assert {a, b}.issubset(mac_names)
        assert w in win_names

        await mcp.call(
            "delete_policy_application_bypass_entries",
            {"policy_name": name, "mac": [a], "windows": [w]},
        )
        shrunk = await mcp.call(
            "get_policy_application_bypass_entries", {"policy_name": name}
        )
        shrunk_mac = {e["name"] for e in shrunk["custom"]["mac"]}
        shrunk_win = {e["name"] for e in shrunk["custom"]["windows"]}
        assert a not in shrunk_mac
        assert b in shrunk_mac
        assert w not in shrunk_win


async def test_get_policy_restrictions_unknown_policy_errors(
    integration_config: IntegrationConfig,
) -> None:
    async with integration(integration_config) as (mcp, _cleaner):
        bogus = make_tag("nope")
        with pytest.raises(ToolError):
            await mcp.call("get_policy_restrictions", {"policy_name": bogus})
