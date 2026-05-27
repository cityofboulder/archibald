"""Tests for FeatureLayer service."""

import pytest

from archie.models.fields_result import FieldsResult
from archie.services.feature_layer import FeatureLayer
from tests.helpers import SERVICE_PATH, make_response


class TestInit:
    @pytest.mark.parametrize(
        "layer_id,expected_path",
        [
            (0, f"{SERVICE_PATH}/0"),
            (1, f"{SERVICE_PATH}/1"),
        ],
        ids=["layer_0", "layer_1"],
    )
    def test_layer_path_set_on_init(self, mock_client, layer_id, expected_path):
        layer = FeatureLayer(
            client=mock_client, service_path=SERVICE_PATH, layer_id=layer_id
        )

        assert layer._layer_path == expected_path


class TestGetLayerMetadata:
    @pytest.mark.anyio
    async def test_returns_response_json(self, feature_layer, mock_client):
        metadata = {"objectIdField": "OBJECTID", "fields": []}
        mock_client.get.return_value = make_response(metadata)

        result = await feature_layer._get_layer_metadata()

        assert result == metadata

    @pytest.mark.anyio
    async def test_caches_result_on_first_call(self, feature_layer, mock_client):
        mock_client.get.return_value = make_response({"objectIdField": "OBJECTID"})

        await feature_layer._get_layer_metadata()
        await feature_layer._get_layer_metadata()

        mock_client.get.assert_called_once()

    @pytest.mark.anyio
    async def test_calls_client_with_layer_path(self, feature_layer, mock_client):
        mock_client.get.return_value = make_response({})

        await feature_layer._get_layer_metadata()

        mock_client.get.assert_called_once_with(endpoint=f"{SERVICE_PATH}/0")


class TestObjectidField:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({}, "OBJECTID"),
            ({"objectIdField": "FID"}, "FID"),
        ],
        ids=["default_when_absent", "returns_custom_name"],
    )
    @pytest.mark.anyio
    async def test_returns_objectid_field(
        self, feature_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        result = await feature_layer.objectid_field()

        assert result == expected


class TestGlobalidField:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({}, None),
            ({"globalIdField": "GlobalID"}, "GlobalID"),
        ],
        ids=["none_when_absent", "returns_field_name"],
    )
    @pytest.mark.anyio
    async def test_returns_globalid_field(
        self, feature_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        result = await feature_layer.globalid_field()

        assert result == expected


class TestSupportsQuery:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({"capabilities": "Query,Create"}, True),
            ({"capabilities": "QUERY"}, True),
            ({"capabilities": "Create,Update"}, False),
            ({}, False),
        ],
        ids=[
            "query_present",
            "query_uppercase",
            "query_absent",
            "capabilities_key_missing",
        ],
    )
    @pytest.mark.anyio
    async def test_supports_query(self, feature_layer, mock_client, metadata, expected):
        mock_client.get.return_value = make_response(metadata)

        result = await feature_layer.supports_query()

        assert result is expected


class TestFields:
    @pytest.mark.anyio
    async def test_returns_fields_result_with_names(self, feature_layer, mock_client):
        mock_client.get.return_value = make_response(
            {
                "fields": [
                    {"name": "OBJECTID", "type": "esriFieldTypeOID", "editable": False},
                    {"name": "Name", "type": "esriFieldTypeString", "editable": True},
                ]
            }
        )

        result = await feature_layer.fields()

        assert isinstance(result, FieldsResult)
        assert result.names() == ["OBJECTID", "Name"]

    @pytest.mark.anyio
    async def test_returns_empty_fields_result_when_key_absent(
        self, feature_layer, mock_client
    ):
        mock_client.get.return_value = make_response({})

        result = await feature_layer.fields()

        assert isinstance(result, FieldsResult)
        assert result.names() == []


class TestQuery:
    @pytest.mark.anyio
    async def test_raises_when_query_not_supported(self, feature_layer, mock_client):
        mock_client.get.return_value = make_response({"capabilities": "Create,Update"})

        with pytest.raises(ValueError, match="does not support query"):
            await feature_layer.query()

    @pytest.mark.anyio
    async def test_delegates_all_args_to_query_op(
        self, feature_layer, mocker, geojson_query_result
    ):
        mocker.patch.object(feature_layer, "supports_query", return_value=True)
        mock_execute = mocker.patch.object(
            feature_layer._query_op, "execute", return_value=geojson_query_result
        )

        result = await feature_layer.query(
            where="Status = 1",
            out_fields=["OBJECTID"],
            return_geometry=True,
            out_sr=4326,
        )

        mock_execute.assert_called_once_with(
            where="Status = 1",
            out_fields=["OBJECTID"],
            return_geometry=True,
            out_sr=4326,
        )
        assert result is geojson_query_result

    @pytest.mark.anyio
    async def test_default_args_forwarded_to_query_op(
        self, feature_layer, mocker, geojson_query_result
    ):
        mocker.patch.object(feature_layer, "supports_query", return_value=True)
        mock_execute = mocker.patch.object(
            feature_layer._query_op, "execute", return_value=geojson_query_result
        )

        await feature_layer.query()

        mock_execute.assert_called_once_with(
            where="1=1",
            out_fields=None,
            return_geometry=True,
            out_sr=None,
        )

    @pytest.mark.anyio
    async def test_forwards_extra_kwargs_to_query_op(
        self, feature_layer, mocker, geojson_query_result
    ):
        mocker.patch.object(feature_layer, "supports_query", return_value=True)
        mock_execute = mocker.patch.object(
            feature_layer._query_op, "execute", return_value=geojson_query_result
        )

        await feature_layer.query(orderByFields="Name DESC")

        mock_execute.assert_called_once_with(
            where="1=1",
            out_fields=None,
            return_geometry=True,
            out_sr=None,
            orderByFields="Name DESC",
        )
