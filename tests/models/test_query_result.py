"""Tests for QueryResult dataclass."""

import pytest
import pandas as pd
import geopandas as gpd

from archie.models import FieldsResult
from tests.helpers import make_query_result


class TestToFrame:
    @pytest.mark.parametrize(
        "features, geojson",
        [
            (
                [
                    {"properties": {"OBJECTID": 1, "Name": "Feature1"}},
                    {"properties": {"OBJECTID": 2, "Name": "Feature2"}},
                ],
                True,
            ),
            (
                [
                    {"attributes": {"OBJECTID": 1, "Name": "Feature1"}},
                    {"attributes": {"OBJECTID": 2, "Name": "Feature2"}},
                ],
                False,
            ),
        ],
        ids=["geojson", "esri_json"],
    )
    def test_returns_records_from_correct_key(self, fields_result, features, geojson):
        qr = make_query_result(features, fields_result, geojson=geojson)

        result = qr.to_frame()

        assert isinstance(result, pd.DataFrame)
        assert result["OBJECTID"].tolist() == [1, 2]
        assert result["Name"].tolist() == ["Feature1", "Feature2"]

    def test_returns_empty_dataframe_with_field_columns_when_no_features(
        self, fields_result
    ):
        qr = make_query_result([], fields_result)

        result = qr.to_frame()

        assert isinstance(result, pd.DataFrame)
        assert result.empty
        assert list(result.columns) == ["OBJECTID", "Name", "Status"]


class TestToGeoDataFrame:
    def test_returns_geodataframe_from_features(self, geojson_query_result):
        result = geojson_query_result.to_geodataframe()

        assert isinstance(result, gpd.GeoDataFrame)
        assert len(result) == 2
        assert result.crs == 4326

    def test_returns_empty_geodataframe_when_no_features(self, fields_result):
        qr = make_query_result([], fields_result, crs=4326)

        result = qr.to_geodataframe()

        assert isinstance(result, gpd.GeoDataFrame)
        assert result.empty

    @pytest.mark.parametrize(
        "geojson, crs, match",
        [
            (False, 4326, "no geometry present"),
            (True, None, "no spatial reference"),
        ],
        ids=["no-geometry", "no-crs"],
    )
    def test_raises_when_cannot_convert(self, geojson, crs, match):
        qr = make_query_result([], FieldsResult(fields=[]), geojson=geojson, crs=crs)

        with pytest.raises(ValueError, match=match):
            qr.to_geodataframe()


class TestParseDtypes:
    @pytest.mark.parametrize(
        "esri_type, raw_value, expected_dtype",
        [
            ("esriFieldTypeDate", 1_748_476_800_000, "datetime64[ms, UTC]"),
            ("esriFieldTypeInteger", 42, "Int32"),
            ("esriFieldTypeSmallInteger", 5, "Int16"),
            ("esriFieldTypeBigInteger", 10**10, "Int64"),
            ("esriFieldTypeOID", 1, "Int64"),
            ("esriFieldTypeSingle", 3.14, "float32"),
            ("esriFieldTypeDouble", 3.14, "float64"),
            ("esriFieldTypeGUID", "{abc}", "str"),
            ("esriFieldTypeGlobalID", "{def}", "str"),
            ("esriFieldTypeXML", "<x/>", "str"),
            ("esriFieldTypeString", "hello", "str"),
        ],
        ids=[
            "date",
            "integer",
            "small-integer",
            "big-integer",
            "oid",
            "single",
            "double",
            "guid",
            "global-id",
            "xml",
            "string",
        ],
    )
    def test_to_frame_converts_column_type_when_parse_dtypes_true(
        self, esri_type, raw_value, expected_dtype
    ):
        fields = FieldsResult(fields=[{"name": "Value", "type": esri_type}])
        qr = make_query_result([{"properties": {"Value": raw_value}}], fields)

        result = qr.to_frame(parse_dtypes=True)

        assert str(result["Value"].dtype) == expected_dtype

    def test_to_frame_does_not_convert_when_parse_dtypes_false(self):
        fields = FieldsResult(
            fields=[{"name": "StartDate", "type": "esriFieldTypeDate"}]
        )
        qr = make_query_result(
            [{"properties": {"StartDate": 1_748_476_800_000}}], fields
        )

        result = qr.to_frame()

        assert pd.api.types.is_integer_dtype(result["StartDate"])

    def test_to_frame_parse_dtypes_true_with_no_features_returns_empty(self):
        fields = FieldsResult(
            fields=[{"name": "StartDate", "type": "esriFieldTypeDate"}]
        )
        qr = make_query_result([], fields)

        result = qr.to_frame(parse_dtypes=True)

        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_to_frame_parse_dtypes_true_returns_dataframe(self):
        fields = FieldsResult(
            fields=[{"name": "Count", "type": "esriFieldTypeInteger"}]
        )
        qr = make_query_result([{"properties": {"Count": 1}}], fields)

        result = qr.to_frame(parse_dtypes=True)

        assert type(result) is pd.DataFrame

    def test_to_geodataframe_converts_column_while_preserving_geometry(self):
        fields = FieldsResult(
            fields=[{"name": "StartDate", "type": "esriFieldTypeDate"}]
        )
        features = [
            {
                "type": "Feature",
                "properties": {"StartDate": 1_748_476_800_000},
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            }
        ]
        qr = make_query_result(features, fields, crs=4326)

        result = qr.to_geodataframe(parse_dtypes=True)

        assert isinstance(result, gpd.GeoDataFrame)
        assert str(result["StartDate"].dtype) == "datetime64[ms, UTC]"
        assert isinstance(result.geometry, gpd.GeoSeries)
