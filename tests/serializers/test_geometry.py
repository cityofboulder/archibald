"""Tests for geometry_to_esri."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from archie.exceptions import InvalidParameterError
from archie.serializers._geometry import geometry_to_esri


class TestNullInputs:
    @pytest.mark.parametrize(
        "value",
        [None, float("nan"), math.nan, pd.NA],
        ids=["none", "float-nan", "math-nan", "pd-na"],
    )
    def test_returns_none_for_null_input(self, value):
        assert geometry_to_esri(value) is None


class TestUnsupportedType:
    def test_raises_for_geometry_collection(self):
        gc = GeometryCollection([Point(0, 0)])

        with pytest.raises(InvalidParameterError):
            geometry_to_esri(gc)

    def test_raises_message_contains_type_name(self):
        gc = GeometryCollection([Point(0, 0)])

        with pytest.raises(InvalidParameterError, match="GeometryCollection"):
            geometry_to_esri(gc)


class TestPoint:
    @pytest.mark.parametrize(
        ("geom", "expected"),
        [
            (Point(1.0, 2.0), {"x": 1.0, "y": 2.0}),
            (Point(1.0, 2.0, 3.0), {"x": 1.0, "y": 2.0, "z": 3.0}),
        ],
        ids=["2d", "3d"],
    )
    def test_output_shape(self, geom, expected):
        assert geometry_to_esri(geom) == expected

    @pytest.mark.parametrize(
        ("geom", "forbidden_key"),
        [
            (Point(1.0, 2.0), "z"),
            (Point(1.0, 2.0), "hasZ"),
            (
                Point(1.0, 2.0, 3.0),
                "hasZ",
            ),  # Point uses 'z' directly; hasZ never present
        ],
        ids=["2d-no-z", "2d-no-hasZ", "3d-no-hasZ"],
    )
    def test_forbidden_keys_absent(self, geom, forbidden_key):
        assert forbidden_key not in geometry_to_esri(geom)


class TestMultiPoint:
    @pytest.mark.parametrize(
        ("geom", "expected"),
        [
            (
                MultiPoint([(0.0, 0.0), (1.0, 1.0)]),
                {"points": [[0.0, 0.0], [1.0, 1.0]]},
            ),
            (
                MultiPoint([(0.0, 0.0, 5.0), (1.0, 1.0, 6.0)]),
                {"points": [[0.0, 0.0, 5.0], [1.0, 1.0, 6.0]], "hasZ": True},
            ),
        ],
        ids=["2d", "3d"],
    )
    def test_output_shape(self, geom, expected):
        assert geometry_to_esri(geom) == expected


class TestLineString:
    @pytest.mark.parametrize(
        ("geom", "expected"),
        [
            (
                LineString([(0.0, 0.0), (1.0, 1.0)]),
                {"paths": [[[0.0, 0.0], [1.0, 1.0]]]},
            ),
            (
                LineString([(0.0, 0.0, 1.0), (1.0, 1.0, 2.0)]),
                {"paths": [[[0.0, 0.0, 1.0], [1.0, 1.0, 2.0]]], "hasZ": True},
            ),
        ],
        ids=["2d", "3d"],
    )
    def test_output_shape(self, geom, expected):
        assert geometry_to_esri(geom) == expected


class TestMultiLineString:
    @pytest.mark.parametrize(
        ("geom", "expected"),
        [
            (
                MultiLineString([[(0.0, 0.0), (1.0, 0.0)], [(0.0, 1.0), (1.0, 1.0)]]),
                {"paths": [[[0.0, 0.0], [1.0, 0.0]], [[0.0, 1.0], [1.0, 1.0]]]},
            ),
            (
                MultiLineString([[(0.0, 0.0, 1.0), (1.0, 0.0, 2.0)]]),
                {"paths": [[[0.0, 0.0, 1.0], [1.0, 0.0, 2.0]]], "hasZ": True},
            ),
        ],
        ids=["2d", "3d"],
    )
    def test_output_shape(self, geom, expected):
        assert geometry_to_esri(geom) == expected


class TestPolygon:
    @pytest.mark.parametrize(
        ("holes", "expected_ring_count"),
        [
            ([], 1),
            ([[(0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)]], 2),
            (
                [
                    [(0.1, 0.1), (0.2, 0.1), (0.2, 0.2), (0.1, 0.2)],
                    [(0.5, 0.5), (0.6, 0.5), (0.6, 0.6), (0.5, 0.6)],
                ],
                3,
            ),
        ],
        ids=["no-holes", "one-hole", "two-holes"],
    )
    def test_ring_count_by_hole_count(self, holes, expected_ring_count):
        exterior = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

        result = geometry_to_esri(Polygon(exterior, holes))

        assert isinstance(result, dict)
        assert len(result["rings"]) == expected_ring_count

    def test_ring_0_is_exterior(self):
        exterior = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        hole = [(0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)]

        result = geometry_to_esri(Polygon(exterior, [hole]))

        # Exterior ring spans from x=0 to x=1; hole ring stays within (0.2–0.4)
        assert isinstance(result, dict)
        assert 0.0 in {c[0] for c in result["rings"][0]}
        assert 1.0 in {c[0] for c in result["rings"][0]}
        assert 0.0 not in {c[0] for c in result["rings"][1]}

    @pytest.mark.parametrize(
        ("geom", "expect_has_z"),
        [
            (Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]), False),
            (
                Polygon(
                    [
                        (0.0, 0.0, 1.0),
                        (1.0, 0.0, 1.0),
                        (1.0, 1.0, 1.0),
                        (0.0, 1.0, 1.0),
                    ]
                ),
                True,
            ),
        ],
        ids=["2d", "3d"],
    )
    def test_has_z_flag(self, geom, expect_has_z):
        result = geometry_to_esri(geom)

        assert isinstance(result, dict)
        if expect_has_z:
            assert result["hasZ"] is True
        else:
            assert "hasZ" not in result


class TestMultiPolygon:
    @pytest.mark.parametrize(
        ("parts", "expected_ring_count"),
        [
            (
                [
                    Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]),
                    Polygon([(2.0, 0.0), (3.0, 0.0), (3.0, 1.0), (2.0, 1.0)]),
                ],
                2,
            ),
            (
                [
                    Polygon(
                        [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)],
                        [[(0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (0.5, 1.0)]],
                    ),
                    Polygon(
                        [(3.0, 0.0), (5.0, 0.0), (5.0, 2.0), (3.0, 2.0)],
                        [[(3.5, 0.5), (4.0, 0.5), (4.0, 1.0), (3.5, 1.0)]],
                    ),
                ],
                4,
            ),
        ],
        ids=["two-parts-no-holes", "two-parts-with-holes"],
    )
    def test_ring_count(self, parts, expected_ring_count):
        result = geometry_to_esri(MultiPolygon(parts))

        assert isinstance(result, dict)
        assert len(result["rings"]) == expected_ring_count

    @pytest.mark.parametrize(
        ("geom", "expect_has_z"),
        [
            (
                MultiPolygon(
                    [Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])]
                ),
                False,
            ),
            (
                MultiPolygon(
                    [
                        Polygon(
                            [
                                (0.0, 0.0, 1.0),
                                (1.0, 0.0, 1.0),
                                (1.0, 1.0, 1.0),
                                (0.0, 1.0, 1.0),
                            ]
                        )
                    ]
                ),
                True,
            ),
        ],
        ids=["2d", "3d"],
    )
    def test_has_z_flag(self, geom, expect_has_z):
        result = geometry_to_esri(geom)

        assert isinstance(result, dict)
        if expect_has_z:
            assert result["hasZ"] is True
        else:
            assert "hasZ" not in result
