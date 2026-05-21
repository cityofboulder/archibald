# tests/helpers.py
from __future__ import annotations

import httpx
from pytest_mock import MockerFixture
from unittest.mock import AsyncMock

from archie.auth.base import ArcGISAuth
from archie.auth.user_token import UserTokenAuth
from archie.errors import handle_esri_errors


class StaticTokenAuth(ArcGISAuth):
    """Minimal ArcGISAuth implementation for testing. Returns a static token with no I/O."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def get_token(self) -> str:
        """Return the static token provided at construction."""
        return self._token


def make_response(body: dict) -> httpx.Response:
    """Create a minimal httpx.Response with a JSON body for use in tests."""
    return httpx.Response(200, json=body)


def make_decorated_call(body: dict):
    """Return a handle_esri_errors-decorated coroutine that responds with body."""

    @handle_esri_errors
    async def _call():
        return make_response(body)

    return _call


def inject_mock_client(
    target: UserTokenAuth,
    response: httpx.Response,
    mocker: MockerFixture,
) -> AsyncMock:
    """Inject a mock httpx.AsyncClient onto target._client that returns response on post().

    Returns the mock client so callers can make assertions against it.
    """
    mock_client = mocker.AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = response
    target._client = mock_client
    return mock_client
