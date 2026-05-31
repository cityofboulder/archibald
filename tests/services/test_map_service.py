import pytest

from archie.exceptions import InvalidServiceURL
from archie.services import MapService


class TestMapService:
    def test_accepts_map_server_path(self, mock_client):
        service = MapService(
            client=mock_client, service_path="services/MyService/MapServer"
        )

        assert service._service_path == "services/MyService/MapServer"

    def test_rejects_non_map_server_path(self, mock_client):
        with pytest.raises(InvalidServiceURL, match="MapServer"):
            MapService(
                client=mock_client, service_path="services/MyService/FeatureServer"
            )
