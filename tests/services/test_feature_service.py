import pytest

from tests.helpers import make_response


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
        self, feature_service, mock_client, method_name, expected_default
    ):
        mock_client.get.return_value = make_response({})

        method = getattr(feature_service, method_name)
        result = await method()

        assert result == expected_default


class TestRetrieveServiceProperties:
    @pytest.mark.anyio
    async def test_returns_max_record_count(self, feature_service, mock_client):
        mock_client.get.return_value = make_response({"maxRecordCount": 2000})

        result = await feature_service.max_record_count()

        assert result == 2000

    @pytest.mark.anyio
    async def test_returns_service_description(self, feature_service, mock_client):
        mock_client.get.return_value = make_response(
            {"serviceDescription": "My service"}
        )

        result = await feature_service.description()

        assert result == "My service"

    @pytest.mark.anyio
    async def test_returns_latest_wkid_from_spatial_reference(
        self, feature_service, mock_client
    ):
        mock_client.get.return_value = make_response(
            {"spatialReference": {"latestWkid": 2876}}
        )

        result = await feature_service.crs()

        assert result == 2876
