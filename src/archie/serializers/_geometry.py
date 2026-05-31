"""geometry_to_esri: convert shapely geometries to ESRI JSON geometry dicts."""

from __future__ import annotations

import math

import pandas as pd

from archie.exceptions import InvalidParameterError


def geometry_to_esri(geom) -> dict | None:
    """Convert a shapely geometry (or None/NaN) to an ESRI JSON geometry dict.

    Intended to be called via ``GeoSeries.apply(geometry_to_esri)`` — one call
    per geometry object, not per DataFrame row.

    Supported types: Point, MultiPoint, LineString, MultiLineString, Polygon,
    MultiPolygon. Z coordinates are preserved when the coordinate tuple has
    length 3.

    For Point, Z is included as a top-level ``"z"`` key per the ESRI spec.
    For all other geometry types, ``"hasZ": true`` is included at the geometry
    level whenever Z coordinates are present, as required by the ESRI REST API.

    Args:
        geom: A shapely geometry, None, float NaN, or ``pd.NA`` (the three
            forms in which a GeoSeries stores missing geometries).

    Returns:
        ESRI JSON geometry dict, or None for null/missing geometry (the caller
        omits the ``"geometry"`` key from the feature dict in that case).

    Raises:
        InvalidParameterError: If geom is a non-null, unsupported geometry type.
    """
    if geom is None or geom is pd.NA:
        return None
    if isinstance(geom, float) and math.isnan(geom):
        return None

    geo = geom.__geo_interface__  # type: ignore[attr-defined]
    gtype: str = geo["type"]

    _SUPPORTED = {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
    }
    if gtype not in _SUPPORTED:
        raise InvalidParameterError(
            f"Unsupported geometry type: {gtype!r}. "
            "Supported: Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon."
        )

    coords = geo["coordinates"]

    def extract_coords(c) -> list:
        """Return [x, y, z] if the coordinate tuple has length 3, else [x, y]."""
        return [c[0], c[1], c[2]] if len(c) == 3 else [c[0], c[1]]

    if gtype == "Point":
        # Point uses "z" directly; no hasZ flag per ESRI spec.
        return {
            "x": coords[0],
            "y": coords[1],
            **({} if len(coords) < 3 else {"z": coords[2]}),
        }

    if gtype == "MultiPoint":
        result: dict = {"points": [extract_coords(c) for c in coords]}
    elif gtype == "LineString":
        result = {"paths": [[extract_coords(c) for c in coords]]}
    elif gtype == "MultiLineString":
        result = {"paths": [[extract_coords(c) for c in ring] for ring in coords]}
    elif gtype == "Polygon":
        result = {"rings": [[extract_coords(c) for c in ring] for ring in coords]}
    else:
        # gtype == "MultiPolygon"
        result = {
            "rings": [
                [extract_coords(c) for c in ring]
                for polygon in coords
                for ring in polygon
            ]
        }

    if geom.has_z:  # type: ignore[attr-defined]
        result["hasZ"] = True

    return result
