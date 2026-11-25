import pytest

from archibald.exceptions import InvalidServiceURL
from archibald.services import GeocodeService
from tests.helpers import GEOCODE_SERVICE_PATH, make_geocode_metadata, make_response


class TestGeocodeServicePath:
    def test_accepts_path_when_it_ends_in_geocode_server(self, mock_client):
        service = GeocodeService(client=mock_client, service_path=GEOCODE_SERVICE_PATH)

        assert service._service_path == GEOCODE_SERVICE_PATH

    def test_raises_when_path_is_not_a_geocode_server(self, mock_client):
        with pytest.raises(InvalidServiceURL, match="GeocodeServer"):
            GeocodeService(
                client=mock_client, service_path="services/MyService/MapServer"
            )


class TestGeocodeServiceMaxBatchSize:
    @pytest.mark.parametrize(
        "locator_properties, expected",
        [
            ({"MaxBatchSize": 500}, 500),
            ({"MaxBatchSize": "1000"}, 1000),
            ({}, None),
            (None, None),
        ],
        ids=["int", "string", "key-absent", "no-locator-properties"],
    )
    @pytest.mark.anyio
    async def test_returns_expected_size_when_metadata_given(
        self, geocode_service, mock_client, locator_properties, expected
    ):
        mock_client.get.return_value = make_response(
            make_geocode_metadata(locator_properties=locator_properties)
        )

        result = await geocode_service.max_batch_size()

        assert result == expected


class TestGeocodeServiceCapabilities:
    @pytest.mark.parametrize(
        "capabilities, expected",
        [
            ("Geocode,ReverseGeocode,Suggest", (True, True, True)),
            ("Geocode,ReverseGeocode", (True, True, False)),
            ("ReverseGeocode", (False, True, False)),
            (" geocode , SUGGEST ", (True, False, True)),
            ("", (False, False, False)),
            (None, (False, False, False)),
        ],
        ids=[
            "all",
            "no-suggest",
            "reverse-only",
            "spacing-and-case",
            "empty",
            "key-absent",
        ],
    )
    @pytest.mark.anyio
    async def test_reports_advertised_operations_when_metadata_given(
        self, geocode_service, mock_client, capabilities, expected
    ):
        mock_client.get.return_value = make_response(
            make_geocode_metadata(capabilities=capabilities)
        )

        result = (
            await geocode_service.supports_geocode(),
            await geocode_service.supports_reverse_geocode(),
            await geocode_service.supports_suggest(),
        )

        assert result == expected

    @pytest.mark.parametrize(
        "capabilities, locator_properties, expected",
        [
            ("Geocode,ReverseGeocode", {"MaxBatchSize": 500}, True),
            ("Geocode,ReverseGeocode", {"MaxBatchSize": "1000"}, True),
            ("Geocode,ReverseGeocode", {"MaxBatchSize": 0}, False),
            ("Geocode,ReverseGeocode", {}, False),
            ("ReverseGeocode", {"MaxBatchSize": 500}, False),
        ],
        ids=[
            "max-batch-size",
            "string-max-batch-size",
            "zero-max-batch-size",
            "no-max-batch-size",
            "geocode-not-advertised",
        ],
    )
    @pytest.mark.anyio
    async def test_reports_batch_support_when_metadata_given(
        self, geocode_service, mock_client, capabilities, locator_properties, expected
    ):
        mock_client.get.return_value = make_response(
            make_geocode_metadata(
                capabilities=capabilities, locator_properties=locator_properties
            )
        )

        result = await geocode_service.supports_batch_geocode()

        assert result is expected
