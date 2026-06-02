"""Tests for serialize_features and pack_batches."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from archibald.models import FieldsResult
from archibald.serializers._features import pack_batches, serialize_features
from tests.helpers import make_small_feature


class TestSelectAttrColumns:
    def test_objectid_included_when_objectid_field_provided(self, fields_result):
        df = pd.DataFrame({"OBJECTID": [1], "Name": ["Alice"]})

        result = serialize_features(df, fields_result, objectid_field="OBJECTID")

        assert "OBJECTID" in result[0]["attributes"]

    def test_objectid_excluded_when_objectid_field_none(self, fields_result):
        df = pd.DataFrame({"Name": ["Alice"]})

        result = serialize_features(df, fields_result, objectid_field=None)

        assert "OBJECTID" not in result[0]["attributes"]

    def test_globalid_dropped_as_non_editable(self):
        fields = FieldsResult(
            fields=[
                {"name": "OBJECTID", "type": "esriFieldTypeOID", "editable": False},
                {"name": "Name", "type": "esriFieldTypeString", "editable": True},
                {
                    "name": "GlobalID",
                    "type": "esriFieldTypeGlobalID",
                    "editable": False,
                },
            ]
        )
        df = pd.DataFrame(
            {"OBJECTID": [1], "Name": ["Alice"], "GlobalID": ["{abc-123}"]}
        )

        with pytest.warns(UserWarning, match="GlobalID"):
            result = serialize_features(df, fields, objectid_field="OBJECTID")

        assert "GlobalID" not in result[0]["attributes"]

    def test_non_editable_column_dropped_with_warning(self, fields_result):
        df = pd.DataFrame({"OBJECTID": [1], "Name": ["Alice"], "ExtraCol": ["x"]})

        with pytest.warns(UserWarning, match="ExtraCol"):
            result = serialize_features(df, fields_result, objectid_field="OBJECTID")

        assert "ExtraCol" not in result[0]["attributes"]

    def test_geometry_column_excluded_from_attributes(self, fields_result):
        gdf = gpd.GeoDataFrame(
            {"OBJECTID": [1], "Name": ["Alice"], "geometry": [Point(0.0, 0.0)]},
            crs=4326,
        )

        result = serialize_features(gdf, fields_result, objectid_field="OBJECTID")

        assert "geometry" not in result[0]["attributes"]


class TestSerializeFeatures:
    def test_plain_dataframe_returns_attributes_dicts(self, fields_result):
        df = pd.DataFrame({"OBJECTID": [1, 2], "Name": ["Alice", "Bob"]})

        result = serialize_features(df, fields_result, objectid_field="OBJECTID")

        assert len(result) == 2
        assert all("attributes" in feat for feat in result)
        assert all("geometry" not in feat for feat in result)

    def test_geodataframe_includes_geometry_key(self, fields_result):
        gdf = gpd.GeoDataFrame(
            {"OBJECTID": [1], "Name": ["Alice"], "geometry": [Point(1.0, 2.0)]},
            crs=4326,
        )

        result = serialize_features(gdf, fields_result, objectid_field="OBJECTID")

        assert "geometry" in result[0]
        assert result[0]["geometry"] == {"x": 1.0, "y": 2.0}

    def test_null_geometry_omits_geometry_key(self, fields_result):
        gdf = gpd.GeoDataFrame(
            {
                "OBJECTID": [1, 2],
                "Name": ["Alice", "Bob"],
                "geometry": [Point(0.0, 0.0), None],
            },
            crs=4326,
        )

        result = serialize_features(gdf, fields_result, objectid_field="OBJECTID")

        assert "geometry" in result[0]
        assert "geometry" not in result[1]

    def test_objectid_field_none_omits_objectid(self, fields_result):
        df = pd.DataFrame({"Name": ["Alice"]})

        result = serialize_features(df, fields_result, objectid_field=None)

        assert "OBJECTID" not in result[0]["attributes"]

    def test_translates_domain_names_to_codes_when_flag_set(
        self, fields_result_with_domains
    ):
        df = pd.DataFrame({"Status": ["Active", "Inactive"]})

        result = serialize_features(
            df, fields_result_with_domains, apply_coded_values=True
        )

        assert result[0]["attributes"]["Status"] == 1
        assert result[1]["attributes"]["Status"] == 0

    def test_leaves_values_unchanged_when_apply_coded_values_false(
        self, fields_result_with_domains
    ):
        df = pd.DataFrame({"Status": [1, 0]})

        result = serialize_features(df, fields_result_with_domains)

        assert result[0]["attributes"]["Status"] == 1
        assert result[1]["attributes"]["Status"] == 0

    def test_warns_and_nulls_unmapped_names_when_mixed_to_esri(
        self, fields_result_with_domains
    ):
        # "Active" maps to 1; "Unknown" has no domain entry → recode_domains
        # emits a mixed-type warning, and the leftover str "Unknown" cannot be
        # coerced to an integer by _coerce_columns, so it is sent as null.
        df = pd.DataFrame({"Status": ["Active", "Unknown"]})

        with pytest.warns(UserWarning, match="mixed-type"):
            result = serialize_features(
                df, fields_result_with_domains, apply_coded_values=True
            )

        assert result[0]["attributes"]["Status"] == 1
        assert result[1]["attributes"]["Status"] is None


class TestPackBatches:
    def test_empty_inputs_returns_single_empty_dict(self):
        result = pack_batches([], [], [])

        assert result == [{}]

    def test_all_fit_in_one_batch(self):
        adds = [make_small_feature(1)]
        updates = [make_small_feature(2)]
        deletes = [3]

        result = pack_batches(
            adds, updates, deletes, max_bytes=1_000_000, overhead_bytes=0
        )

        assert len(result) == 1
        assert "adds" in result[0]
        assert "updates" in result[0]
        assert "deletes" in result[0]

    @pytest.mark.parametrize(
        "args, key",
        [
            (([make_small_feature(i) for i in range(3)], [], []), "adds"),
            (([], [make_small_feature(i) for i in range(3)], []), "updates"),
        ],
        ids=["adds", "updates"],
    )
    def test_features_overflow_into_separate_batches(self, args, key):
        result = pack_batches(*args, max_bytes=1, overhead_bytes=0)

        assert len(result) == 3
        assert all(key in b for b in result)

    def test_deletes_serialized_as_comma_separated_string(self):
        result = pack_batches([], [], [1, 2, 3], max_bytes=1_000_000, overhead_bytes=0)

        assert result[0]["deletes"] == "1,2,3"

    def test_empty_lists_omitted_from_batch_dict(self):
        result = pack_batches(
            [make_small_feature()], [], [], max_bytes=1_000_000, overhead_bytes=0
        )

        assert "adds" in result[0]
        assert "updates" not in result[0]
        assert "deletes" not in result[0]

    def test_single_oversized_feature_still_emitted(self):
        adds = [make_small_feature()]

        result = pack_batches(adds, [], [], max_bytes=1, overhead_bytes=0)

        assert len(result) == 1
        assert result[0]["adds"] == adds
