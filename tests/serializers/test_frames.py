"""Tests for the shared DataFrame helpers in serializers._frames."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest

from archibald.exceptions import InvalidParameterError
from archibald.serializers._frames import concat_frames, error_frame, geometry_spec
from tests.helpers import ESRI_ROLLBACK_ERROR, make_geo_frame


class TestConcatFrames:
    def test_restores_integer_columns_when_missing_from_some_frames(self):
        frames = [
            pd.DataFrame({"oid": [1], "value": [1.5], "count": [3]}),
            pd.DataFrame({"value": [2.5], "count": [4]}),
        ]

        result = concat_frames(frames)

        assert result.dtypes.astype(str).to_dict() == {
            "oid": "Int64",
            "value": "float64",
            "count": "int64",
        }

    def test_returns_geodataframe_when_a_later_frame_is_geo(self):
        frames = [pd.DataFrame({"name": ["x"]}), make_geo_frame(1)]

        result = concat_frames(frames)

        assert isinstance(result, gpd.GeoDataFrame)
        assert result.geometry.isna().tolist() == [True, False]


class TestGeometrySpec:
    def test_returns_none_when_no_frame_is_geo(self):
        frames = [pd.DataFrame({"a": [1]})]

        result = geometry_spec(frames)

        assert result is None

    def test_returns_name_and_crs_when_geo_frames_agree(self):
        frames = [make_geo_frame(1, geometry_name="shape"), pd.DataFrame()]

        result = geometry_spec(frames)

        assert result == ("shape", "EPSG:4326")

    @pytest.mark.parametrize(
        "other, match",
        [
            (make_geo_frame(1, crs="EPSG:3857"), "different CRS"),
            (make_geo_frame(1, geometry_name="shape"), "different geometry columns"),
        ],
        ids=["crs-mismatch", "geometry-name-mismatch"],
    )
    def test_raises_when_geo_frames_disagree(self, other, match):
        frames = [make_geo_frame(1), other]

        with pytest.raises(InvalidParameterError, match=match):
            geometry_spec(frames)


class TestErrorFrame:
    @pytest.mark.parametrize(
        "error, expected",
        [
            (
                ESRI_ROLLBACK_ERROR,
                "Unable to complete operation. Operation rolled back. "
                "Setting of value for SITEGUID failed.",
            ),
            ({"code": 400, "message": "Only a message."}, "Only a message."),
            ({"code": 400, "details": ["First.", "Second."]}, "First. Second."),
            ({"code": 400, "description": "", "message": "Empty."}, "Empty."),
            ({"code": 400, "description": "Only desc."}, "Only desc."),
        ],
        ids=[
            "message-and-details",
            "message-only",
            "details-only",
            "empty-description",
            "description-only",
        ],
    )
    def test_description_is_filled_when_esri_sent_none(self, error, expected):
        frame = error_frame([error])

        assert frame.loc[0, "error_description"] == expected

    def test_description_is_null_when_no_text_is_available(self):
        frame = error_frame([{"code": 400}])

        assert pd.isna(frame.loc[0, "error_description"])
