"""MCP-facing input/output models and shared normalization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


class _StrictSnakeModel(BaseModel):
    """Base model for Flightdeck-derived inputs.

    Allows extra Flightdeck fields to pass through transparently and
    renames a configured set of camelCase input keys to snake_case
    field names before validation.

    We avoid Pydantic ``validation_alias`` because it leaks into the
    JSON schema FastMCP generates for tool outputs (validation-mode
    schema uses the alias as the property name), which then mismatches
    the snake_case keys produced by ``model_dump(by_alias=True)``.
    Subclasses set ``_input_aliases`` as a ``ClassVar`` mapping
    ``{wire_input_key: model_field_name}``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    _input_aliases: ClassVar[dict[str, str]] = {}

    @model_validator(mode="before")
    @classmethod
    def _rename_input_keys(cls, data: Any) -> Any:
        if isinstance(data, dict) and cls._input_aliases:
            return {cls._input_aliases.get(k, k): v for k, v in data.items()}
        return data


class PageInfo(_StrictSnakeModel):
    """Cursor pagination metadata exposed in MCP outputs."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    _input_aliases: ClassVar[dict[str, str]] = {
        "endCursor": "end_cursor",
        "hasNextPage": "has_next_page",
    }

    end_cursor: str | None = None
    has_next_page: bool = False


class SuccessResult(BaseModel):
    """Generic success result for write operations that return no body."""

    message: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def strip_data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Strip the top-level Flightdeck `data` wrapper if present."""

    inner = payload.get("data")
    if isinstance(inner, Mapping):
        return inner
    return payload


_INHERITS_FROM_BASE_DESCRIPTION = (
    "True when this policy has no override at this layer and the effective "
    "behavior comes from the base policy. The listed items are still the "
    "ones in force; they are just inherited rather than locally configured."
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


_ENDPOINT_SEARCH_FIELDS: tuple[str, ...] = (
    "query",
    "email_id",
    "device_name",
    "user_id",
    "os_version",
    "status",
    "debug_state",
    "fallback_mode",
    "location_id",
    "agent_version",
)

_ENDPOINT_PARAM_NAME_MAP: dict[str, str] = {
    "query": "id",
    "email_id": "emailId",
    "device_name": "deviceName",
    "user_id": "userId",
    "os_version": "osVersion",
    "status": "status",
    "debug_state": "debugState",
    "fallback_mode": "fallbackMode",
    "location_id": "locationId",
    "agent_version": "agentVersion",
}


class EndpointSearchInput(BaseModel):
    """Input for `search_endpoints`. Allows zero or one filter field."""

    model_config = ConfigDict(extra="forbid")

    first: int | None = Field(default=None, gt=0)
    after: str | None = None
    order: Literal["asc", "desc"] | None = None

    query: str | None = None
    email_id: str | None = None
    device_name: str | None = None
    user_id: str | None = None
    os_version: str | None = None
    status: str | None = None
    debug_state: str | None = None
    fallback_mode: str | None = None
    location_id: str | None = None
    agent_version: str | None = None

    @model_validator(mode="after")
    def _at_most_one_filter(self) -> EndpointSearchInput:
        active = [
            name
            for name in _ENDPOINT_SEARCH_FIELDS
            if getattr(self, name) is not None
        ]
        if len(active) > 1:
            raise ValueError(
                "search_endpoints accepts at most one of "
                + ", ".join(_ENDPOINT_SEARCH_FIELDS)
                + f"; got {active}"
            )
        return self


def endpoint_search_params(input: EndpointSearchInput) -> dict[str, Any]:
    """Translate an EndpointSearchInput into Flightdeck query parameters."""

    params: dict[str, Any] = {}
    if input.first is not None:
        params["first"] = input.first
    if input.after is not None:
        params["after"] = input.after
    if input.order is not None:
        params["order"] = input.order
    for field, api_name in _ENDPOINT_PARAM_NAME_MAP.items():
        value = getattr(input, field)
        if value is not None:
            params[api_name] = value
    return params


class EndpointItem(_StrictSnakeModel):
    """Endpoint summary returned by `search_endpoints`."""

    _input_aliases: ClassVar[dict[str, str]] = {
        "agentUUID": "agent_uuid",
        "userUUID": "user_uuid",
        "agentVersion": "agent_version",
        "deviceName": "device_name",
        "emailId": "email_id",
        "userId": "user_id",
        "osVersion": "os_version",
        "policyName": "policy_name",
        "debugState": "debug_state",
        "fallbackMode": "fallback_mode",
        "lastSeen": "last_seen",
    }

    agent_uuid: str | None = None
    user_uuid: str | None = None
    agent_version: str | None = None
    device_name: str | None = None
    email_id: str | None = None
    user_id: str | None = None
    os_version: str | None = None
    policy_name: str | None = Field(
        default=None,
        description=(
            "Name of the policy assigned to this endpoint's user. Use with "
            "get_policy_restrictions / get_policy_exceptions / get_policy_url_bypass "
            "to read what the user is actually allowed to access."
        ),
    )
    status: str | None = Field(
        default=None,
        description=(
            "Agent enforcement state on the device (e.g. 'active', 'disabled'). "
            "Describes whether the agent is enforcing policy, NOT whether the user "
            "is blocked. A 'disabled' agent enforces nothing, so the user is "
            "generally less restricted, not more."
        ),
    )
    debug_state: str | None = None
    fallback_mode: bool | None = Field(
        default=None,
        description=(
            "True when the agent is in fallback mode (reduced enforcement, e.g. due "
            "to a network or service issue). Like `status`, describes agent state, "
            "not policy decisions."
        ),
    )
    last_seen: str | None = None


class SearchEndpointsResult(BaseModel):
    """Result for `search_endpoints`."""

    endpoints: list[EndpointItem] = Field(default_factory=list)
    page_info: PageInfo = Field(default_factory=PageInfo)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


class PolicyItem(_StrictSnakeModel):
    """Summary of a policy returned by `list_policies`."""

    _input_aliases: ClassVar[dict[str, str]] = {
        "policyName": "policy_name",
        "updatedAt": "updated_at",
        "sslInspection": "ssl_inspection",
        "clashCount": "clash_count",
    }

    policy_name: str
    updated_at: str | None = None
    ssl_inspection: str | None = None
    clash_count: int | None = None


class ListPoliciesResult(BaseModel):
    policies: list[PolicyItem] = Field(default_factory=list)
    page_info: PageInfo = Field(default_factory=PageInfo)


class PolicyUserAssignment(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    email: str
    name: str | None = None


class PolicyGroupAssignment(_StrictSnakeModel):
    _input_aliases: ClassVar[dict[str, str]] = {
        "membersCount": "members_count",
    }

    email: str
    name: str | None = None
    members_count: int | None = None


class PolicyAssignmentsResult(BaseModel):
    users: list[PolicyUserAssignment] = Field(default_factory=list)
    groups: list[PolicyGroupAssignment] = Field(default_factory=list)


# Policy restrictions ---------------------------------------------------------


RestrictionLiteral = Literal["ALLOW", "BLOCK", "WARNING", "IGNORE"]


class RestrictionItem(BaseModel):
    """A single category restriction in a derived read."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    restriction: RestrictionLiteral
    page: str | None = None
    description: str | None = None


class RestrictionsBlock(BaseModel):
    inherits_from_base: bool = Field(
        default=False, description=_INHERITS_FROM_BASE_DESCRIPTION
    )
    items: list[RestrictionItem] = Field(default_factory=list)


class PolicyRestrictionsResult(BaseModel):
    categories: RestrictionsBlock = Field(default_factory=RestrictionsBlock)
    custom_categories: RestrictionsBlock = Field(default_factory=RestrictionsBlock)


class RestrictionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    restriction: RestrictionLiteral
    page: str | None = None


class UpdatePolicyRestrictionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_name: str
    categories: list[RestrictionUpdate] | None = None
    custom_categories: list[RestrictionUpdate] | None = None

    @model_validator(mode="after")
    def _at_least_one_section(self) -> UpdatePolicyRestrictionsInput:
        if self.categories is None and self.custom_categories is None:
            raise ValueError(
                "update_policy_restrictions requires at least one of categories or custom_categories"
            )
        return self


# Policy exceptions -----------------------------------------------------------


class ExceptionItem(_StrictSnakeModel):
    """A single exception in a derived read."""

    _input_aliases: ClassVar[dict[str, str]] = {
        "type": "principal_type",
    }

    principal: str
    restriction: RestrictionLiteral
    page: str | None = None
    name: str | None = None
    principal_type: str | None = None


class ExceptionCategoryItem(BaseModel):
    name: str
    exceptions: list[ExceptionItem] = Field(default_factory=list)


class ExceptionsBlock(BaseModel):
    inherits_from_base: bool = Field(
        default=False, description=_INHERITS_FROM_BASE_DESCRIPTION
    )
    items: list[ExceptionCategoryItem] = Field(default_factory=list)


class PolicyExceptionsResult(BaseModel):
    categories: ExceptionsBlock = Field(default_factory=ExceptionsBlock)
    custom_categories: ExceptionsBlock = Field(default_factory=ExceptionsBlock)


class ExceptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal: str
    restriction: RestrictionLiteral
    page: str | None = None


class ExceptionCategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    exceptions: list[ExceptionUpdate]


class ReplacePolicyCategoryExceptionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_name: str
    categories: list[ExceptionCategoryUpdate] | None = None
    custom_categories: list[ExceptionCategoryUpdate] | None = None

    @model_validator(mode="after")
    def _at_least_one_section(self) -> ReplacePolicyCategoryExceptionsInput:
        if self.categories is None and self.custom_categories is None:
            raise ValueError(
                "replace_policy_category_exceptions requires at least one of "
                "categories or custom_categories"
            )
        return self


# URL bypass ------------------------------------------------------------------


class CustomUrlBypassItem(_StrictSnakeModel):
    _input_aliases: ClassVar[dict[str, str]] = {
        "updatedBy": "updated_by",
        "updatedAt": "updated_at",
    }

    name: str
    note: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None


class DefaultUrlBypassItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    state: str


class PolicyUrlBypassResult(BaseModel):
    inherits_from_base: bool = Field(
        default=False, description=_INHERITS_FROM_BASE_DESCRIPTION
    )
    custom: list[CustomUrlBypassItem] = Field(default_factory=list)
    default: list[DefaultUrlBypassItem] = Field(default_factory=list)


class CustomUrlBypassUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    note: str | None = None


class DefaultUrlBypassUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    state: Literal["applied", "ignored"]


class UpsertPolicyUrlBypassInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_name: str
    custom: list[CustomUrlBypassUpdate] | None = None
    default: list[DefaultUrlBypassUpdate] | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> UpsertPolicyUrlBypassInput:
        if self.custom is None and self.default is None:
            raise ValueError(
                "upsert_policy_url_bypass requires at least one of custom or default"
            )
        return self


# Application bypass ----------------------------------------------------------


class CustomApplicationPlatformBlock(BaseModel):
    mac: list[CustomUrlBypassItem] = Field(default_factory=list)
    windows: list[CustomUrlBypassItem] = Field(default_factory=list)


class DefaultApplicationPlatformBlock(BaseModel):
    mac: list[DefaultUrlBypassItem] = Field(default_factory=list)
    windows: list[DefaultUrlBypassItem] = Field(default_factory=list)


class PolicyApplicationBypassResult(BaseModel):
    inherits_from_base: bool = Field(
        default=False, description=_INHERITS_FROM_BASE_DESCRIPTION
    )
    custom: CustomApplicationPlatformBlock = Field(default_factory=CustomApplicationPlatformBlock)
    default: DefaultApplicationPlatformBlock = Field(
        default_factory=DefaultApplicationPlatformBlock
    )


class CustomApplicationPlatformUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mac: list[CustomUrlBypassUpdate] | None = None
    windows: list[CustomUrlBypassUpdate] | None = None


class DefaultApplicationPlatformUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mac: list[DefaultUrlBypassUpdate] | None = None
    windows: list[DefaultUrlBypassUpdate] | None = None


class UpsertPolicyApplicationBypassInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_name: str
    custom: CustomApplicationPlatformUpdate | None = None
    default: DefaultApplicationPlatformUpdate | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> UpsertPolicyApplicationBypassInput:
        if self.custom is None and self.default is None:
            raise ValueError(
                "upsert_policy_application_bypass requires at least one of custom or default"
            )
        return self


# ---------------------------------------------------------------------------
# Custom categories
# ---------------------------------------------------------------------------


class CustomCategoryItem(BaseModel):
    """Custom category names returned by Flightdeck as plain strings."""

    name: str

    @classmethod
    def from_value(cls, value: Any) -> CustomCategoryItem:
        if isinstance(value, str):
            return cls(name=value)
        if isinstance(value, Mapping):
            name = value.get("name") or value.get("customCategoryName")
            if isinstance(name, str):
                return cls(name=name)
        raise ValueError(f"Unexpected custom category value: {value!r}")


class ListCustomCategoriesResult(BaseModel):
    custom_categories: list[CustomCategoryItem] = Field(default_factory=list)
    page_info: PageInfo = Field(default_factory=PageInfo)


class CustomCategoryUrlsResult(BaseModel):
    urls: list[str] = Field(default_factory=list)


__all__ = [
    "CustomApplicationPlatformBlock",
    "CustomApplicationPlatformUpdate",
    "CustomCategoryItem",
    "CustomCategoryUrlsResult",
    "CustomUrlBypassItem",
    "CustomUrlBypassUpdate",
    "DefaultApplicationPlatformBlock",
    "DefaultApplicationPlatformUpdate",
    "DefaultUrlBypassItem",
    "DefaultUrlBypassUpdate",
    "EndpointItem",
    "EndpointSearchInput",
    "ExceptionCategoryItem",
    "ExceptionCategoryUpdate",
    "ExceptionItem",
    "ExceptionUpdate",
    "ExceptionsBlock",
    "ListCustomCategoriesResult",
    "ListPoliciesResult",
    "PageInfo",
    "PolicyApplicationBypassResult",
    "PolicyAssignmentsResult",
    "PolicyExceptionsResult",
    "PolicyGroupAssignment",
    "PolicyItem",
    "PolicyRestrictionsResult",
    "PolicyUrlBypassResult",
    "PolicyUserAssignment",
    "ReplacePolicyCategoryExceptionsInput",
    "RestrictionItem",
    "RestrictionUpdate",
    "RestrictionsBlock",
    "SearchEndpointsResult",
    "SuccessResult",
    "UpdatePolicyRestrictionsInput",
    "UpsertPolicyApplicationBypassInput",
    "UpsertPolicyUrlBypassInput",
    "endpoint_search_params",
    "strip_data",
]
