from __future__ import annotations

import time

import httpx
from anyio import Lock
from pydantic import SecretStr

from archibald.auth.base import ArcGISAuth
from archibald.errors import handle_esri_errors
from archibald.exceptions import ConfigurationError, TokenRefreshError

ARCGIS_ONLINE_BASE_URL = "https://www.arcgis.com"
TOKEN_PATH = "/sharing/rest/generateToken"
EXPIRY_BUFFER_SECONDS = 60


class UserTokenAuth(ArcGISAuth):
    """Authenticates with an ESRI REST API using the generateToken endpoint.

    Lazily initialises an internal httpx.AsyncClient on the first request.
    Tokens are cached and proactively refreshed before expiry. Safe for use
    across concurrent requests via an anyio.Lock.

    Args:
        username: ESRI account username.
        password: ESRI account password. Stored internally as a SecretStr.
        base_url: Base URL of the portal. Defaults to ArcGIS Online.
        expiration: Token lifetime in minutes. Defaults to 60.
    """

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str = ARCGIS_ONLINE_BASE_URL,
        expiration: int = 60,
    ) -> None:
        if not username:
            raise ConfigurationError("username must not be empty.")
        if not password:
            raise ConfigurationError("password must not be empty.")
        if expiration < 1:
            raise ConfigurationError("expiration must be at least 1 minute.")

        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = SecretStr(password)
        self._token_url = self._base_url + TOKEN_PATH
        self._expiration = expiration

        self._token: str | None = None
        self._expires_at: float = 0.0
        self._client: httpx.AsyncClient | None = None
        self._lock: Lock | None = None

    def _is_valid(self) -> bool:
        """Return True if the cached token exists and is not close to expiry."""
        return (
            self._token is not None
            and time.time() < self._expires_at - EXPIRY_BUFFER_SECONDS
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the internal httpx.AsyncClient, creating it if necessary."""
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def _get_lock(self) -> Lock:
        """Return the anyio.Lock, creating it if necessary."""
        if self._lock is None:
            self._lock = Lock()
        return self._lock

    @handle_esri_errors
    async def _request_token(self) -> httpx.Response:
        """POST to the generateToken endpoint and return the raw response.

        Raises:
            TokenRefreshError: If the HTTP request itself fails.
        """
        client = await self._get_client()
        try:
            return await client.post(
                self._token_url,
                data={
                    "username": self._username,
                    "password": self._password.get_secret_value(),
                    "client": "referer",
                    "referer": self._base_url,
                    "expiration": self._expiration,
                    "f": "json",
                },
            )
        except httpx.HTTPError as exc:
            raise TokenRefreshError(f"Token request failed: {exc}") from exc

    async def _fetch_token(self) -> None:
        """Request a new token and store it along with its expiry.

        Raises:
            TokenRefreshError: If the response does not contain a valid token
                or expiry.
        """
        response = await self._request_token()
        body = response.json()

        token = body.get("token")
        expires = body.get("expires")

        if not token:
            raise TokenRefreshError("Token endpoint response did not contain a token.")
        if expires is None:
            raise TokenRefreshError(
                "Token endpoint response did not contain an expiry."
            )

        self._token = token
        self._expires_at = expires / 1000.0

    async def get_token(self) -> str:
        """Return a valid token, refreshing if necessary.

        Uses a double-checked lock to prevent concurrent refresh races.

        Raises:
            TokenRefreshError: If the token cannot be obtained or refreshed.
        """
        if self._is_valid():
            return self._token  # type: ignore[return-value]

        lock = await self._get_lock()
        async with lock:
            if not self._is_valid():
                await self._fetch_token()

        return self._token  # type: ignore[return-value]

    async def force_refresh(self) -> None:
        """Invalidate the cached token and fetch a new one immediately.

        Intended for use by the client layer when a 498 or 499 is received
        despite a nominally valid token.

        Raises:
            TokenRefreshError: If the token cannot be refreshed.
        """
        self._token = None
        self._expires_at = 0.0
        await self.get_token()

    async def aclose(self) -> None:
        """Close the internal httpx.AsyncClient if one was created."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
