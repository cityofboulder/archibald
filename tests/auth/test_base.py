import pytest
import httpx

from archibald.auth import ArcGISAuth

from tests.helpers import StaticTokenAuth


class TestArcGISAuthContract:
    def test_cannot_instantiate_without_get_token(self):
        class IncompleteAuth(ArcGISAuth):
            async def force_refresh(self) -> None:
                pass

        with pytest.raises(TypeError):
            IncompleteAuth()  # type: ignore

    def test_cannot_instantiate_without_force_refresh(self):
        class IncompleteAuth(ArcGISAuth):
            async def get_token(self) -> str:
                return "token"

        with pytest.raises(TypeError):
            IncompleteAuth()  # type: ignore


class TestAsyncAuthFlow:
    @pytest.mark.anyio
    async def test_injects_bearer_token_header(self):
        auth = StaticTokenAuth(token="test-token")
        request = httpx.Request("GET", "https://example.com")

        flow = auth.async_auth_flow(request)
        await flow.asend(None)  # type: ignore

        assert request.headers["Authorization"] == "Bearer test-token"

    @pytest.mark.anyio
    async def test_yields_the_request(self):
        auth = StaticTokenAuth(token="test-token")
        request = httpx.Request("GET", "https://example.com")

        flow = auth.async_auth_flow(request)
        yielded = await flow.asend(None)  # type: ignore

        assert yielded is request


class TestContextManager:
    @pytest.mark.anyio
    async def test_aenter_returns_self(self):
        auth = StaticTokenAuth(token="test-token")

        result = await auth.__aenter__()

        assert result is auth

    @pytest.mark.anyio
    async def test_aexit_calls_aclose(self, mocker):
        auth = StaticTokenAuth(token="test-token")
        mock_aclose = mocker.patch.object(auth, "aclose")

        await auth.__aexit__(None, None, None)

        mock_aclose.assert_awaited_once()

    @pytest.mark.anyio
    async def test_aclose_is_noop(self):
        auth = StaticTokenAuth(token="test-token")

        await auth.aclose()

    @pytest.mark.anyio
    async def test_context_manager_yields_self(self):
        async with StaticTokenAuth(token="test-token") as auth:
            assert isinstance(auth, StaticTokenAuth)
