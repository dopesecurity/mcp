"""Policy domain service backed by the Flightdeck partner API."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from dopesecurity.mcp_server.errors import (
    InvalidPrincipalError,
)
from dopesecurity.mcp_server.flightdeck.client import FlightdeckClient
from dopesecurity.mcp_server.schemas import (
    CustomApplicationPlatformBlock,
    CustomUrlBypassItem,
    DefaultApplicationPlatformBlock,
    DefaultUrlBypassItem,
    ExceptionCategoryItem,
    ExceptionCategoryUpdate,
    ExceptionItem,
    ExceptionsBlock,
    ListPoliciesResult,
    PageInfo,
    PolicyApplicationBypassResult,
    PolicyAssignmentsResult,
    PolicyExceptionsResult,
    PolicyGroupAssignment,
    PolicyItem,
    PolicyRestrictionsResult,
    PolicyUrlBypassResult,
    PolicyUserAssignment,
    ReplacePolicyCategoryExceptionsInput,
    RestrictionItem,
    RestrictionsBlock,
    RestrictionUpdate,
    SuccessResult,
    UpdatePolicyRestrictionsInput,
    UpsertPolicyApplicationBypassInput,
    UpsertPolicyUrlBypassInput,
    strip_data,
)


class PoliciesService:
    def __init__(self, flightdeck: FlightdeckClient) -> None:
        self._flightdeck = flightdeck

    # ---- list / lifecycle ---------------------------------------------------

    async def list_policies(
        self,
        *,
        first: int | None = None,
        after: str | None = None,
        order: Literal["asc", "desc"] | None = None,
    ) -> ListPoliciesResult:
        params: dict[str, Any] = {}
        if first is not None:
            params["first"] = first
        if after is not None:
            params["after"] = after
        if order is not None:
            params["order"] = order
        payload = await self._flightdeck.list_policies(params)
        data = strip_data(payload) if isinstance(payload, Mapping) else {}
        policies_raw = data.get("policies", []) if isinstance(data, Mapping) else []
        page_info_raw = data.get("pageInfo", {}) if isinstance(data, Mapping) else {}
        return ListPoliciesResult(
            policies=[PolicyItem.model_validate(p) for p in policies_raw or []],
            page_info=PageInfo.model_validate(page_info_raw)
            if isinstance(page_info_raw, Mapping)
            else PageInfo(),
        )

    async def create_policy(self, policy_name: str) -> SuccessResult:
        await self._flightdeck.create_policy(policy_name)
        return SuccessResult(message=f"Policy {policy_name!r} created")

    async def delete_policy(self, policy_name: str) -> SuccessResult:
        await self._flightdeck.delete_policy(policy_name)
        return SuccessResult(message=f"Policy {policy_name!r} deleted")

    # ---- assignments --------------------------------------------------------

    async def get_assignments(self, policy_name: str) -> PolicyAssignmentsResult:
        payload = await self._flightdeck.get_policy_assignments(policy_name)
        return _parse_assignments(payload)

    async def assign_principals(
        self,
        policy_name: str,
        *,
        user_emails: Sequence[str] | None = None,
        group_emails: Sequence[str] | None = None,
    ) -> PolicyAssignmentsResult:
        _require_any_principals(user_emails, group_emails)
        current = await self.get_assignments(policy_name)
        new_users = _merge_emails(_emails(current.users), user_emails)
        new_groups = _merge_emails(_emails(current.groups), group_emails)
        body = {"users": new_users, "groups": new_groups}
        await self._flightdeck.update_policy_assignments(policy_name, body)
        return await self.get_assignments(policy_name)

    async def unassign_principals(
        self,
        policy_name: str,
        *,
        user_emails: Sequence[str] | None = None,
        group_emails: Sequence[str] | None = None,
    ) -> PolicyAssignmentsResult:
        _require_any_principals(user_emails, group_emails)
        current = await self.get_assignments(policy_name)
        new_users = _remove_emails(_emails(current.users), user_emails)
        new_groups = _remove_emails(_emails(current.groups), group_emails)
        body = {"users": new_users, "groups": new_groups}
        await self._flightdeck.update_policy_assignments(policy_name, body)
        return await self.get_assignments(policy_name)

    # ---- restrictions -------------------------------------------------------

    async def get_restrictions(self, policy_name: str) -> PolicyRestrictionsResult:
        payload = await self._flightdeck.get_policy_content(policy_name)
        data = strip_data(payload) if isinstance(payload, Mapping) else {}
        return PolicyRestrictionsResult(
            categories=_parse_restrictions_block(
                data.get("categories") if isinstance(data, Mapping) else None,
                description_supported=True,
            ),
            custom_categories=_parse_restrictions_block(
                data.get("customCategories") if isinstance(data, Mapping) else None,
                description_supported=False,
            ),
        )

    async def update_restrictions(
        self, input: UpdatePolicyRestrictionsInput
    ) -> SuccessResult:
        sections: dict[str, Any] = {}
        if input.categories is not None:
            sections["categories"] = _restrictions_to_map(input.categories)
        if input.custom_categories is not None:
            sections["customCategories"] = _restrictions_to_map(input.custom_categories)
        body = {"data": sections}
        await self._flightdeck.update_policy_content_restrictions(input.policy_name, body)
        return SuccessResult(message="Policy restrictions updated")

    async def reset_restrictions_to_base(
        self,
        policy_name: str,
        scope: Literal["categories", "custom_categories", "both"],
    ) -> SuccessResult:
        sections: dict[str, Any] = {}
        if scope in ("categories", "both"):
            sections["categories"] = {"inheritsFromBase": True}
        if scope in ("custom_categories", "both"):
            sections["customCategories"] = {"inheritsFromBase": True}
        body = {"data": sections}
        await self._flightdeck.update_policy_content_restrictions(policy_name, body)
        return SuccessResult(message=f"Policy restrictions reset to base ({scope})")

    # ---- exceptions ---------------------------------------------------------

    async def get_exceptions(self, policy_name: str) -> PolicyExceptionsResult:
        payload = await self._flightdeck.get_policy_content(policy_name)
        data = strip_data(payload) if isinstance(payload, Mapping) else {}
        return PolicyExceptionsResult(
            categories=_parse_exceptions_block(
                data.get("categories") if isinstance(data, Mapping) else None,
            ),
            custom_categories=_parse_exceptions_block(
                data.get("customCategories") if isinstance(data, Mapping) else None,
            ),
        )

    async def replace_category_exceptions(
        self, input: ReplacePolicyCategoryExceptionsInput
    ) -> SuccessResult:
        sections: dict[str, Any] = {}
        if input.categories is not None:
            sections["categories"] = _exceptions_to_map(input.categories)
        if input.custom_categories is not None:
            sections["customCategories"] = _exceptions_to_map(input.custom_categories)
        body = {"data": sections}
        await self._flightdeck.update_policy_content_exceptions(input.policy_name, body)
        return SuccessResult(message="Policy exceptions updated")

    # ---- URL bypass ---------------------------------------------------------

    async def get_url_bypass(self, policy_name: str) -> PolicyUrlBypassResult:
        payload = await self._flightdeck.get_policy_url_bypass(policy_name)
        data = strip_data(payload) if isinstance(payload, Mapping) else {}
        if not isinstance(data, Mapping):
            return PolicyUrlBypassResult()
        return PolicyUrlBypassResult(
            inherits_from_base=bool(data.get("inheritsFromBase", False)),
            custom=[
                CustomUrlBypassItem.model_validate(c)
                for c in data.get("custom", []) or []
            ],
            default=[
                DefaultUrlBypassItem.model_validate(d)
                for d in data.get("default", []) or []
            ],
        )

    async def upsert_url_bypass(
        self, input: UpsertPolicyUrlBypassInput
    ) -> SuccessResult:
        section: dict[str, Any] = {}
        if input.custom is not None:
            section["custom"] = [c.model_dump(exclude_none=True) for c in input.custom]
        if input.default is not None:
            section["default"] = [
                d.model_dump(exclude_none=True) for d in input.default
            ]
        body = {"data": section}
        await self._flightdeck.upsert_policy_url_bypass(input.policy_name, body)
        return SuccessResult(message="URL bypass updated")

    async def delete_url_bypass_entries(
        self, policy_name: str, names: Sequence[str]
    ) -> SuccessResult:
        if not names:
            raise InvalidPrincipalError("names must not be empty")
        await self._flightdeck.delete_policy_url_bypass_entries(policy_name, list(names))
        return SuccessResult(message="URL bypass entries deleted")

    async def reset_url_bypass_to_base(self, policy_name: str) -> SuccessResult:
        body = {"data": {"inheritsFromBase": True}}
        await self._flightdeck.upsert_policy_url_bypass(policy_name, body)
        return SuccessResult(message="URL bypass reset to base")

    # ---- application bypass -------------------------------------------------

    async def get_application_bypass(
        self, policy_name: str
    ) -> PolicyApplicationBypassResult:
        payload = await self._flightdeck.get_policy_application_bypass(policy_name)
        data = strip_data(payload) if isinstance(payload, Mapping) else {}
        if not isinstance(data, Mapping):
            return PolicyApplicationBypassResult()
        custom_raw = data.get("custom", {}) or {}
        default_raw = data.get("default", {}) or {}
        return PolicyApplicationBypassResult(
            inherits_from_base=bool(data.get("inheritsFromBase", False)),
            custom=CustomApplicationPlatformBlock(
                mac=[
                    CustomUrlBypassItem.model_validate(item)
                    for item in (custom_raw.get("mac", []) or [])
                ],
                windows=[
                    CustomUrlBypassItem.model_validate(item)
                    for item in (custom_raw.get("windows", []) or [])
                ],
            ),
            default=DefaultApplicationPlatformBlock(
                mac=[
                    DefaultUrlBypassItem.model_validate(item)
                    for item in (default_raw.get("mac", []) or [])
                ],
                windows=[
                    DefaultUrlBypassItem.model_validate(item)
                    for item in (default_raw.get("windows", []) or [])
                ],
            ),
        )

    async def upsert_application_bypass(
        self, input: UpsertPolicyApplicationBypassInput
    ) -> SuccessResult:
        section: dict[str, Any] = {}
        if input.custom is not None:
            custom: dict[str, Any] = {}
            if input.custom.mac is not None:
                custom["mac"] = [c.model_dump(exclude_none=True) for c in input.custom.mac]
            if input.custom.windows is not None:
                custom["windows"] = [
                    c.model_dump(exclude_none=True) for c in input.custom.windows
                ]
            section["custom"] = custom
        if input.default is not None:
            default: dict[str, Any] = {}
            if input.default.mac is not None:
                default["mac"] = [d.model_dump(exclude_none=True) for d in input.default.mac]
            if input.default.windows is not None:
                default["windows"] = [
                    d.model_dump(exclude_none=True) for d in input.default.windows
                ]
            section["default"] = default
        body = {"data": section}
        await self._flightdeck.upsert_policy_application_bypass(input.policy_name, body)
        return SuccessResult(message="Application bypass updated")

    async def delete_application_bypass_entries(
        self,
        policy_name: str,
        *,
        mac: Sequence[str] | None = None,
        windows: Sequence[str] | None = None,
    ) -> SuccessResult:
        if not mac and not windows:
            raise InvalidPrincipalError(
                "At least one of mac or windows must be a non-empty list"
            )
        await self._flightdeck.delete_policy_application_bypass_entries(
            policy_name, mac=mac, windows=windows
        )
        return SuccessResult(message="Application bypass entries deleted")

    async def reset_application_bypass_to_base(
        self, policy_name: str
    ) -> SuccessResult:
        body = {"data": {"inheritsFromBase": True}}
        await self._flightdeck.upsert_policy_application_bypass(policy_name, body)
        return SuccessResult(message="Application bypass reset to base")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_assignments(payload: Any) -> PolicyAssignmentsResult:
    data = strip_data(payload) if isinstance(payload, Mapping) else {}
    if not isinstance(data, Mapping):
        return PolicyAssignmentsResult()
    return PolicyAssignmentsResult(
        users=[PolicyUserAssignment.model_validate(u) for u in data.get("users", []) or []],
        groups=[PolicyGroupAssignment.model_validate(g) for g in data.get("groups", []) or []],
    )


def _emails(items: Iterable[Any]) -> list[str]:
    return [item.email for item in items if getattr(item, "email", None)]


def _require_any_principals(
    user_emails: Sequence[str] | None, group_emails: Sequence[str] | None
) -> None:
    if not user_emails and not group_emails:
        raise InvalidPrincipalError(
            "At least one of user_emails or group_emails must be provided"
        )


def _merge_emails(existing: Sequence[str], to_add: Sequence[str] | None) -> list[str]:
    if not to_add:
        return list(existing)
    seen: set[str] = set()
    merged: list[str] = []
    for email in list(existing) + list(to_add):
        if email in seen:
            continue
        seen.add(email)
        merged.append(email)
    return merged


def _remove_emails(existing: Sequence[str], to_remove: Sequence[str] | None) -> list[str]:
    if not to_remove:
        return list(existing)
    drop = set(to_remove)
    return [email for email in existing if email not in drop]


def _parse_restrictions_block(
    block: Any, *, description_supported: bool
) -> RestrictionsBlock:
    if not isinstance(block, Mapping):
        return RestrictionsBlock()
    inherits = bool(block.get("inheritsFromBase", False))
    restrictions = block.get("restrictions") or {}
    items: list[RestrictionItem] = []
    if isinstance(restrictions, Mapping):
        for name, value in restrictions.items():
            if not isinstance(value, Mapping):
                continue
            payload: dict[str, Any] = {
                "name": name,
                "restriction": value.get("restriction"),
                "page": value.get("page"),
            }
            if description_supported:
                payload["description"] = value.get("description")
            items.append(RestrictionItem.model_validate(payload))
    return RestrictionsBlock(inherits_from_base=inherits, items=items)


def _restrictions_to_map(items: Sequence[RestrictionUpdate]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        entry: dict[str, Any] = {"restriction": item.restriction}
        if item.page is not None:
            entry["page"] = item.page
        result[item.name] = entry
    return result


def _parse_exceptions_block(block: Any) -> ExceptionsBlock:
    if not isinstance(block, Mapping):
        return ExceptionsBlock()
    inherits = bool(block.get("inheritsFromBase", False))
    restrictions = block.get("restrictions") or {}
    items: list[ExceptionCategoryItem] = []
    if isinstance(restrictions, Mapping):
        for name, value in restrictions.items():
            if not isinstance(value, Mapping):
                continue
            exceptions_raw = value.get("exceptions") or {}
            exception_items: list[ExceptionItem] = []
            if isinstance(exceptions_raw, Mapping):
                for principal, ex_value in exceptions_raw.items():
                    if not isinstance(ex_value, Mapping):
                        continue
                    payload: dict[str, Any] = dict(ex_value)
                    payload["principal"] = principal
                    exception_items.append(ExceptionItem.model_validate(payload))
            items.append(
                ExceptionCategoryItem(name=name, exceptions=exception_items)
            )
    return ExceptionsBlock(inherits_from_base=inherits, items=items)


def _exceptions_to_map(items: Sequence[ExceptionCategoryUpdate]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cat in items:
        principals: dict[str, Any] = {}
        for ex in cat.exceptions:
            entry: dict[str, Any] = {"restriction": ex.restriction}
            if ex.page is not None:
                entry["page"] = ex.page
            principals[ex.principal] = entry
        result[cat.name] = principals
    return result
