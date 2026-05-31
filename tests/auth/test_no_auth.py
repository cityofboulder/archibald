import pytest
import httpx

from archie.auth import NoAuth


@pytest.fixture
def auth():
    return NoAuth()


class TestAsyncAuthFlow:
    @pytest.mark.anyio
    async def test_does_not_inject_authorization_header(self, auth):
        request = httpx.Request("GET", "https://example.com")

        flow = auth.async_auth_flow(request)
        await flow.asend(None)  # type: ignore

        assert "Authorization" not in request.headers

    @pytest.mark.anyio
    async def test_yields_the_request(self, auth):
        request = httpx.Request("GET", "https://example.com")

        flow = auth.async_auth_flow(request)
        yielded = await flow.asend(None)  # type: ignore

        assert yielded is request


class TestGetToken:
    @pytest.mark.anyio
    async def test_returns_empty_string(self, auth):
        result = await auth.get_token()

        assert result == ""


class TestForceRefresh:
    @pytest.mark.anyio
    async def test_is_noop(self, auth):
        await auth.force_refresh()


class TestContextManager:
    @pytest.mark.anyio
    async def test_yields_self(self):
        async with NoAuth() as auth:
            assert isinstance(auth, NoAuth)
