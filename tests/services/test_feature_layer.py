"""Tests for FeatureLayer service."""

import pandas as pd
import pytest

from archie.models import FieldsResult
from archie.services import FeatureLayer
from tests.helpers import SERVICE_PATH, make_apply_edits_result, make_response


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
        assert result.names == ["OBJECTID", "Name"]

    @pytest.mark.anyio
    async def test_returns_empty_fields_result_when_key_absent(
        self, feature_layer, mock_client
    ):
        mock_client.get.return_value = make_response({})

        result = await feature_layer.fields()

        assert isinstance(result, FieldsResult)
        assert result.names == []


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


class TestValidateKeyFields:
    @pytest.mark.parametrize(
        "key_fields,df,match",
        [
            ([], pd.DataFrame({"Name": ["Alice"]}), "must not be empty"),
            (["Nope"], pd.DataFrame({"Name": ["Alice"]}), "'Nope'"),
            (
                ["Name"],
                pd.DataFrame({"Name": ["Alice", "Alice"]}),
                "do not uniquely identify",
            ),
            (
                ["Name", "Status"],
                pd.DataFrame(
                    {
                        "Name": ["Alice", "Alice"],
                        "Status": ["Active", "Active"],
                    }
                ),
                "do not uniquely identify",
            ),
        ],
        ids=[
            "empty_key_fields",
            "unknown_column",
            "duplicate_key",
            "duplicate_composite_key",
        ],
    )
    def test_raises_on_invalid_key_fields(self, key_fields, df, match):
        with pytest.raises(ValueError, match=match):
            FeatureLayer._validate_key_fields(df, key_fields)

    def test_passes_for_valid_unique_keys(self):
        df = pd.DataFrame({"Name": ["Alice", "Bob"]})
        FeatureLayer._validate_key_fields(df, ["Name"])


class TestApplyEdits:
    @pytest.mark.anyio
    async def test_raises_when_not_supported(self, feature_layer, mocker):
        mocker.patch.object(feature_layer, "supports_apply_edits", return_value=False)

        with pytest.raises(ValueError, match="does not support edit operations"):
            await feature_layer.apply_edits()

    @pytest.mark.anyio
    async def test_delegates_to_apply_edits_op(self, feature_layer, mocker):
        df = pd.DataFrame({"Name": ["Alice"]})
        expected = make_apply_edits_result()
        mocker.patch.object(feature_layer, "supports_apply_edits", return_value=True)
        mock_execute = mocker.patch.object(
            feature_layer._apply_edits_op, "execute", return_value=expected
        )

        result = await feature_layer.apply_edits(adds=df, rollback_on_failure=True)

        mock_execute.assert_called_once_with(
            adds=df, updates=None, deletes=None, rollback_on_failure=True
        )
        assert result is expected


class TestAppend:
    @pytest.mark.anyio
    async def test_delegates_to_apply_edits_with_adds(self, feature_layer, mocker):
        df = pd.DataFrame({"Name": ["Alice"]})
        expected = make_apply_edits_result()
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=expected
        )

        result = await feature_layer.append(df)

        mock_apply.assert_called_once_with(adds=df)
        assert result is expected


class TestUpsert:
    @pytest.mark.anyio
    async def test_routes_adds_and_updates(self, feature_layer, mocker):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        updates_df = pd.DataFrame({"Name": ["Bob"], "OBJECTID": [1]})
        mocker.patch.object(
            feature_layer, "_diff", return_value=(adds_df, updates_df, [])
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await feature_layer.upsert(adds_df, ["Name"])

        mock_apply.assert_called_once_with(adds=adds_df, updates=updates_df)

    @pytest.mark.parametrize(
        "adds_rows,updates_rows",
        [
            ([], [{"Name": "Bob", "OBJECTID": 1}]),
            ([{"Name": "Alice"}], []),
        ],
        ids=["empty_adds", "empty_updates"],
    )
    @pytest.mark.anyio
    async def test_passes_none_for_empty_partition(
        self, feature_layer, mocker, adds_rows, updates_rows
    ):
        adds_df = pd.DataFrame(adds_rows) if adds_rows else pd.DataFrame(columns=["Name"])
        updates_df = pd.DataFrame(updates_rows) if updates_rows else pd.DataFrame(columns=["Name"])
        mocker.patch.object(feature_layer, "_diff", return_value=(adds_df, updates_df, []))
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await feature_layer.upsert(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=None if adds_df.empty else adds_df,
            updates=None if updates_df.empty else updates_df,
        )


class TestSync:
    @pytest.mark.anyio
    async def test_routes_all_three(self, feature_layer, mocker):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        updates_df = pd.DataFrame({"Name": ["Bob"], "OBJECTID": [1]})
        expected = make_apply_edits_result()
        mocker.patch.object(
            feature_layer, "_diff", return_value=(adds_df, updates_df, [2, 3])
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=expected
        )

        await feature_layer.sync(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=adds_df, updates=updates_df, deletes=[2, 3]
        )

    @pytest.mark.anyio
    async def test_passes_none_for_empty_deletes(self, feature_layer, mocker):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        updates_df = pd.DataFrame({"Name": ["Bob"], "OBJECTID": [1]})
        mocker.patch.object(
            feature_layer, "_diff", return_value=(adds_df, updates_df, [])
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await feature_layer.sync(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=adds_df, updates=updates_df, deletes=None
        )


class TestDiff:
    @pytest.mark.anyio
    async def test_new_rows_are_adds(self, feature_layer, mocker):
        input_df = pd.DataFrame({"Name": ["Alice", "Bob"]})
        existing_df = pd.DataFrame(columns=["OBJECTID", "Name"])
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, delete_oids = await feature_layer._diff(input_df, ["Name"])

        assert sorted(adds["Name"].tolist()) == ["Alice", "Bob"]
        assert updates.empty
        assert delete_oids == []

    @pytest.mark.anyio
    async def test_matched_rows_become_updates_with_objectid(
        self, feature_layer, mocker
    ):
        input_df = pd.DataFrame({"Name": ["Alice"]})
        existing_df = pd.DataFrame({"OBJECTID": [5], "Name": ["Alice"]})
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, delete_oids = await feature_layer._diff(input_df, ["Name"])

        assert adds.empty
        assert updates["Name"].tolist() == ["Alice"]
        assert updates["OBJECTID"].tolist() == [5]
        assert delete_oids == []

    @pytest.mark.anyio
    async def test_unmatched_existing_rows_are_deletes(self, feature_layer, mocker):
        input_df = pd.DataFrame({"Name": ["Alice"]})
        existing_df = pd.DataFrame({"OBJECTID": [1, 2], "Name": ["Alice", "Bob"]})
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, delete_oids = await feature_layer._diff(input_df, ["Name"])

        assert adds.empty
        assert updates["Name"].tolist() == ["Alice"]
        assert updates["OBJECTID"].tolist() == [1]
        assert delete_oids == [2]

    @pytest.mark.anyio
    async def test_composite_key_uses_all_fields(self, feature_layer, mocker):
        input_df = pd.DataFrame(
            {
                "Name": ["Alice", "Alice"],
                "Status": ["Active", "Inactive"],
            }
        )
        existing_df = pd.DataFrame(
            {
                "OBJECTID": [1],
                "Name": ["Alice"],
                "Status": ["Active"],
            }
        )
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, delete_oids = await feature_layer._diff(
            input_df, ["Name", "Status"]
        )

        assert adds["Status"].tolist() == ["Inactive"]
        assert updates["Status"].tolist() == ["Active"]
        assert updates["OBJECTID"].tolist() == [1]
        assert delete_oids == []
