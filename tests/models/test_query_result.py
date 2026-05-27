"""Tests for QueryResult dataclass."""

import pytest
import pandas as pd
import geopandas as gpd

from archie.models.query_result import QueryResult


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
    def test_returns_records_from_correct_key(self, features, geojson):
        qr = QueryResult(
            features=features, fields=["OBJECTID", "Name"], geojson=geojson
        )

        result = qr.to_frame()

        assert isinstance(result, pd.DataFrame)
        assert result["OBJECTID"].tolist() == [1, 2]
        assert result["Name"].tolist() == ["Feature1", "Feature2"]

    def test_returns_empty_dataframe_with_field_columns_when_no_features(self):
        qr = QueryResult(features=[], fields=["OBJECTID", "Name"], geojson=True)

        result = qr.to_frame()

        assert isinstance(result, pd.DataFrame)
        assert result.empty
        assert list(result.columns) == ["OBJECTID", "Name"]


class TestToGeoDataFrame:
    def test_returns_geodataframe_from_features(self, geojson_query_result):
        result = geojson_query_result.to_geodataframe()

        assert isinstance(result, gpd.GeoDataFrame)
        assert len(result) == 2
        assert result.crs == 4326

    def test_returns_empty_geodataframe_when_no_features(self):
        qr = QueryResult(
            features=[], fields=["OBJECTID", "Name"], geojson=True, crs=4326
        )

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
        qr = QueryResult(features=[], fields=[], geojson=geojson, crs=crs)

        with pytest.raises(ValueError, match=match):
            qr.to_geodataframe()
