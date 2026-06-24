"""Tests for BaseLayer shared layer behavior."""

import pytest

from archibald.exceptions import InvalidParameterError, LayerCapabilityError
from archibald.models import FieldsResult
from archibald.services import FeatureLayer
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
    async def test_returns_response_json(self, base_layer, mock_client):
        metadata = {"objectIdField": "OBJECTID", "fields": []}
        mock_client.get.return_value = make_response(metadata)

        result = await base_layer._get_layer_metadata()

        assert result == metadata

    @pytest.mark.anyio
    async def test_caches_result_on_first_call(self, base_layer, mock_client):
        mock_client.get.return_value = make_response({"objectIdField": "OBJECTID"})

        await base_layer._get_layer_metadata()
        await base_layer._get_layer_metadata()

        mock_client.get.assert_called_once()

    @pytest.mark.anyio
    async def test_calls_client_with_layer_path(self, base_layer, mock_client):
        mock_client.get.return_value = make_response({})

        await base_layer._get_layer_metadata()

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
        self, base_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        result = await base_layer.objectid_field()

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
        self, base_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        result = await base_layer.globalid_field()

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
    async def test_supports_query(self, base_layer, mock_client, metadata, expected):
        mock_client.get.return_value = make_response(metadata)

        result = await base_layer.supports_query()

        assert result is expected


class TestSupportsAttachments:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({"hasAttachments": True}, True),
            ({"hasAttachments": False}, False),
            ({}, False),
        ],
        ids=[
            "has_attachments_true",
            "has_attachments_false",
            "has_attachments_missing",
        ],
    )
    @pytest.mark.anyio
    async def test_returns_expected_value(
        self, base_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        assert await base_layer.supports_attachments() is expected


class TestSupportsQueryAttachments:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({"advancedQueryCapabilities": {"supportsQueryAttachments": True}}, True),
            ({"advancedQueryCapabilities": {"supportsQueryAttachments": False}}, False),
            ({"advancedQueryCapabilities": {}}, False),
            ({}, False),
        ],
        ids=["supported", "explicitly_false", "key_absent", "no_advanced_caps"],
    )
    @pytest.mark.anyio
    async def test_returns_expected_value(
        self, base_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        assert await base_layer.supports_query_attachments() is expected


class TestSupportsQueryAttachmentsCountOnly:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            (
                {
                    "advancedQueryCapabilities": {
                        "supportsQueryAttachmentsCountOnly": True
                    }
                },
                True,
            ),
            ({"advancedQueryCapabilities": {}}, False),
            ({}, False),
        ],
        ids=["supported", "key_absent", "no_advanced_caps"],
    )
    @pytest.mark.anyio
    async def test_returns_expected_value(
        self, base_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        assert await base_layer.supports_query_attachments_count_only() is expected


class TestSupportsQueryAttachmentsOrderByFields:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            (
                {
                    "advancedQueryCapabilities": {
                        "supportsQueryAttachmentsOrderByFields": True
                    }
                },
                True,
            ),
            ({"advancedQueryCapabilities": {}}, False),
            ({}, False),
        ],
        ids=["supported", "key_absent", "no_advanced_capabilities"],
    )
    @pytest.mark.anyio
    async def test_returns_expected_value(
        self, base_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        assert await base_layer.supports_query_attachments_order_by_fields() is expected


class TestAttachmentFields:
    @pytest.mark.anyio
    async def test_returns_fields_result_from_attachment_fields_key(
        self, base_layer, mock_client, attachment_fields
    ):
        mock_client.get.return_value = make_response(
            {"attachmentFields": attachment_fields}
        )

        result = await base_layer.attachment_fields()

        assert isinstance(result, FieldsResult)
        assert result.names == [f["name"] for f in attachment_fields]

    @pytest.mark.anyio
    async def test_returns_empty_fields_result_when_key_absent(
        self, base_layer, mock_client
    ):
        mock_client.get.return_value = make_response({})

        result = await base_layer.attachment_fields()

        assert isinstance(result, FieldsResult)
        assert result.names == []


class TestAttachmentProperties:
    @pytest.mark.anyio
    async def test_returns_attachment_properties_from_metadata(
        self, base_layer, mock_client, attachment_properties
    ):
        mock_client.get.return_value = make_response(
            {"attachmentProperties": attachment_properties}
        )

        result = await base_layer.attachment_properties()

        assert result == attachment_properties

    @pytest.mark.anyio
    async def test_returns_empty_list_when_key_absent(self, base_layer, mock_client):
        mock_client.get.return_value = make_response({})

        result = await base_layer.attachment_properties()

        assert result == []


class TestFields:
    @pytest.mark.anyio
    async def test_returns_fields_result_with_names(self, base_layer, mock_client):
        mock_client.get.return_value = make_response(
            {
                "fields": [
                    {"name": "OBJECTID", "type": "esriFieldTypeOID", "editable": False},
                    {"name": "Name", "type": "esriFieldTypeString", "editable": True},
                ]
            }
        )

        result = await base_layer.fields()

        assert isinstance(result, FieldsResult)
        assert result.names == ["OBJECTID", "Name"]

    @pytest.mark.anyio
    async def test_returns_empty_fields_result_when_key_absent(
        self, base_layer, mock_client
    ):
        mock_client.get.return_value = make_response({})

        result = await base_layer.fields()

        assert isinstance(result, FieldsResult)
        assert result.names == []


class TestQuery:
    @pytest.mark.anyio
    async def test_raises_when_query_not_supported(self, base_layer, mock_client):
        mock_client.get.return_value = make_response({"capabilities": "Create,Update"})

        with pytest.raises(LayerCapabilityError, match="does not support query"):
            await base_layer.query()

    @pytest.mark.anyio
    async def test_delegates_all_args_to_query_op(
        self, base_layer, mocker, geojson_query_result
    ):
        mocker.patch.object(base_layer, "supports_query", return_value=True)
        mock_execute = mocker.patch.object(
            base_layer._query_op, "execute", return_value=geojson_query_result
        )

        result = await base_layer.query(
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
        self, base_layer, mocker, geojson_query_result
    ):
        mocker.patch.object(base_layer, "supports_query", return_value=True)
        mock_execute = mocker.patch.object(
            base_layer._query_op, "execute", return_value=geojson_query_result
        )

        await base_layer.query()

        mock_execute.assert_called_once_with(
            where="1=1",
            out_fields=None,
            return_geometry=True,
            out_sr=None,
        )

    @pytest.mark.anyio
    async def test_forwards_extra_kwargs_to_query_op(
        self, base_layer, mocker, geojson_query_result
    ):
        mocker.patch.object(base_layer, "supports_query", return_value=True)
        mock_execute = mocker.patch.object(
            base_layer._query_op, "execute", return_value=geojson_query_result
        )

        await base_layer.query(orderByFields="Name DESC")

        mock_execute.assert_called_once_with(
            where="1=1",
            out_fields=None,
            return_geometry=True,
            out_sr=None,
            orderByFields="Name DESC",
        )

    @pytest.mark.anyio
    async def test_sets_apply_coded_values_on_result_when_true(
        self, base_layer, mocker, geojson_query_result
    ):
        mocker.patch.object(base_layer, "supports_query", return_value=True)
        mocker.patch.object(
            base_layer._query_op, "execute", return_value=geojson_query_result
        )

        result = await base_layer.query(apply_coded_values=True)

        assert result.apply_coded_values is True

    @pytest.mark.anyio
    async def test_apply_coded_values_false_returns_result_unchanged(
        self, base_layer, mocker, geojson_query_result
    ):
        mocker.patch.object(base_layer, "supports_query", return_value=True)
        mocker.patch.object(
            base_layer._query_op, "execute", return_value=geojson_query_result
        )

        result = await base_layer.query(apply_coded_values=False)

        assert result is geojson_query_result


class TestQueryAttachments:
    @pytest.mark.anyio
    async def test_raises_when_query_attachments_not_supported(
        self, base_layer, mocker
    ):
        mocker.patch.object(
            base_layer, "supports_query_attachments", return_value=False
        )

        with pytest.raises(
            LayerCapabilityError, match="does not support querying attachments"
        ):
            await base_layer.query_attachments(object_ids=[1])

    @pytest.mark.anyio
    async def test_raises_when_count_only_unsupported(self, base_layer, mocker):
        mocker.patch.object(base_layer, "supports_query_attachments", return_value=True)
        mocker.patch.object(
            base_layer, "supports_query_attachments_count_only", return_value=False
        )

        with pytest.raises(
            LayerCapabilityError, match="does not support querying attachment counts"
        ):
            await base_layer.query_attachments(object_ids=[1], return_count_only=True)

    @pytest.mark.anyio
    async def test_propagates_invalid_parameter_error_from_op(
        self, base_layer, mock_client, mocker
    ):
        mocker.patch.object(base_layer, "supports_query_attachments", return_value=True)
        mocker.patch.object(base_layer, "attachment_properties", return_value=[])

        with pytest.raises(InvalidParameterError, match="at least one"):
            await base_layer.query_attachments()

        mock_client.get.assert_not_called()

    @pytest.mark.anyio
    async def test_delegates_all_args_to_op(
        self, base_layer, mocker, attachments_query_result
    ):
        mocker.patch.object(base_layer, "supports_query_attachments", return_value=True)
        mock_execute = mocker.patch.object(
            base_layer._query_attachments_op,
            "execute",
            return_value=attachments_query_result,
        )

        result = await base_layer.query_attachments(
            object_ids=[1, 2], attachment_types=["jpeg"], return_url=True
        )

        mock_execute.assert_called_once_with(
            object_ids=[1, 2],
            global_ids=None,
            definition_expression=None,
            attachments_definition_expression=None,
            attachment_types=["jpeg"],
            size=None,
            keywords=None,
            return_url=True,
            return_metadata=None,
            order_by_fields=None,
            result_offset=None,
            result_record_count=None,
            return_count_only=False,
        )
        assert result is attachments_query_result

    @pytest.mark.anyio
    async def test_forwards_extra_kwargs_to_op(
        self, base_layer, mocker, attachments_query_result
    ):
        mocker.patch.object(base_layer, "supports_query_attachments", return_value=True)
        mock_execute = mocker.patch.object(
            base_layer._query_attachments_op,
            "execute",
            return_value=attachments_query_result,
        )

        await base_layer.query_attachments(object_ids=[1], cacheHint="true")

        assert mock_execute.call_args.kwargs["cacheHint"] == "true"
