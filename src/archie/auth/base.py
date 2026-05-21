# archie/auth/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

import httpx


class ArcGISAuth(httpx.Auth, ABC):
    """Abstract base class for all archie authentication implementations.

    Subclasses must implement get_token(), which is called on every request.
    Token caching, refresh logic, and expiry management are the subclass's
    responsibility. This base class owns only the header injection contract.
    """

    requires_response_body = False

    @abstractmethod
    async def get_token(self) -> str:
        """Return a valid access token.

        Implementations are responsible for caching, refresh, and expiry.
        This method must always return a token that is ready to use.
        """
    
    @abstractmethod
    async def force_refresh(self) -> None:
        """Unconditionally refresh the access token.

        Called by ArchieClient when a 498/499 response is received. Implementations
        must fetch a fresh token regardless of any cached state.
        """

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Inject the Bearer token into the request's Authorization header."""
        token = await self.get_token()
        request.headers["Authorization"] = f"Bearer {token}"
        yield request

    async def __aenter__(self) -> ArcGISAuth:
        """Enter the async context manager."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the async context manager and release resources."""
        await self.aclose()

    async def aclose(self) -> None:
        """Release any resources held by this auth instance.

        Subclasses that hold an internal httpx.AsyncClient should override
        this method to close it. The base implementation is a no-op.
        """
