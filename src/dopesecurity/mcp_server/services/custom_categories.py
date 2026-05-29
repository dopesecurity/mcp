"""Custom category service backed by the Flightdeck API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal
from urllib.parse import quote

from dopesecurity.mcp_server.errors import FlightdeckNotFoundError, InvalidPrincipalError
from dopesecurity.mcp_server.flightdeck.client import FlightdeckClient
from dopesecurity.mcp_server.schemas import (
    CustomCategoryItem,
    CustomCategoryUrlsResult,
    ListCustomCategoriesResult,
    PageInfo,
    SuccessResult,
    strip_data,
)


class CustomCategoriesService:
    def __init__(self, flightdeck: FlightdeckClient) -> None:
        self._flightdeck = flightdeck

    async def list_custom_categories(
        self,
        *,
        first: int | None = None,
        after: str | None = None,
        order: Literal["asc", "desc"] | None = None,
    ) -> ListCustomCategoriesResult:
        params: dict[str, Any] = {}
        if first is not None:
            params["first"] = first
        if after is not None:
            params["after"] = after
        if order is not None:
            params["order"] = order
        payload = await self._flightdeck.list_custom_categories(params)
        data = strip_data(payload) if isinstance(payload, Mapping) else {}
        names_raw = data.get("customCategories", []) if isinstance(data, Mapping) else []
        page_info_raw = data.get("pageInfo", {}) if isinstance(data, Mapping) else {}
        return ListCustomCategoriesResult(
            custom_categories=[CustomCategoryItem.from_value(v) for v in names_raw or []],
            page_info=PageInfo.model_validate(page_info_raw)
            if isinstance(page_info_raw, Mapping)
            else PageInfo(),
        )

    async def get_urls(self, custom_category_name: str) -> CustomCategoryUrlsResult:
        payload = await self._flightdeck.get_custom_category_urls(custom_category_name)
        data = strip_data(payload) if isinstance(payload, Mapping) else {}
        urls = data.get("urls", []) if isinstance(data, Mapping) else []
        return CustomCategoryUrlsResult(
            urls=[u for u in urls or [] if isinstance(u, str)]
        )

    async def create(self, custom_category_name: str) -> SuccessResult:
        await self._flightdeck.create_custom_category(custom_category_name)
        return SuccessResult(message=f"Custom category {custom_category_name!r} created")

    async def delete(self, custom_category_name: str) -> SuccessResult:
        await self._flightdeck.delete_custom_category(custom_category_name)
        return SuccessResult(message=f"Custom category {custom_category_name!r} deleted")

    async def add_urls(
        self, custom_category_name: str, urls: Sequence[str]
    ) -> SuccessResult:
        if not urls:
            raise InvalidPrincipalError("urls must be a non-empty list")
        await self._flightdeck.add_urls_to_custom_category(custom_category_name, list(urls))
        return SuccessResult(message="URLs added")

    async def delete_all_urls(self, custom_category_name: str) -> SuccessResult:
        await self._flightdeck.delete_all_urls_from_custom_category(custom_category_name)
        return SuccessResult(message="All URLs deleted")

    async def delete_single_url(
        self, custom_category_name: str, url: str
    ) -> SuccessResult:
        if not url:
            raise InvalidPrincipalError("url must be a non-empty string")
        encoded = quote(url, safe="")
        try:
            await self._flightdeck.delete_single_url_from_custom_category(
                custom_category_name, encoded
            )
        except FlightdeckNotFoundError as exc:
            raise FlightdeckNotFoundError(
                f"Custom category {custom_category_name!r} has no URL {url!r}",
                details=exc.normalized.details,
            ) from exc
        return SuccessResult(message=f"URL {url!r} deleted")
