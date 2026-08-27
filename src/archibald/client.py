from __future__ import annotations

import anyio
import httpx

from archibald.auth import ArcGISAuth
from archibald.errors import handle_esri_errors
from archibald.exceptions import InvalidServiceURL, TokenExpiredError, TokenMissingError


class ArchieClient:
    """Async HTTP client for ESRI REST APIs.

    Manages an internal httpx.AsyncClient with lazy initialization. Enforces
    f=json on all requests (preserving f=geojson when explicitly set), handles
    token refresh on 498/499 responses, and raises for HTTP-level errors before
    ESRI envelope errors are inspected. Bounds the number of concurrent
    in-flight requests so fan-out callers (batched applyEdits, paged query,
    bulk attachment operations) can't overrun the connection pool.

    Can be used as an async context manager or instantiated directly; in the
    latter case call aclose() manually when done.
    """

    def __init__(
        self,
        base_url: str,
        auth: ArcGISAuth,
        timeout: float | httpx.Timeout | None = 60.0,
        max_concurrent_requests: int = 20,
    ) -> None:
        """Construct an ArchieClient.

        Args:
            base_url: Base URL ending in 'rest/services'.
            auth: Authentication handler for token injection.
            timeout: Default request timeout in seconds, an explicit
                httpx.Timeout for fine-grained control, or None for no timeout.
                Applied to all requests unless overridden per-request via kwargs.
            max_concurrent_requests: Maximum number of requests in flight at
                once, shared across all callers (query paging, attachment
                fan-out, applyEdits batching, ...). Defaults to 20, matching
                httpx's own max_keepalive_connections default — comfortably
                under its max_connections=100 pool ceiling, so this cannot
                reproduce a PoolTimeout regardless of how many batches/pages/
                attachments a caller fans out. Raise or lower it based on what
                the target ArcGIS Server instance's own service concurrency
                is known to tolerate.
        """
        self._base_url = self._validate_base_url(base_url.rstrip("/"))
        self._auth = auth
        self._timeout = timeout
        self._limiter = anyio.CapacityLimiter(max_concurrent_requests)
        self._client: httpx.AsyncClient | None = None

    def _validate_base_url(self, url: str) -> str:
        """Validate that url ends with 'rest/services' and return it.

        Raises:
            InvalidServiceURL: If the url does not end with 'rest/services'.
        """
        if not url.endswith("rest/services"):
            raise InvalidServiceURL(
                f"Expected base_url ending in 'rest/services', got: {url}"
            )
        return url

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the shared httpx.AsyncClient, creating it lazily on first call."""
        if self._client is None:
            self._client = httpx.AsyncClient(auth=self._auth, timeout=self._timeout)
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
        The network call is gated by self._limiter so no more than
        max_concurrent_requests are in flight at once, regardless of how many
        callers fan out concurrently. Raises for HTTP-level errors before
        returning; @handle_esri_errors then inspects the body for ESRI
        envelope errors.
        """
        client = await self._get_client()
        async with self._limiter:
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
