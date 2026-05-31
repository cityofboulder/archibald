from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx

from archie.auth.base import ArcGISAuth


class NoAuth(ArcGISAuth):
    """Authentication implementation for public ESRI services that require no credentials."""

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Pass the request through without adding any Authorization header."""
        yield request

    async def get_token(self) -> str:
        """NoAuth does not issue tokens; returns an empty string."""
        return ""

    async def force_refresh(self) -> None:
        """No-op: NoAuth has no token to refresh."""
