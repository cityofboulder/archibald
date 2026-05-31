import pytest

from archie.exceptions import InvalidServiceURL
from archie.services import FeatureService


class TestFeatureService:
    def test_accepts_feature_server_path(self, mock_client):
        service = FeatureService(
            client=mock_client, service_path="services/MyService/FeatureServer"
        )

        assert service._service_path == "services/MyService/FeatureServer"

    def test_rejects_non_feature_server_path(self, mock_client):
        with pytest.raises(InvalidServiceURL, match="FeatureServer"):
            FeatureService(
                client=mock_client, service_path="services/MyService/MapServer"
            )
