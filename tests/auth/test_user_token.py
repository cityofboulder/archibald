# tests/auth/test_user_token.py
from __future__ import annotations

import time
from unittest.mock import AsyncMock

import anyio
import httpx
import pytest

from archibald.auth.user_token import (
    ARCGIS_ONLINE_BASE_URL,
    EXPIRY_BUFFER_SECONDS,
    TOKEN_PATH,
    UserTokenAuth,
)
from archibald.exceptions import ConfigurationError, TokenRefreshError
from tests.helpers import inject_mock_client, make_response


def make_token_response(
    token: str = "test-token",
    expires: int | None = None,
) -> httpx.Response:
    """Create a mock ESRI generateToken response with a token and expiry in milliseconds."""
    expires = expires or int((time.time() + 3600) * 1000)
    return make_response({"token": token, "expires": expires})


def make_auth(
    username: str = "user",
    password: str = "pass",
    base_url: str = ARCGIS_ONLINE_BASE_URL,
    expiration: int = 60,
) -> UserTokenAuth:
    """Create a UserTokenAuth instance with sensible test defaults."""
    return UserTokenAuth(
        username=username,
        password=password,
        base_url=base_url,
        expiration=expiration,
    )


class TestUserTokenAuthInit:
    @pytest.mark.parametrize(
        "kwargs,match",
        [
            ({"username": "", "password": "pass"}, "username"),
            ({"username": "user", "password": ""}, "password"),
            ({"username": "user", "password": "pass", "expiration": 0}, "expiration"),
        ],
        ids=["empty_username", "empty_password", "invalid_expiration"],
    )
    def test_raises_on_invalid_init(self, kwargs, match):
        with pytest.raises(ConfigurationError, match=match):
            UserTokenAuth(**kwargs)

    @pytest.mark.parametrize(
        "base_url,expected",
        [
            (
                "https://myportal.example.com",
                "https://myportal.example.com" + TOKEN_PATH,
            ),
            (
                "https://myportal.example.com/",
                "https://myportal.example.com" + TOKEN_PATH,
            ),
            (ARCGIS_ONLINE_BASE_URL, ARCGIS_ONLINE_BASE_URL + TOKEN_PATH),
        ],
        ids=["no_trailing_slash", "trailing_slash", "arcgis_online_default"],
    )
    def test_token_url_construction(self, base_url, expected):
        auth = make_auth(base_url=base_url)

        assert auth._token_url == expected

    def test_password_stored_as_secret(self):
        auth = make_auth(password="supersecret")

        assert "supersecret" not in repr(auth._password)
        assert auth._password.get_secret_value() == "supersecret"

    def test_initial_token_is_none(self, auth):
        assert auth._token is None

    def test_initial_client_is_none(self, auth):
        assert auth._client is None

    def test_initial_lock_is_none(self, auth):
        assert auth._lock is None


class TestIsValid:
    def test_returns_false_when_token_is_none(self, auth):
        assert auth._is_valid() is False

    @pytest.mark.parametrize(
        "offset,expected",
        [
            (-1, False),
            (EXPIRY_BUFFER_SECONDS - 1, False),
            (EXPIRY_BUFFER_SECONDS + 60, True),
        ],
        ids=["expired", "within_buffer", "valid"],
    )
    def test_validity_based_on_expiry(self, auth, offset, expected):
        auth._token = "test-token"
        auth._expires_at = time.time() + offset

        assert auth._is_valid() is expected


class TestGetClient:
    @pytest.mark.anyio
    async def test_creates_client_on_first_call(self, auth):
        client = await auth._get_client()

        assert isinstance(client, httpx.AsyncClient)

    @pytest.mark.anyio
    async def test_returns_same_client_on_subsequent_calls(self, auth):
        first = await auth._get_client()
        second = await auth._get_client()

        assert first is second


class TestGetLock:
    @pytest.mark.anyio
    async def test_creates_lock_on_first_call(self, auth):
        lock = await auth._get_lock()

        assert lock is not None

    @pytest.mark.anyio
    async def test_returns_same_lock_on_subsequent_calls(self, auth):
        first = await auth._get_lock()
        second = await auth._get_lock()

        assert first is second


class TestFetchToken:
    @pytest.mark.anyio
    async def test_stores_token_from_response(self, auth, mocker):
        inject_mock_client(auth, make_token_response(token="fresh-token"), mocker)

        await auth._fetch_token()

        assert auth._token == "fresh-token"

    @pytest.mark.anyio
    async def test_stores_expiry_from_response(self, auth, mocker):
        expires_ms = int((time.time() + 3600) * 1000)
        inject_mock_client(auth, make_token_response(expires=expires_ms), mocker)

        await auth._fetch_token()

        assert auth._expires_at == pytest.approx(expires_ms / 1000.0)

    @pytest.mark.anyio
    async def test_raises_when_token_missing_from_response(self, auth, mocker):
        inject_mock_client(auth, make_response({"expires": 9999999999000}), mocker)

        with pytest.raises(TokenRefreshError, match="token"):
            await auth._fetch_token()

    @pytest.mark.anyio
    async def test_raises_when_expiry_missing_from_response(self, auth, mocker):
        inject_mock_client(auth, make_response({"token": "test-token"}), mocker)

        with pytest.raises(TokenRefreshError, match="expiry"):
            await auth._fetch_token()

    @pytest.mark.anyio
    async def test_raises_on_esri_error_envelope(self, auth, mocker):
        inject_mock_client(
            auth,
            make_response(
                {
                    "error": {
                        "code": 400,
                        "message": "Invalid credentials.",
                        "details": [],
                    }
                }
            ),
            mocker,
        )

        with pytest.raises(Exception):
            await auth._fetch_token()

    @pytest.mark.anyio
    async def test_raises_on_http_error(self, auth, mocker):
        mock_client: AsyncMock = mocker.AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.NetworkError("connection refused")
        auth._client = mock_client

        with pytest.raises(TokenRefreshError, match="Token request failed"):
            await auth._fetch_token()

    @pytest.mark.anyio
    async def test_posts_correct_parameters(self, mocker):
        auth = make_auth(username="testuser", expiration=120)
        mock_client = inject_mock_client(auth, make_token_response(), mocker)

        await auth._fetch_token()

        mock_client.post.assert_awaited_once_with(
            auth._token_url,
            data={
                "username": "testuser",
                "password": "pass",
                "client": "referer",
                "referer": ARCGIS_ONLINE_BASE_URL,
                "expiration": 120,
                "f": "json",
            },
        )


class TestGetToken:
    @pytest.mark.anyio
    async def test_fetches_token_when_none_cached(self, auth, mocker):
        inject_mock_client(auth, make_token_response(token="new-token"), mocker)

        token = await auth.get_token()

        assert token == "new-token"

    @pytest.mark.anyio
    async def test_returns_cached_token_when_valid(self, auth, mocker):
        auth._token = "cached-token"
        auth._expires_at = time.time() + EXPIRY_BUFFER_SECONDS + 60
        mock_client = inject_mock_client(auth, make_token_response(), mocker)

        token = await auth.get_token()

        assert token == "cached-token"
        mock_client.post.assert_not_awaited()

    @pytest.mark.anyio
    async def test_refreshes_token_when_expired(self, auth, mocker):
        auth._token = "old-token"
        auth._expires_at = time.time() - 1
        inject_mock_client(auth, make_token_response(token="refreshed-token"), mocker)

        token = await auth.get_token()

        assert token == "refreshed-token"

    @pytest.mark.anyio
    async def test_fetch_called_once_under_concurrent_requests(self, auth, mocker):
        inject_mock_client(auth, make_token_response(token="concurrent-token"), mocker)

        tokens = []

        async def call_get_token():
            token = await auth.get_token()
            tokens.append(token)

        async with anyio.create_task_group() as tg:
            for _ in range(10):
                tg.start_soon(call_get_token)

        assert all(t == "concurrent-token" for t in tokens)
        assert auth._client.post.await_count == 1


class TestForceRefresh:
    @pytest.mark.anyio
    async def test_fetches_new_token_even_when_valid(self, auth, mocker):
        auth._token = "old-token"
        auth._expires_at = time.time() + EXPIRY_BUFFER_SECONDS + 60
        mock_client = inject_mock_client(
            auth, make_token_response(token="forced-token"), mocker
        )

        await auth.force_refresh()

        assert auth._token == "forced-token"
        mock_client.post.assert_awaited_once()

    @pytest.mark.anyio
    async def test_resets_token_before_refresh(self, auth, mocker):
        auth._token = "old-token"
        auth._expires_at = time.time() + EXPIRY_BUFFER_SECONDS + 60
        inject_mock_client(auth, make_token_response(), mocker)

        await auth.force_refresh()

        assert auth._token != "old-token"


class TestAclose:
    @pytest.mark.anyio
    async def test_closes_and_nullifies_client(self, auth, mocker):
        mock_client = inject_mock_client(auth, make_token_response(), mocker)

        await auth.aclose()

        mock_client.aclose.assert_awaited_once()
        assert auth._client is None

    @pytest.mark.anyio
    async def test_context_manager_closes_client(self, auth, mocker):
        async with auth:
            mock_client = inject_mock_client(auth, make_token_response(), mocker)

        mock_client.aclose.assert_awaited_once()
