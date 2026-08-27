"""ESRI field type coercions: inbound (ESRI JSON → pandas) and outbound (pandas → ESRI JSON)."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Callable, Literal

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from archibald.models.fields_result import FieldsResult


# ─── Inbound: ESRI JSON → pandas ──────────────────────────────────────────────

ESRI_TO_PANDAS: dict[str, Callable[[pd.Series], pd.Series]] = {
    "esriFieldTypeSmallInteger": lambda s: s.astype("Int16"),
    "esriFieldTypeInteger": lambda s: s.astype("Int32"),
    "esriFieldTypeBigInteger": lambda s: s.astype("Int64"),
    "esriFieldTypeOID": lambda s: s.astype("Int64"),
    "esriFieldTypeSingle": lambda s: s.astype("float32"),
    "esriFieldTypeDouble": lambda s: s.astype("float64"),
    "esriFieldTypeDate": lambda s: pd.to_datetime(s, unit="ms", utc=True),
    "esriFieldTypeGUID": lambda s: s.astype(str),
    "esriFieldTypeGlobalID": lambda s: s.astype(str),
    "esriFieldTypeXML": lambda s: s.astype(str),
    "esriFieldTypeString": lambda s: s.astype(str),
}


# ─── Outbound: pandas → ESRI JSON ─────────────────────────────────────────────


def _coerce_datetime(series: pd.Series) -> pd.Series:
    """Convert a datetime Series to integer milliseconds since UTC epoch.

    Emits a UserWarning when the Series is timezone-naive, as the conversion
    will assume UTC. NaT values become None. Returns an object-dtype Series so
    None is preserved rather than coerced back to NaN.

    Object-dtype series (e.g. containing Python datetime objects, pd.Timestamps,
    or ISO-format strings) are first passed through pd.to_datetime(errors="coerce").
    Values that cannot be parsed become null; a UserWarning is emitted with a count
    and examples. If all values resolve to NaT (including all-null input), an
    all-None Series is returned without a tz warning.
    """
    if not pd.api.types.is_datetime64_any_dtype(series):
        null_mask = series.isna()
        parsed = pd.to_datetime(series, errors="coerce")

        failed_mask = ~null_mask & parsed.isna()
        if failed_mask.any():
            examples = series[failed_mask].unique().tolist()[:5]
            warnings.warn(
                f"Column '{series.name}': {int(failed_mask.sum())} value(s) could not be "
                f"parsed as datetime and will be sent as null. Examples: {examples}",
                UserWarning,
                stacklevel=5,
            )

        if parsed.isna().all():
            result = parsed.astype(object)
            result[:] = None
            return result

        series = parsed

    if isinstance(series.dtype, pd.DatetimeTZDtype):
        utc = series.dt.tz_convert("UTC")
    else:
        warnings.warn(
            f"Column '{series.name}' contains timezone-naive datetimes and will be "
            "serialized as UTC. Localize explicitly "
            f"(e.g. df['{series.name}'] = df['{series.name}'].dt.tz_localize('UTC')) "
            "to suppress this warning.",
            UserWarning,
            stacklevel=5,
        )
        utc = series.dt.tz_localize("UTC")

    nat_mask = utc.isna()
    # Normalise to millisecond resolution then strip tz before the int64 cast.
    # astype("datetime64[ms]") fails on tz-aware series; tz_localize(None) strips
    # it cleanly after resolution is fixed. pandas 3 defaults to datetime64[us],
    # so the unit conversion is necessary for a correct ms-since-epoch result.
    ms: pd.Series = (
        utc.dt.as_unit("ms").dt.tz_localize(None).astype("int64").astype(object)
    )
    ms[nat_mask] = None
    return ms


def _coerce_integer(series: pd.Series, nullable_dtype: str) -> pd.Series:
    """Coerce a Series to a nullable integer type for ESRI JSON serialization.

    Emits UserWarnings for:
    - Non-null values that cannot be parsed as numbers (sent as null).
    - Non-null numeric values with fractional parts that will lose precision.

    Args:
        series: Source Series.
        nullable_dtype: Target nullable integer dtype string (e.g. "Int16", "Int32").

    Returns:
        Object-dtype Series with Python int values and None for nulls/failures.
    """
    null_mask = series.isna()
    numeric = pd.to_numeric(series, errors="coerce")

    failed_mask = ~null_mask & numeric.isna()
    if failed_mask.any():
        examples = series[failed_mask].unique().tolist()[:5]
        warnings.warn(
            f"Column '{series.name}': {int(failed_mask.sum())} value(s) could not be "
            f"converted to {nullable_dtype} and will be sent as null. "
            f"Examples: {examples}",
            UserWarning,
            stacklevel=5,
        )

    non_null_numeric = numeric[~numeric.isna()]
    fractional_mask = non_null_numeric != non_null_numeric.round()
    if fractional_mask.any():
        warnings.warn(
            f"Column '{series.name}': {int(fractional_mask.sum())} value(s) have "
            f"fractional parts that will be lost when coerced to {nullable_dtype}.",
            UserWarning,
            stacklevel=5,
        )

    # Truncate fractional parts before the nullable-int cast: pandas _safe_cast
    # rejects float arrays that still carry fractional values.
    truncated = pd.Series(
        np.trunc(numeric.to_numpy(dtype=float)),
        index=numeric.index,
    )
    result = truncated.astype(nullable_dtype).astype(object)  # type: ignore
    result[truncated.isna()] = None
    return result


def _coerce_float(series: pd.Series) -> pd.Series:
    """Coerce a Series to float for ESRI JSON serialization.

    Emits a UserWarning for non-null values that cannot be parsed as a number;
    those are sent as null. NaN and null values become None.

    Args:
        series: Source Series.

    Returns:
        Object-dtype Series with Python float values and None for nulls/failures.
    """
    null_mask = series.isna()
    numeric = pd.to_numeric(series, errors="coerce")

    failed_mask = ~null_mask & numeric.isna()
    if failed_mask.any():
        examples = series[failed_mask].unique().tolist()[:5]
        warnings.warn(
            f"Column '{series.name}': {int(failed_mask.sum())} value(s) could not be "
            f"converted to a float and will be sent as null. "
            f"Examples: {examples}",
            UserWarning,
            stacklevel=5,
        )

    result = numeric.astype("float64").astype(object)
    result[numeric.isna()] = None
    return result


def _coerce_string(series: pd.Series, max_length: int | None = None) -> pd.Series:
    """Coerce a Series to strings for ESRI JSON serialization.

    Null values (None, pd.NA, NaN) are preserved as None rather than converted
    to the strings "None", "<NA>", or "nan". If max_length is given, values
    that exceed it are truncated and a UserWarning is emitted with the count.

    Args:
        series: Source Series.
        max_length: Maximum allowed string length; None means no truncation.

    Returns:
        Object-dtype Series with Python str values and None for nulls.
    """
    null_mask = series.isna()
    result = series.astype(str).astype(object)
    result[null_mask] = None

    if max_length is not None:
        non_null_strs = result[~null_mask]
        too_long_count = int((non_null_strs.str.len() > max_length).sum())
        if too_long_count:
            warnings.warn(
                f"Column '{series.name}': {too_long_count} value(s) exceed the "
                f"maximum length of {max_length} and will be truncated.",
                UserWarning,
                stacklevel=5,
            )
        result[~null_mask] = non_null_strs.str[:max_length]

    return result


def _coerce_guid(series: pd.Series) -> pd.Series:
    """Coerce a Series to GUID strings for ESRI JSON serialization.

    Null values (None, pd.NA, NaN) are preserved as None rather than converted
    to the strings "None", "<NA>", or "nan". Non-null values are cast to str,
    uppercased, and braces are added if missing.

    Args:
        series: Source Series.
    Returns:
        Object-dtype Series with Python str values and None for nulls.
    """
    null_mask = series.isna()
    result = series.astype(str).str.upper().astype(object)

    needs_braces = ~null_mask & ~result.str.startswith("{")
    result[needs_braces] = "{" + result[needs_braces] + "}"
    result[null_mask] = None

    return result


# Dispatch: maps each ESRI type to callable(series, field_def) → object Series.
# field_def is the raw field dict from FieldsResult.fields (may be None).
PANDAS_TO_ESRI: dict[str, Callable[[pd.Series, dict | None], pd.Series]] = {
    "esriFieldTypeSmallInteger": lambda s, f: _coerce_integer(s, "Int16"),
    "esriFieldTypeInteger": lambda s, f: _coerce_integer(s, "Int32"),
    "esriFieldTypeBigInteger": lambda s, f: _coerce_integer(s, "Int64"),
    "esriFieldTypeOID": lambda s, f: _coerce_integer(s, "Int64"),
    "esriFieldTypeSingle": lambda s, f: _coerce_float(s),
    "esriFieldTypeDouble": lambda s, f: _coerce_float(s),
    "esriFieldTypeDate": lambda s, f: _coerce_datetime(s),
    "esriFieldTypeGUID": lambda s, f: _coerce_guid(s),
    "esriFieldTypeGlobalID": lambda s, f: _coerce_guid(s),
    "esriFieldTypeXML": lambda s, f: _coerce_string(s),
    "esriFieldTypeString": lambda s, f: _coerce_string(s, (f or {}).get("length")),
    # esriFieldTypeGeometry: handled by geopandas, not in the editable field set
    # esriFieldTypeBlob, esriFieldTypeRaster: not editable
}


def recode_domains(
    df: pd.DataFrame,
    fields: FieldsResult,
    *,
    direction: Literal["from_esri", "to_esri"] = "from_esri",
) -> pd.DataFrame:
    """Translate coded domain values between codes and human-readable names.

    ``from_esri``: replaces domain codes with their names (e.g. ``1`` → ``"Active"``).
    ``to_esri``: replaces names with their codes (e.g. ``"Active"`` → ``1``).
    Unmapped values (codes absent from the domain) pass through unchanged.
    Null values are preserved as-is.

    Args:
        df: DataFrame to translate (returned as a new object; never mutated).
        fields: Layer field definitions providing coded-value domain metadata.
        direction: ``"from_esri"`` expands codes to names; ``"to_esri"`` collapses
            names back to codes.

    Returns:
        New DataFrame with translated columns; columns without a coded-value
        domain are left unchanged.
    """
    domain_maps = fields.domain_maps
    if not domain_maps:
        return df

    map_key = "to_name" if direction == "from_esri" else "to_code"
    cols = set(df.columns)
    replacements = {}
    for col_name, maps in domain_maps.items():
        if col_name not in cols:
            continue
        null_mask = df[col_name].isna()
        lookup = maps[map_key]
        mapped = df[col_name].map(lookup)
        # Warn when only some non-null values appear in the domain: translated
        # and untranslated values will coexist in the output column, producing
        # mixed types (e.g. int + str). This is fine when ALL values are
        # unmapped (passthrough, uniform type) or all are mapped.
        unmapped_mask = ~null_mask & mapped.isna()
        if unmapped_mask.any() and (~null_mask & mapped.notna()).any():
            examples = df[col_name][unmapped_mask].unique().tolist()[:5]
            warnings.warn(
                f"Column '{col_name}': {int(unmapped_mask.sum())} value(s) were not "
                f"found in the domain and will remain unchanged, producing a "
                f"mixed-type column. Examples: {examples}",
                UserWarning,
                stacklevel=4,
            )
        # map() returns NaN for keys absent from the lookup; fall back to the
        # original value so unmapped codes pass through. Cast to object so the
        # result can hold mixed types, then restore nulls to None explicitly
        # (where() dtype promotion turns None → NaN on float results).
        result = mapped.where(mapped.notna(), df[col_name]).astype(object)
        result[null_mask] = None
        replacements[col_name] = result

    return df.assign(**replacements) if replacements else df


def enforce_types(
    df: pd.DataFrame,
    fields: FieldsResult,
    *,
    direction: Literal["from_esri", "to_esri"] = "from_esri",
) -> pd.DataFrame:
    """Apply ESRI ↔ pandas type coercions to df based on field metadata.

    Args:
        df: DataFrame to coerce (returned as a new object; never mutated).
        fields: Layer field definitions providing type and length metadata.
        direction: ``"from_esri"`` converts ESRI JSON → pandas types (e.g.
            ``Int32``, ``datetime64[ms, UTC]``); ``"to_esri"`` converts pandas
            → ESRI JSON types suitable for serialization.

    Returns:
        New DataFrame with coerced columns; columns whose ESRI type has no
        registered coercer are left unchanged.
    """
    cols = set(df.columns)
    if direction == "from_esri":
        conversions = {
            f["name"]: ESRI_TO_PANDAS[f["type"]](df[f["name"]])
            for f in fields.fields
            if f["name"] in cols and f.get("type") in ESRI_TO_PANDAS
        }
    else:
        conversions = {
            f["name"]: PANDAS_TO_ESRI[f["type"]](df[f["name"]], f)
            for f in fields.fields
            if f["name"] in cols and f.get("type") in PANDAS_TO_ESRI
        }
    return df.assign(**conversions) if conversions else df
