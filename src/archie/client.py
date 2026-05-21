from __future__ import annotations

import httpx

from archie.auth.base import ArcGISAuth
from archie.errors import handle_esri_errors
from archie.exceptions import TokenExpiredError, TokenMissingError


class ArchieClient:
    """Async HTTP client for ESRI REST APIs.

    Manages an internal httpx.AsyncClient with lazy initialization. Enforces
    f=json on all requests (preserving f=geojson when explicitly set), handles
    token refresh on 498/499 responses, and raises for HTTP-level errors before
    ESRI envelope errors are inspected.

    Can be used as an async context manager or instantiated directly; in the
    latter case call aclose() manually when done.
    """

    def __init__(self, base_url: str, auth: ArcGISAuth) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the shared httpx.AsyncClient, creating it lazily on first call."""
        if self._client is None:
            self._client = httpx.AsyncClient(auth=self._auth)
        return self._client

    def _build_url(self, url: str | None, endpoint: str | None) -> str:
        """Construct the full request URL.

        If *url* is provided it is used as the base instead of self._base_url.
        *endpoint* is appended to whichever base wins.
        """
        base = (url or self._base_url).rstrip("/")
        suffix = (endpoint or "").lstrip("/")
        return f"{base}/{suffix}" if suffix else base

    def _enforce_format(self, params: dict) -> dict:
        """Return a copy of *params* with f=json enforced.

        Preserves f=geojson if the caller explicitly set it; overwrites any
        other value.
        """
        result = dict(params)
        if result.get("f") != "geojson":
            result["f"] = "json"
        return result

    @handle_esri_errors
    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute an HTTP request and return the response.

        URL construction and format enforcement are the caller's responsibility.
        Raises for HTTP-level errors before returning; @handle_esri_errors then
        inspects the body for ESRI envelope errors.
        """
        client = await self._get_client()
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    async def _request_with_refresh(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        """Delegate to _request, retrying once after a token refresh on 498/499."""
        try:
            return await self._request(method, url, **kwargs)
        except (TokenExpiredError, TokenMissingError):
            await self._auth.force_refresh()
            return await self._request(method, url, **kwargs)

    async def get(
        self,
        endpoint: str | None = None,
        *,
        url: str | None = None,
        params: dict | None = None,
        **kwargs,
    ) -> httpx.Response:
        """Send a GET request.

        Args:
            endpoint: Path appended to the client's base_url (or *url*).
            url: Override base URL for this request only.
            params: Query parameters. f=json is enforced (f=geojson is preserved).
            **kwargs: Forwarded to httpx.AsyncClient.request().
        """
        full_url = self._build_url(url, endpoint)
        effective_params = self._enforce_format(params or {})
        return await self._request_with_refresh(
            "GET", full_url, params=effective_params, **kwargs
        )

    async def post(
        self,
        endpoint: str | None = None,
        *,
        url: str | None = None,
        params: dict | None = None,
        data: dict | None = None,
        **kwargs,
    ) -> httpx.Response:
        """Send a POST request with a form-encoded body.

        Args:
            endpoint: Path appended to the client's base_url (or *url*).
            url: Override base URL for this request only.
            params: Query parameters (not form data).
            data: Form body. f=json is enforced here (f=geojson is preserved).
            **kwargs: Forwarded to httpx.AsyncClient.request() (e.g. files=).
        """
        full_url = self._build_url(url, endpoint)
        effective_data = self._enforce_format(data or {})
        return await self._request_with_refresh(
            "POST", full_url, params=params or {}, data=effective_data, **kwargs
        )

    async def aclose(self) -> None:
        """Close the underlying httpx.AsyncClient if it was created."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> ArchieClient:
        """Enter the async context manager."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the async context manager, closing the internal client."""
        await self.aclose()
