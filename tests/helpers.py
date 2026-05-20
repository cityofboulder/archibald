import httpx

from archie.errors import handle_esri_errors


def make_response(body: dict) -> httpx.Response:
    """Create a minimal httpx.Response with a JSON body for use in tests."""
    return httpx.Response(200, json=body)


def make_decorated_call(body: dict):
    """Return a handle_esri_errors-decorated coroutine that responds with body."""

    @handle_esri_errors
    async def _call():
        return make_response(body)

    return _call
