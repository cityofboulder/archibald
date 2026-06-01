"""Tests for MapLayer."""

import pytest

from archie.exceptions import InvalidServiceURL
from archie.services import MapLayer
from tests.helpers import MAP_LAYER_PATH


class TestMapLayer:
    def test_accepts_map_server_path(self, mock_client):
        layer = MapLayer(
            client=mock_client, service_path=MAP_LAYER_PATH, layer_id=0
        )

        assert layer._service_path == MAP_LAYER_PATH
        assert layer._layer_path == f"{MAP_LAYER_PATH}/0"

    def test_rejects_non_map_server_path(self, mock_client):
        with pytest.raises(InvalidServiceURL, match="MapServer"):
            MapLayer(
                client=mock_client,
                service_path="services/MyService/FeatureServer",
                layer_id=0,
            )
