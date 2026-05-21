from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock

from archie.client import ArchieClient
from archie.exceptions import ServiceError, TokenExpiredError, TokenMissingError
from tests.helpers import StaticTokenAuth, inject_mock_client, make_response


class TestBuildUrl:
    @pytest.mark.parametrize(
        "base_url, url, endpoint, expected",
        [
            (
                "https://example.com/arcgis",
                None,
                "FeatureServer/0/query",
                "https://example.com/arcgis/FeatureServer/0/query",
            ),
            (
                "https://example.com/arcgis",
                "https://other.com/service",
                "query",
                "https://other.com/service/query",
            ),
            (
                "https://example.com/arcgis/",
                None,
                "/FeatureServer/0",
                "https://example.com/arcgis/FeatureServer/0",
            ),
            (
                "https://example.com/arcgis",
                None,
                None,
                "https://example.com/arcgis",
            ),
        ],
        ids=[
            "endpoint-appended-to-base",
            "url-overrides-base",
            "slashes-normalised",
            "no-endpoint-returns-base",
        ],
    )
    def test_build_url(self, base_url, url, endpoint, expected):
        client = ArchieClient(base_url=base_url, auth=StaticTokenAuth("token"))

        result = client._build_url(url, endpoint)

        assert result == expected


class TestEnforceFormat:
    @pytest.mark.parametrize(
        "incoming, expected_f",
        [
            ({}, "json"),
            ({"f": "html"}, "json"),
            ({"f": "geojson"}, "geojson"),
        ],
        ids=["absent-gets-json", "other-overwritten-with-json", "geojson-preserved"],
    )
    def test_enforce_format_f_value(self, client, incoming, expected_f):
        result = client._enforce_format(incoming)

        assert result["f"] == expected_f

    def test_does_not_mutate_input(self, client):
        original = {"f": "html", "where": "1=1"}

        client._enforce_format(original)

        assert original == {"f": "html", "where": "1=1"}

    def test_preserves_other_params(self, client):
        result = client._enforce_format({"where": "1=1", "outFields": "*"})

        assert result["where"] == "1=1"
        assert result["outFields"] == "*"


class TestGet:
    @pytest.mark.anyio
    async def test_sends_get_method(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.get()

        assert mock.request.call_args[0][0] == "GET"

    @pytest.mark.anyio
    async def test_enforces_f_json_in_params(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.get(params={"where": "1=1"})

        assert mock.request.call_args[1]["params"]["f"] == "json"

    @pytest.mark.anyio
    async def test_preserves_geojson_in_params(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.get(params={"f": "geojson"})

        assert mock.request.call_args[1]["params"]["f"] == "geojson"

    @pytest.mark.anyio
    async def test_forwards_kwargs_to_httpx(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.get(timeout=30)

        assert mock.request.call_args[1]["timeout"] == 30

    @pytest.mark.anyio
    async def test_sends_to_constructed_url(self, mocker):
        client = ArchieClient(
            base_url="https://example.com/arcgis", auth=StaticTokenAuth("token")
        )
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.get(endpoint="FeatureServer/0/query")

        assert (
            mock.request.call_args[0][1]
            == "https://example.com/arcgis/FeatureServer/0/query"
        )


class TestPost:
    @pytest.mark.anyio
    async def test_sends_post_method(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.post()

        assert mock.request.call_args[0][0] == "POST"

    @pytest.mark.anyio
    async def test_enforces_f_json_in_data(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.post(data={"adds": "[]"})

        assert mock.request.call_args[1]["data"]["f"] == "json"

    @pytest.mark.anyio
    async def test_preserves_geojson_in_data(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.post(data={"f": "geojson"})

        assert mock.request.call_args[1]["data"]["f"] == "geojson"

    @pytest.mark.anyio
    async def test_query_params_are_separate_from_data(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.post(params={"token": "abc"}, data={"adds": "[]"})

        assert "token" in mock.request.call_args[1]["params"]
        assert "adds" in mock.request.call_args[1]["data"]

    @pytest.mark.anyio
    async def test_forwards_kwargs_to_httpx(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.post(timeout=30)

        assert mock.request.call_args[1]["timeout"] == 30


class TestRequest:
    @pytest.mark.anyio
    async def test_raises_on_http_error(self, client, mocker):
        inject_mock_client(client, make_response({}, status_code=404), mocker)

        with pytest.raises(httpx.HTTPStatusError):
            await client._request("GET", "https://example.com")

    @pytest.mark.anyio
    async def test_raises_esri_envelope_error(self, client, mocker):
        inject_mock_client(
            client,
            make_response(
                {"error": {"code": 500, "message": "Internal error", "details": []}}
            ),
            mocker,
        )

        with pytest.raises(ServiceError):
            await client._request("GET", "https://example.com")

    @pytest.mark.anyio
    async def test_returns_response_on_success(self, client, mocker):
        inject_mock_client(client, make_response({"result": "ok"}), mocker)

        response = await client._request("GET", "https://example.com")

        assert response.json() == {"result": "ok"}


class TestRequestWithRefresh:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "exc_class",
        [TokenExpiredError, TokenMissingError],
        ids=["498-token-expired", "499-token-missing"],
    )
    async def test_refreshes_and_retries_once_on_token_error(
        self, exc_class, client, mocker
    ):
        force_refresh = mocker.patch.object(
            client._auth, "force_refresh", new_callable=AsyncMock
        )
        request_mock = mocker.patch.object(
            client,
            "_request",
            new_callable=AsyncMock,
            side_effect=[exc_class(code=498, message="expired"), make_response({})],
        )

        await client._request_with_refresh("GET", "https://example.com")

        force_refresh.assert_awaited_once()
        assert request_mock.await_count == 2

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "exc_class",
        [TokenExpiredError, TokenMissingError],
        ids=["498-token-expired", "499-token-missing"],
    )
    async def test_propagates_if_retry_also_fails(self, exc_class, client, mocker):
        mocker.patch.object(client._auth, "force_refresh", new_callable=AsyncMock)
        mocker.patch.object(
            client,
            "_request",
            new_callable=AsyncMock,
            side_effect=exc_class(code=498, message="expired"),
        )

        with pytest.raises(exc_class):
            await client._request_with_refresh("GET", "https://example.com")


class TestLifecycle:
    def test_client_starts_as_none(self, client):
        assert client._client is None

    @pytest.mark.anyio
    async def test_client_created_on_first_request(self, client, mocker):
        inject_mock_client(client, make_response({}), mocker)

        await client.get()

        assert client._client is not None

    @pytest.mark.anyio
    async def test_aclose_closes_internal_client(self, client, mocker):
        mock = inject_mock_client(client, make_response({}), mocker)

        await client.aclose()

        mock.aclose.assert_awaited_once()

    @pytest.mark.anyio
    async def test_aclose_is_idempotent(self, client, mocker):
        inject_mock_client(client, make_response({}), mocker)

        await client.aclose()
        await client.aclose()

    @pytest.mark.anyio
    async def test_context_manager_closes_on_exit(self, mocker):
        async with ArchieClient(
            base_url="https://example.com", auth=StaticTokenAuth("token")
        ) as client:
            mock = inject_mock_client(client, make_response({}), mocker)

        mock.aclose.assert_awaited_once()
