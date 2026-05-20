import httpx

from archie.auth.base import ArcGISAuth
from archie.errors import handle_esri_errors


class StaticTokenAuth(ArcGISAuth):
    def __init__(self, token: str) -> None:
        self._token = token

    async def get_token(self) -> str:
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
