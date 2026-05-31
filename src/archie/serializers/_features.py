"""serialize_features, pack_batches: DataFrame → ESRI feature dicts + batch packing."""

from __future__ import annotations

import json
import warnings
from typing import TYPE_CHECKING

import geopandas as gpd
import pandas as pd

from archie.serializers._coercions import PANDAS_TO_ESRI
from archie.serializers._geometry import geometry_to_esri

if TYPE_CHECKING:
    from archie.models.fields_result import FieldsResult


def _select_attr_columns(
    df: pd.DataFrame,
    fields: FieldsResult,
    objectid_field: str | None,
    geo_col: str | None,
) -> list[str]:
    """Return the list of attribute columns to include in serialization.

    Builds the keep-set from editable fields plus the OBJECTID when provided,
    then emits a warning for every df column that falls outside that set
    (excluding the geometry column).
    """
    editables = set(fields.filter(editable=True).names)
    ids: set[str] = {objectid_field} if objectid_field else set()
    attrs = set(c for c in df.columns if c != geo_col)
    final_attrs = (ids & attrs) | (editables & attrs)
    dropped = sorted(attrs - final_attrs)

    if dropped:
        msg_cols = ", ".join(repr(c) for c in dropped)
        warnings.warn(
            (
                "The following columns(s) are not editable and will not be sent: "
                f"{msg_cols}"
            ),
            stacklevel=4,
        )

    return list(final_attrs)  # Order does not matter for sending data to API


def _coerce_columns(
    attrs: pd.DataFrame,
    fields: FieldsResult,
) -> pd.DataFrame:
    """Apply per-column type coercions then replace remaining NA/NaN with None.

    Dispatches each column to its ESRI-type-specific coercion function via
    PANDAS_TO_ESRI. Columns whose ESRI type has no registered coercer are left
    unchanged. The final where() call is a safety net for any unregistered types
    that may still carry numpy NA sentinels.
    """
    field_types = fields.field_type_map
    field_defs = {f["name"]: f for f in fields.fields}

    for col in attrs.columns:
        coercer = PANDAS_TO_ESRI.get(field_types.get(col, ""))
        if coercer is not None:
            attrs[col] = coercer(attrs[col], field_defs.get(col))

    return attrs.astype(object).where(pd.notna(attrs), other=None)


def _pair_geometry(
    records: list[dict],
    gdf: gpd.GeoDataFrame,
) -> list[dict]:
    """Pair attribute record dicts with their ESRI JSON geometry counterparts.

    Geometry is converted via GeoSeries.apply so no explicit row iteration
    occurs. Features with null geometry omit the ``"geometry"`` key entirely.
    """
    geoms = gdf.geometry.apply(geometry_to_esri).tolist()
    return [
        {"attributes": attrs, "geometry": geom}
        if geom is not None
        else {"attributes": attrs}
        for attrs, geom in zip(records, geoms)
    ]


def serialize_features(
    df: pd.DataFrame | gpd.GeoDataFrame,
    fields: FieldsResult,
    *,
    objectid_field: str | None = None,
) -> list[dict]:
    """Convert a DataFrame (or GeoDataFrame) to a list of ESRI feature dicts.

    All type conversion and column selection are performed as vectorized column
    operations; no iteration over DataFrame rows occurs. Geometry is handled
    via ``GeoSeries.apply``, which is the tightest available abstraction for
    per-geometry conversion.

    Field selection:
        - Start from ``fields.filter(editable=True)`` for the writable set.
        - Include ``objectid_field`` when provided (required for updates; pass
          None for adds so the server assigns a new OID).
        - DataFrame columns outside the selected set are dropped; a
          ``warnings.warn`` is emitted for each so callers know their data
          was not sent.

    Reverse type conversions (pandas → ESRI JSON):
        - ``datetime64`` / tz-aware datetime: converted to integer milliseconds
          since UTC epoch; ``NaT`` → ``None``.
        - Nullable integer (``Int8``/``Int16``/``Int32``/``Int64``): Python
          ``int`` or ``None`` for ``pd.NA``.
        - ``float``: ``NaN`` → ``None``.
        - ``str`` / ``object``: ``pd.NA`` / ``None`` preserved as ``None``;
          values for ``esriFieldTypeString`` columns are truncated to the
          field's ``"length"`` when defined.

    Args:
        df: Source DataFrame or GeoDataFrame.
        fields: Layer field definitions used for type metadata and editable
            field selection.
        objectid_field: Name of the layer's OBJECTID field, or None to exclude
            it. Pass None for add operations; pass the field name for updates.

    Returns:
        List of ``{"attributes": {...}}`` dicts, with an additional
        ``"geometry"`` key for GeoDataFrame rows that carry non-null geometry.
    """
    is_geo = isinstance(df, gpd.GeoDataFrame)
    geo_col: str | None = str(df.geometry.name) if is_geo else None

    attr_cols = _select_attr_columns(df, fields, objectid_field, geo_col)
    attrs = _coerce_columns(df[attr_cols].copy(), fields)
    records: list[dict] = attrs.to_dict(orient="records")

    if is_geo:
        return _pair_geometry(records, df)
    return [{"attributes": rec} for rec in records]


def pack_batches(
    adds: list[dict],
    updates: list[dict],
    deletes: list[int],
    *,
    max_bytes: int = 1_800_000,
    overhead_bytes: int = 4_096,
) -> list[dict]:
    """Pack adds, updates, and deletes into POST body dicts bounded by max_bytes.

    Greedy algorithm: serialise each feature to a JSON byte string once,
    then fill batches in order — adds first, then updates, then deletes —
    flushing to a new batch whenever the next item would push the running
    total over ``max_bytes - overhead_bytes``.

    Empty lists are omitted from each batch dict. A single-element list is
    returned for datasets that fit within one batch.

    Args:
        adds: Serialised ESRI feature dicts to add.
        updates: Serialised ESRI feature dicts to update (must include OBJECTID).
        deletes: Integer OBJECTIDs to delete.
        max_bytes: Soft upper bound for the encoded POST body (default 1.8 MB).
        overhead_bytes: Reserved headroom per batch for HTTP framing and form
            encoding (default 4 KB).

    Returns:
        List of POST body dicts, each containing any combination of
        ``"adds"``, ``"updates"``, and ``"deletes"`` keys.
    """
    budget = max_bytes - overhead_bytes

    # Pre-serialise features to measure their encoded byte sizes once.
    add_sizes = [len(json.dumps(f).encode()) for f in adds]
    update_sizes = [len(json.dumps(f).encode()) for f in updates]

    batches: list[dict] = []

    # Batch state — mutated in place by _flush.
    batch_adds: list[dict] = []
    batch_updates: list[dict] = []
    batch_deletes: list[int] = []
    running = 0

    def _flush() -> None:
        """Emit the current batch and reset mutable state."""
        body: dict = {}
        if batch_adds:
            body["adds"] = list(batch_adds)
        if batch_updates:
            body["updates"] = list(batch_updates)
        if batch_deletes:
            body["deletes"] = ",".join(str(o) for o in batch_deletes)
        if body:
            batches.append(body)
        batch_adds.clear()
        batch_updates.clear()
        batch_deletes.clear()

    # --- adds ---
    for feat, size in zip(adds, add_sizes):
        if running + size > budget and (batch_adds or batch_updates or batch_deletes):
            _flush()
            running = 0
        batch_adds.append(feat)
        running += size

    # --- updates ---
    for feat, size in zip(updates, update_sizes):
        if running + size > budget and (batch_adds or batch_updates or batch_deletes):
            _flush()
            running = 0
        batch_updates.append(feat)
        running += size

    # --- deletes ---
    # OIDs are small integers; estimate bytes as digit count + 2 (comma + space).
    for oid in deletes:
        oid_size = len(str(oid)) + 2
        if running + oid_size > budget and (
            batch_adds or batch_updates or batch_deletes
        ):
            _flush()
            running = 0
        batch_deletes.append(oid)
        running += oid_size

    _flush()

    # Guarantee at least one element so callers never receive [].
    if not batches:
        batches.append({})

    return batches
