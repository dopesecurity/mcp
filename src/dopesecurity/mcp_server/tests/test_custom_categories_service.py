"""Tests for the CustomCategoriesService."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from dopesecurity.mcp_server.errors import (
    FlightdeckNotFoundError,
    InvalidPrincipalError,
)
from dopesecurity.mcp_server.services.custom_categories import CustomCategoriesService


class FakeFlightdeck:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.responses: dict[str, Any] = {}

    def _record(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        return self.responses.get(name)

    async def list_custom_categories(self, params: Mapping[str, Any]) -> Any:
        return self._record("list_custom_categories", params)

    async def get_custom_category_urls(self, custom_category_name: str) -> Any:
        return self._record("get_custom_category_urls", custom_category_name)

    async def create_custom_category(self, custom_category_name: str) -> Any:
        return self._record("create_custom_category", custom_category_name)

    async def delete_custom_category(self, custom_category_name: str) -> Any:
        return self._record("delete_custom_category", custom_category_name)

    async def add_urls_to_custom_category(
        self, custom_category_name: str, urls: Sequence[str]
    ) -> Any:
        return self._record(
            "add_urls_to_custom_category", custom_category_name, urls=list(urls)
        )

    async def delete_all_urls_from_custom_category(self, custom_category_name: str) -> Any:
        return self._record("delete_all_urls_from_custom_category", custom_category_name)

    async def delete_single_url_from_custom_category(
        self, custom_category_name: str, encoded_url: str
    ) -> Any:
        return self._record(
            "delete_single_url_from_custom_category",
            custom_category_name,
            encoded_url=encoded_url,
        )


def _make() -> tuple[FakeFlightdeck, CustomCategoriesService]:
    fake = FakeFlightdeck()
    return fake, CustomCategoriesService(fake)  # type: ignore[arg-type]


async def test_list_custom_categories_normalizes_items_and_page_info() -> None:
    fake, svc = _make()
    fake.responses["list_custom_categories"] = {
        "data": {
            "customCategories": ["Gambling", "Streaming"],
            "pageInfo": {"endCursor": "cur", "hasNextPage": False},
        }
    }

    result = await svc.list_custom_categories(first=10)

    assert [c.name for c in result.custom_categories] == ["Gambling", "Streaming"]
    assert result.page_info.end_cursor == "cur"
    assert result.page_info.has_next_page is False
    assert fake.calls[0][1] == ({"first": 10},)


async def test_get_custom_category_urls_returns_urls() -> None:
    fake, svc = _make()
    fake.responses["get_custom_category_urls"] = {
        "data": {"urls": ["dope.security", "google.com"]}
    }

    result = await svc.get_urls("Gambling")

    assert result.urls == ["dope.security", "google.com"]


async def test_add_urls_rejects_empty_list_before_client_call() -> None:
    fake, svc = _make()
    with pytest.raises(InvalidPrincipalError):
        await svc.add_urls("Gambling", [])
    assert fake.calls == []


async def test_delete_single_url_encodes_url() -> None:
    fake, svc = _make()
    await svc.delete_single_url("Gambling", "https://example.com/a?b=c")
    call = next(c for c in fake.calls if c[0] == "delete_single_url_from_custom_category")
    assert call[1] == ("Gambling",)
    assert call[2]["encoded_url"] == "https%3A%2F%2Fexample.com%2Fa%3Fb%3Dc"


async def test_delete_single_url_wraps_not_found_with_category_and_url() -> None:
    class RaisingFlightdeck(FakeFlightdeck):
        async def delete_single_url_from_custom_category(
            self, custom_category_name: str, encoded_url: str
        ) -> Any:
            raise FlightdeckNotFoundError(details={"message": "Not Found"})

    fake = RaisingFlightdeck()
    # FakeFlightdeck stands in for FlightdeckClient; matches existing _make() pattern.
    svc = CustomCategoriesService(fake)  # type: ignore[arg-type]

    with pytest.raises(FlightdeckNotFoundError) as exc_info:
        await svc.delete_single_url("Gambling", "https://example.com/a")

    assert "'Gambling'" in str(exc_info.value)
    assert "'https://example.com/a'" in str(exc_info.value)
