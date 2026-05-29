"""Tests for the PoliciesService."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from dopesecurity.mcp_server.errors import InvalidPrincipalError
from dopesecurity.mcp_server.schemas import (
    CustomApplicationPlatformUpdate,
    CustomUrlBypassUpdate,
    DefaultUrlBypassUpdate,
    ExceptionCategoryUpdate,
    ExceptionUpdate,
    ReplacePolicyCategoryExceptionsInput,
    RestrictionUpdate,
    UpdatePolicyRestrictionsInput,
    UpsertPolicyApplicationBypassInput,
    UpsertPolicyUrlBypassInput,
)
from dopesecurity.mcp_server.services.policies import PoliciesService


class FakeFlightdeck:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.responses: dict[str, Any] = {}

    def _record(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        return self.responses.get(name)

    async def list_policies(self, params: Mapping[str, Any]) -> Any:
        return self._record("list_policies", params)

    async def create_policy(self, policy_name: str) -> Any:
        return self._record("create_policy", policy_name)

    async def delete_policy(self, policy_name: str) -> Any:
        return self._record("delete_policy", policy_name)

    async def get_policy_assignments(self, policy_name: str) -> Any:
        return self._record("get_policy_assignments", policy_name)

    async def update_policy_assignments(self, policy_name: str, body: Mapping[str, Any]) -> Any:
        return self._record("update_policy_assignments", policy_name, body=body)

    async def get_policy_content(self, policy_name: str) -> Any:
        return self._record("get_policy_content", policy_name)

    async def update_policy_content_restrictions(
        self, policy_name: str, body: Mapping[str, Any]
    ) -> Any:
        return self._record("update_policy_content_restrictions", policy_name, body=body)

    async def update_policy_content_exceptions(
        self, policy_name: str, body: Mapping[str, Any]
    ) -> Any:
        return self._record("update_policy_content_exceptions", policy_name, body=body)

    async def get_policy_url_bypass(self, policy_name: str) -> Any:
        return self._record("get_policy_url_bypass", policy_name)

    async def upsert_policy_url_bypass(
        self, policy_name: str, body: Mapping[str, Any]
    ) -> Any:
        return self._record("upsert_policy_url_bypass", policy_name, body=body)

    async def delete_policy_url_bypass_entries(
        self, policy_name: str, names: Sequence[str]
    ) -> Any:
        return self._record("delete_policy_url_bypass_entries", policy_name, names=list(names))

    async def get_policy_application_bypass(self, policy_name: str) -> Any:
        return self._record("get_policy_application_bypass", policy_name)

    async def upsert_policy_application_bypass(
        self, policy_name: str, body: Mapping[str, Any]
    ) -> Any:
        return self._record("upsert_policy_application_bypass", policy_name, body=body)

    async def delete_policy_application_bypass_entries(
        self,
        policy_name: str,
        *,
        mac: Sequence[str] | None,
        windows: Sequence[str] | None,
    ) -> Any:
        return self._record(
            "delete_policy_application_bypass_entries",
            policy_name,
            mac=list(mac) if mac is not None else None,
            windows=list(windows) if windows is not None else None,
        )


def _make() -> tuple[FakeFlightdeck, PoliciesService]:
    fake = FakeFlightdeck()
    return fake, PoliciesService(fake)  # type: ignore[arg-type]


# ---- list / lifecycle ----------------------------------------------------------


async def test_list_policies_normalizes_page_info_and_items() -> None:
    fake, svc = _make()
    fake.responses["list_policies"] = {
        "data": {
            "policies": [
                {
                    "policyName": "Engineering",
                    "updatedAt": "2025-07-23T08:30:09+00:00",
                    "sslInspection": "enabled",
                    "clashCount": 3,
                }
            ],
            "pageInfo": {"endCursor": "cur", "hasNextPage": True},
        }
    }

    result = await svc.list_policies(first=10, order="asc")

    assert fake.calls[0][1] == ({"first": 10, "order": "asc"},)
    assert result.policies[0].policy_name == "Engineering"
    assert result.policies[0].ssl_inspection == "enabled"
    assert result.policies[0].clash_count == 3
    assert result.policies[0].updated_at == "2025-07-23T08:30:09+00:00"
    assert result.page_info.end_cursor == "cur"
    assert result.page_info.has_next_page is True


# ---- assignments ---------------------------------------------------------------


async def test_assign_principals_merges_and_deduplicates() -> None:
    fake, svc = _make()
    fake.responses["get_policy_assignments"] = {
        "data": {
            "users": [{"email": "alice@example.com", "name": "Alice"}],
            "groups": [{"email": "engineers@example.com", "name": "Eng", "membersCount": 5}],
        }
    }

    await svc.assign_principals(
        "Engineering",
        user_emails=["alice@example.com", "bob@example.com"],
        group_emails=["sales@example.com"],
    )

    update_calls = [c for c in fake.calls if c[0] == "update_policy_assignments"]
    assert len(update_calls) == 1
    body = update_calls[0][2]["body"]
    assert body == {
        "users": ["alice@example.com", "bob@example.com"],
        "groups": ["engineers@example.com", "sales@example.com"],
    }


async def test_unassign_principals_ignores_missing() -> None:
    fake, svc = _make()
    fake.responses["get_policy_assignments"] = {
        "data": {
            "users": [{"email": "alice@example.com"}],
            "groups": [],
        }
    }

    await svc.unassign_principals(
        "Engineering",
        user_emails=["bob@example.com"],
    )

    body = next(c for c in fake.calls if c[0] == "update_policy_assignments")[2]["body"]
    assert body == {"users": ["alice@example.com"], "groups": []}


async def test_assignment_no_inputs_rejected_before_client_call() -> None:
    fake, svc = _make()

    with pytest.raises(InvalidPrincipalError):
        await svc.assign_principals("Engineering")

    assert fake.calls == []


# ---- restrictions --------------------------------------------------------------


async def test_get_restrictions_omits_exceptions() -> None:
    fake, svc = _make()
    fake.responses["get_policy_content"] = {
        "data": {
            "categories": {
                "inheritsFromBase": False,
                "restrictions": {
                    "Social Media": {
                        "restriction": "BLOCK",
                        "page": "blockpage1",
                        "description": "Social networks",
                        "exceptions": {
                            "alice@example.com": {"restriction": "ALLOW", "type": "users"},
                        },
                    }
                },
            },
            "customCategories": {
                "inheritsFromBase": False,
                "restrictions": {
                    "MyCat": {"restriction": "BLOCK", "page": "blockpage2", "exceptions": {}}
                },
            },
        }
    }

    result = await svc.get_restrictions("ExamplePolicy")

    assert len(result.categories.items) == 1
    assert result.categories.items[0].name == "Social Media"
    assert result.categories.items[0].restriction == "BLOCK"
    assert result.categories.items[0].description == "Social networks"
    # Exceptions field is not part of the restrictions schema and must not leak through.
    assert "exceptions" not in result.categories.items[0].model_dump()
    assert result.custom_categories.items[0].name == "MyCat"


async def test_update_restrictions_sends_only_submitted_categories() -> None:
    fake, svc = _make()

    await svc.update_restrictions(
        UpdatePolicyRestrictionsInput(
            policy_name="ExamplePolicy",
            categories=[RestrictionUpdate(name="Finance", restriction="BLOCK", page="bp1")],
        )
    )

    body = fake.calls[0][2]["body"]
    assert body == {
        "data": {
            "categories": {
                "Finance": {"restriction": "BLOCK", "page": "bp1"},
            }
        }
    }


@pytest.mark.parametrize(
    "scope, expected",
    [
        ("categories", {"categories": {"inheritsFromBase": True}}),
        ("custom_categories", {"customCategories": {"inheritsFromBase": True}}),
        (
            "both",
            {
                "categories": {"inheritsFromBase": True},
                "customCategories": {"inheritsFromBase": True},
            },
        ),
    ],
)
async def test_reset_restrictions_to_base_scopes(
    scope: str, expected: dict[str, Any]
) -> None:
    fake, svc = _make()

    await svc.reset_restrictions_to_base("ExamplePolicy", scope)  # type: ignore[arg-type]

    body = fake.calls[0][2]["body"]
    assert body == {"data": expected}


# ---- exceptions ----------------------------------------------------------------


async def test_get_exceptions_normalizes_principal_type() -> None:
    fake, svc = _make()
    fake.responses["get_policy_content"] = {
        "data": {
            "categories": {
                "inheritsFromBase": False,
                "restrictions": {
                    "Social Media": {
                        "restriction": "BLOCK",
                        "exceptions": {
                            "alice@example.com": {
                                "restriction": "ALLOW",
                                "type": "users",
                                "name": "Alice",
                            },
                        },
                    },
                },
            },
            "customCategories": {"inheritsFromBase": False, "restrictions": {}},
        }
    }

    result = await svc.get_exceptions("ExamplePolicy")

    assert result.categories.items[0].name == "Social Media"
    exception = result.categories.items[0].exceptions[0]
    assert exception.principal == "alice@example.com"
    assert exception.principal_type == "users"
    assert exception.restriction == "ALLOW"


async def test_replace_category_exceptions_replaces_per_submitted_category() -> None:
    fake, svc = _make()

    await svc.replace_category_exceptions(
        ReplacePolicyCategoryExceptionsInput(
            policy_name="ExamplePolicy",
            categories=[
                ExceptionCategoryUpdate(
                    name="Social Media",
                    exceptions=[
                        ExceptionUpdate(
                            principal="alice@example.com",
                            restriction="BLOCK",
                            page="blockpage1",
                        )
                    ],
                )
            ],
        )
    )

    body = fake.calls[0][2]["body"]
    assert body == {
        "data": {
            "categories": {
                "Social Media": {
                    "alice@example.com": {"restriction": "BLOCK", "page": "blockpage1"},
                }
            }
        }
    }


async def test_replace_category_exceptions_empty_list_clears_category() -> None:
    fake, svc = _make()

    await svc.replace_category_exceptions(
        ReplacePolicyCategoryExceptionsInput(
            policy_name="ExamplePolicy",
            categories=[ExceptionCategoryUpdate(name="Social Media", exceptions=[])],
        )
    )

    body = fake.calls[0][2]["body"]
    assert body == {"data": {"categories": {"Social Media": {}}}}


# ---- url bypass ----------------------------------------------------------------


async def test_url_bypass_delete_sends_names() -> None:
    fake, svc = _make()

    await svc.delete_url_bypass_entries("Marketing", ["a", "b"])

    call = next(c for c in fake.calls if c[0] == "delete_policy_url_bypass_entries")
    assert call[1] == ("Marketing",)
    assert call[2] == {"names": ["a", "b"]}


async def test_url_bypass_delete_rejects_empty() -> None:
    fake, svc = _make()
    with pytest.raises(InvalidPrincipalError):
        await svc.delete_url_bypass_entries("Marketing", [])
    assert fake.calls == []


async def test_upsert_url_bypass_sends_data_wrapped_payload() -> None:
    fake, svc = _make()

    await svc.upsert_url_bypass(
        UpsertPolicyUrlBypassInput(
            policy_name="Marketing",
            custom=[CustomUrlBypassUpdate(name="*.example.com", note="ok")],
            default=[DefaultUrlBypassUpdate(name="*.zoom.us", state="ignored")],
        )
    )

    body = fake.calls[0][2]["body"]
    assert body == {
        "data": {
            "custom": [{"name": "*.example.com", "note": "ok"}],
            "default": [{"name": "*.zoom.us", "state": "ignored"}],
        }
    }


async def test_reset_url_bypass_uses_inheritance_body() -> None:
    fake, svc = _make()
    await svc.reset_url_bypass_to_base("Marketing")
    body = fake.calls[0][2]["body"]
    assert body == {"data": {"inheritsFromBase": True}}


# ---- application bypass --------------------------------------------------------


async def test_application_bypass_reset_uses_inheritance_body() -> None:
    fake, svc = _make()
    await svc.reset_application_bypass_to_base("Marketing")
    body = fake.calls[0][2]["body"]
    assert body == {"data": {"inheritsFromBase": True}}


async def test_application_bypass_delete_sends_per_platform_payload() -> None:
    fake, svc = _make()

    await svc.delete_application_bypass_entries(
        "Marketing", mac=["Slack.app"], windows=["teams.exe"]
    )

    call = next(
        c for c in fake.calls if c[0] == "delete_policy_application_bypass_entries"
    )
    assert call[1] == ("Marketing",)
    assert call[2] == {"mac": ["Slack.app"], "windows": ["teams.exe"]}


async def test_application_bypass_delete_allows_single_platform() -> None:
    fake, svc = _make()

    await svc.delete_application_bypass_entries("Marketing", mac=["Slack.app"])

    call = next(
        c for c in fake.calls if c[0] == "delete_policy_application_bypass_entries"
    )
    assert call[2] == {"mac": ["Slack.app"], "windows": None}


async def test_application_bypass_delete_rejects_both_empty() -> None:
    fake, svc = _make()
    with pytest.raises(InvalidPrincipalError):
        await svc.delete_application_bypass_entries("Marketing")
    assert fake.calls == []


async def test_application_bypass_upsert_sends_per_platform_payload() -> None:
    fake, svc = _make()

    await svc.upsert_application_bypass(
        UpsertPolicyApplicationBypassInput(
            policy_name="Marketing",
            custom=CustomApplicationPlatformUpdate(
                mac=[CustomUrlBypassUpdate(name="Slack.app", note="Comm")],
            ),
        )
    )

    body = fake.calls[0][2]["body"]
    assert body == {
        "data": {
            "custom": {
                "mac": [{"name": "Slack.app", "note": "Comm"}],
            }
        }
    }
