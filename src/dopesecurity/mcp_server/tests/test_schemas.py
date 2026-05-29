"""Tests for MCP-facing schemas and helpers."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dopesecurity.mcp_server.schemas import (
    EndpointSearchInput,
    ExceptionItem,
    PageInfo,
    ReplacePolicyCategoryExceptionsInput,
    UpdatePolicyRestrictionsInput,
    UpsertPolicyUrlBypassInput,
    endpoint_search_params,
    strip_data,
)


def test_endpoint_search_allows_zero_filter_fields() -> None:
    params = endpoint_search_params(EndpointSearchInput(first=10, order="asc"))
    assert params == {"first": 10, "order": "asc"}


def test_endpoint_search_allows_one_filter_field_and_maps_names() -> None:
    params = endpoint_search_params(EndpointSearchInput(query="alice"))
    assert params == {"id": "alice"}

    params = endpoint_search_params(EndpointSearchInput(email_id="alice@example.com"))
    assert params == {"emailId": "alice@example.com"}


def test_endpoint_search_rejects_multiple_filter_fields() -> None:
    with pytest.raises(ValidationError):
        EndpointSearchInput(query="alice", email_id="alice@example.com")


def test_endpoint_search_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        EndpointSearchInput(unknown_filter="x")  # type: ignore[call-arg]


def test_endpoint_search_first_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        EndpointSearchInput(first=0)


def test_page_info_parses_camel_case_aliases() -> None:
    info = PageInfo.model_validate({"endCursor": "abc", "hasNextPage": True})
    assert info.end_cursor == "abc"
    assert info.has_next_page is True


def test_strip_data_unwraps_when_present() -> None:
    payload: dict[str, object] = {"data": {"endpoints": [{"deviceName": "x"}]}}
    assert strip_data(payload) == {"endpoints": [{"deviceName": "x"}]}


def test_strip_data_passes_through_when_missing() -> None:
    payload: dict[str, object] = {"endpoints": []}
    assert strip_data(payload) == payload


def test_exception_item_normalizes_type_to_principal_type() -> None:
    item = ExceptionItem.model_validate(
        {
            "principal": "alice@example.com",
            "restriction": "ALLOW",
            "type": "users",
            "name": "Alice",
        }
    )
    assert item.principal_type == "users"
    assert item.name == "Alice"


def test_update_restrictions_requires_at_least_one_section() -> None:
    with pytest.raises(ValidationError):
        UpdatePolicyRestrictionsInput(policy_name="Engineering")


def test_replace_exceptions_requires_at_least_one_section() -> None:
    with pytest.raises(ValidationError):
        ReplacePolicyCategoryExceptionsInput(policy_name="Engineering")


def test_upsert_url_bypass_requires_at_least_one_section() -> None:
    with pytest.raises(ValidationError):
        UpsertPolicyUrlBypassInput(policy_name="Engineering")


def test_mutating_inputs_reject_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        UpdatePolicyRestrictionsInput(
            policy_name="Engineering",
            categories=[{"name": "Social", "restriction": "BLOCK", "extra": "no"}],  # type: ignore[list-item]
        )
