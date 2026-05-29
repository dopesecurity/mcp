"""Wire-close Flightdeck models used by the API client."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

JsonObject = dict[str, Any]
JsonValue = Any


class TokenResponse(BaseModel):
    """OAuth client-credentials token response."""

    access_token: str
    token_type: str
    expires_in: float


class PageInfo(BaseModel):
    """Cursor pagination info as returned by Flightdeck."""

    model_config = ConfigDict(populate_by_name=True)

    end_cursor: str | None = Field(default=None, alias="endCursor")
    has_next_page: bool = Field(default=False, alias="hasNextPage")
