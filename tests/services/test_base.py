import pytest

from archie.exceptions import InvalidServiceURL
from tests.helpers import SERVICE_PATH, MinimalService, make_response


class TestValidatePath:
    @pytest.mark.parametrize(
        "path,expected_path",
        [
            (SERVICE_PATH, SERVICE_PATH),
            (SERVICE_PATH + "/", SERVICE_PATH),
        ],
        ids=["valid_path", "trailing_slash_stripped"],
    )
    def test_valid_path(self, mock_client, path, expected_path):
        service = MinimalService(client=mock_client, service_path=path)

        assert service._service_path == expected_path

    @pytest.mark.parametrize(
        "path,match",
        [
            (
                "services/MyService/MapServer",
                "FeatureServer",
            ),
            (
                "services/MyService/MapServer",
                "MapServer",
            ),
        ],
        ids=["error_contains_expected_type", "error_contains_provided_path"],
    )
    def test_invalid_path_raises(self, mock_client, path, match):
        with pytest.raises(InvalidServiceURL, match=match):
            MinimalService(client=mock_client, service_path=path)


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
    async def test_calls_client_with_service_path(self, service, mock_client):
        mock_client.get.return_value = make_response({"type": "FeatureServer"})

        await service._get_service_metadata()

        mock_client.get.assert_called_once_with(endpoint=SERVICE_PATH)


class TestServicePropertyDefaults:
    @pytest.mark.parametrize(
        "method_name,expected_default",
        [
            ("crs", 3857),
            ("description", ""),
            ("max_record_count", 1000),
        ],
        ids=[
            "crs_defaults_to_3857",
            "description_defaults_to_empty",
            "max_record_count_defaults_to_1000",
        ],
    )
    @pytest.mark.anyio
    async def test_property_returns_default_when_missing(
        self, service, mock_client, method_name, expected_default
    ):
        mock_client.get.return_value = make_response({})

        result = await getattr(service, method_name)()

        assert result == expected_default


class TestRetrieveServiceProperties:
    @pytest.mark.anyio
    async def test_returns_max_record_count(self, service, mock_client):
        mock_client.get.return_value = make_response({"maxRecordCount": 2000})

        result = await service.max_record_count()

        assert result == 2000

    @pytest.mark.anyio
    async def test_returns_service_description(self, service, mock_client):
        mock_client.get.return_value = make_response(
            {"serviceDescription": "My service"}
        )

        result = await service.description()

        assert result == "My service"

    @pytest.mark.anyio
    async def test_returns_latest_wkid_from_spatial_reference(
        self, service, mock_client
    ):
        mock_client.get.return_value = make_response(
            {"spatialReference": {"latestWkid": 2876}}
        )

        result = await service.crs()

        assert result == 2876
