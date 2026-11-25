"""DataFrame helpers shared by result models: stacking input frames and flattening errors."""

from __future__ import annotations

import re
from typing import Any

import geopandas as gpd
import pandas as pd

from archibald.exceptions import InvalidParameterError


def attach_metadata(
    rows: pd.DataFrame | gpd.GeoDataFrame,
    metadata: pd.DataFrame,
) -> pd.DataFrame | gpd.GeoDataFrame:
    """Append ``metadata`` columns to ``rows``, matching them by position.

    Args:
        rows: Input rows, one per item, with their original index.
        metadata: Prefixed metadata for the same items, in the same order.

    Raises:
        InvalidParameterError: If a metadata column already exists in
            ``rows``.
    """
    clash = sorted(set(metadata.columns) & set(rows.columns))
    if clash:
        raise InvalidParameterError(
            f"Columns {clash} already exist in the input; "
            "pass a different metadata_prefix."
        )
    return rows.assign(**{c: metadata[c].array for c in metadata.columns})


def concat_frames(
    frames: list[pd.DataFrame | gpd.GeoDataFrame],
) -> pd.DataFrame | gpd.GeoDataFrame:
    """Stack frames row-wise, returning a GeoDataFrame if any stacked one is.

    Empty frames are skipped (unless all are empty) so they don't affect
    the result's columns, dtypes, or type. ``pd.concat`` returns the type
    of the first frame, so the result is rebuilt as a GeoDataFrame per
    ``geometry_spec``, and integer columns are restored per
    ``_restore_int_columns``.
    """
    frames = [f for f in frames if len(f)] or frames[:1]
    geometry = geometry_spec(frames)
    out = pd.concat(frames) if len(frames) > 1 else frames[0]
    out = _restore_int_columns(out, frames)
    if geometry is None:
        return out
    name, crs = geometry
    return gpd.GeoDataFrame(out, geometry=name, crs=crs)


def error_frame(errors: list[dict | None]) -> pd.DataFrame:
    """Return one row per error dict, flattened into columns.

    Keys become ``error_<snake_case_key>`` columns (``extendedCode`` →
    ``error_extended_code``). ``error_code``, ``error_description``,
    ``error_exception``, ``error_outcome_unknown``, and
    ``error_status_url`` are always present, with fixed dtypes; other keys
    follow in the order they appear, with dtypes from ``convert_dtypes``.
    Where ESRI sent no description (rolled-back batches carry ``message``
    and ``details`` instead), ``error_description`` is filled from those.
    A None entry (an item without an error) gives a row of nulls.
    """
    core_dtypes = {
        "code": "Int64",
        "description": "string",
        "exception": "string",
        "outcome_unknown": "boolean",
        "status_url": "string",
    }
    frame = pd.DataFrame([error or {} for error in errors], index=range(len(errors)))
    frame = frame.rename(
        columns=lambda c: re.sub(r"(?<!^)(?=[A-Z])", "_", str(c)).lower()
    )
    extras = [c for c in frame.columns if c not in core_dtypes]
    frame = frame.reindex(columns=[*core_dtypes, *extras])
    described = frame["description"].fillna("") != ""
    frame["description"] = frame["description"].where(
        described, _fallback_description(frame)
    )
    frame[extras] = frame[extras].convert_dtypes()
    return frame.astype(core_dtypes).add_prefix("error_")


def geometry_spec(
    frames: list[pd.DataFrame | gpd.GeoDataFrame],
) -> tuple[str, Any] | None:
    """Return the shared geometry column name and CRS of the GeoDataFrames.

    Returns:
        ``(name, crs)`` of the GeoDataFrames in ``frames``, or None when
        there are none.

    Raises:
        InvalidParameterError: If the GeoDataFrames disagree on geometry
            column name or CRS.
    """
    geo = [f for f in frames if isinstance(f, gpd.GeoDataFrame)]
    if not geo:
        return None
    names = {str(g.geometry.name) for g in geo}
    if len(names) > 1:
        raise InvalidParameterError(
            f"GeoDataFrame inputs use different geometry columns: {sorted(names)}."
        )
    if any(g.crs != geo[0].crs for g in geo[1:]):
        raise InvalidParameterError(
            "GeoDataFrame inputs have different CRS: "
            f"{sorted({str(g.crs) for g in geo})}."
        )
    return names.pop(), geo[0].crs


def _fallback_description(errors: pd.DataFrame) -> pd.Series:
    """Join each row's ``message`` and ``details`` into one string.

    Rows with neither are null. ``details`` holds a list of strings.
    """
    text = pd.Series("", index=errors.index)
    if "message" in errors:
        text = errors["message"].fillna("").astype(str)
    if "details" in errors:
        details = errors["details"].map(
            lambda d: " ".join(str(p) for p in d) if isinstance(d, list) else ""
        )
        text = text + " " + details
    text = text.str.strip()
    return text.where(text != "")


def _restore_int_columns(
    out: pd.DataFrame | gpd.GeoDataFrame,
    frames: list[pd.DataFrame | gpd.GeoDataFrame],
) -> pd.DataFrame | gpd.GeoDataFrame:
    """Cast columns that ``pd.concat`` turned from integer to float to ``Int64``.

    A column missing from some frames (e.g. OBJECTID, absent from adds)
    is filled with NaN, which turns integers into floats; nullable
    ``Int64`` keeps them integers with ``<NA>`` for the missing rows.

    Args:
        out: The concatenated frame.
        frames: The frames ``out`` was built from.
    """
    upcast = [
        c
        for c in out.columns
        if not pd.api.types.is_integer_dtype(out[c])
        and all(pd.api.types.is_integer_dtype(f[c]) for f in frames if c in f)
    ]
    return out.astype(dict.fromkeys(upcast, "Int64"))
