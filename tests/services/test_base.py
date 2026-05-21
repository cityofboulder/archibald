import pytest

from archie.exceptions import InvalidServiceURL
from tests.helpers import BASE_URL, MinimalService, make_response


class TestValidateURL:
    @pytest.mark.parametrize(
        "url,expected_url",
        [
            (BASE_URL, BASE_URL),
            (BASE_URL + "/", BASE_URL),
        ],
        ids=["valid_url", "trailing_slash_stripped"],
    )
    def test_valid_url(self, mock_client, url, expected_url):
        service = MinimalService(client=mock_client, url=url)

        assert service._url == expected_url

    @pytest.mark.parametrize(
        "url,match",
        [
            (
                "https://example.com/arcgis/rest/services/MyService/MapServer",
                "FeatureServer",
            ),
            (
                "https://example.com/arcgis/rest/services/MyService/MapServer",
                "MapServer",
            ),
        ],
        ids=["error_contains_expected_type", "error_contains_provided_url"],
    )
    def test_invalid_url_raises(self, mock_client, url, match):
        with pytest.raises(InvalidServiceURL, match=match):
            MinimalService(client=mock_client, url=url)


class TestGetServiceMetadata:
    @pytest.mark.anyio
    async def test_returns_response_json(self, service, mock_client):
        metadata = {"type": "FeatureServer", "layers": []}
        mock_client.get.return_value = make_response(metadata)

        result = await service._get_service_metadata()

        assert result == metadata

    @pytest.mark.anyio
    async def test_caches_result_on_first_call(self, service, mock_client):
        mock_client.get.return_value = make_response({"type": "FeatureServer"})

        await service._get_service_metadata()
        await service._get_service_metadata()

        mock_client.get.assert_called_once()

    @pytest.mark.anyio
    async def test_calls_client_with_service_url(self, service, mock_client):
        mock_client.get.return_value = make_response({"type": "FeatureServer"})

        await service._get_service_metadata()

        mock_client.get.assert_called_once_with(url=BASE_URL)
