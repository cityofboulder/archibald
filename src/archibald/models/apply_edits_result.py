"""ApplyEditsResult: aggregated response from an applyEdits operation."""

from __future__ import annotations

import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, get_args

import geopandas as gpd
import pandas as pd

from archibald.exceptions import InvalidParameterError
from archibald.models.edit_result_item import EditKind, EditResultItem, EditStatus

__all__ = ["ApplyEditsResult", "EditKind", "EditResultItem", "EditStatus"]


@dataclass
class ApplyEditsResult:
    """Aggregated add/update/delete results across all applyEdits batches.

    Per-feature errors are captured in result items rather than raised as
    exceptions. Inspect ``has_failures`` and ``failed_*`` properties to detect
    partial failures without iterating manually.

    Built only by applyEdits: ``_merge`` sets every item's ``kind`` and
    ``position`` (its row in that kind's input frame), and the operation
    stores each kind's input frame in ``_inputs`` (in adds, updates, deletes
    order). ``_inputs`` is excluded
    from equality and repr.
    """

    add_results: list[EditResultItem]
    update_results: list[EditResultItem]
    delete_results: list[EditResultItem]
    _inputs: dict[EditKind, pd.DataFrame | gpd.GeoDataFrame] = field(
        default_factory=dict, compare=False, repr=False
    )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def failed_adds(self) -> list[EditResultItem]:
        """Add results where success=False."""
        return [r for r in self.add_results if not r.success]

    @property
    def failed_deletes(self) -> list[EditResultItem]:
        """Delete results where success=False."""
        return [r for r in self.delete_results if not r.success]

    @property
    def failed_updates(self) -> list[EditResultItem]:
        """Update results where success=False."""
        return [r for r in self.update_results if not r.success]

    @property
    def has_failures(self) -> bool:
        """True if any add, update, or delete result reports success=False."""
        return any(not r.success for r in self._items)

    @property
    def _items(self) -> list[EditResultItem]:
        """All items: adds, then updates, then deletes."""
        return self.add_results + self.update_results + self.delete_results

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def filter(
        self,
        *,
        kinds: EditKind | list[EditKind] | None = None,
        statuses: EditStatus | list[EditStatus] | None = None,
    ) -> ApplyEditsResult:
        """Return a new ApplyEditsResult keeping only items matching all criteria.

        The input frames are carried over, so the filtered result still maps
        its items back to their input rows.

        Args:
            kinds: Keep only these kinds (``"adds"``, ``"updates"``,
                ``"deletes"``). A single value or a list; None keeps all.
            statuses: Keep only items with these statuses (``"succeeded"``,
                ``"failed"``, ``"unknown"``). A single value or a list; None
                keeps all.

        Returns:
            A new ApplyEditsResult; kinds that are filtered out have no items.

        Raises:
            InvalidParameterError: If any kind or status is not a valid value.
        """
        kind_set = self._filter_values(kinds, get_args(EditKind), "kinds")
        status_set = self._filter_values(statuses, get_args(EditStatus), "statuses")
        kept = [
            item
            for item in self._items
            if (kind_set is None or item.kind in kind_set)
            and (status_set is None or item.status in status_set)
        ]
        return ApplyEditsResult(
            add_results=[i for i in kept if i.kind == "adds"],
            update_results=[i for i in kept if i.kind == "updates"],
            delete_results=[i for i in kept if i.kind == "deletes"],
            _inputs=self._inputs,
        )

    @classmethod
    def from_esri_response(cls, body: dict) -> ApplyEditsResult:
        """Parse a single synchronous applyEdits response body.

        .. deprecated::
            Internal to applyEdits; will be removed in 2.0. Results come from
            ``FeatureLayer`` edit methods.

        Args:
            body: Parsed JSON response dict from the applyEdits endpoint.

        Returns:
            ApplyEditsResult populated from addResults, updateResults, deleteResults.
        """
        warnings.warn(
            "ApplyEditsResult.from_esri_response is deprecated and will be "
            "removed in 2.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls._from_esri_response(body)

    @classmethod
    def merge(cls, results: list[ApplyEditsResult]) -> ApplyEditsResult:
        """Merge multiple per-batch ApplyEditsResults into one aggregate.

        .. deprecated::
            Internal to applyEdits batching; will be removed in 2.0.

        Args:
            results: List of per-batch results in posting order.

        Returns:
            Single ApplyEditsResult with all items concatenated in order.
        """
        warnings.warn(
            "ApplyEditsResult.merge is deprecated and will be removed in 2.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls._merge(results)

    def to_frame(
        self,
        *,
        include_input: bool = True,
        include_metadata: bool = True,
        metadata_prefix: str = "_edit_",
    ) -> pd.DataFrame | gpd.GeoDataFrame:
        """Return one row per edit, in adds, updates, deletes order.

        With ``include_input``, each row is the input row the edit came from,
        with its original index: for ``append`` / ``upsert`` / ``sync``, rows
        of the df passed in (``upsert`` / ``sync`` updates also carry the
        matched OBJECTID); for ``apply_edits``, rows of ``adds`` / ``updates``
        / ``deletes``. Deletes given as OBJECTIDs are rows of a one-column
        OBJECTID frame; ``sync`` deletes hold the OBJECTID and key fields.
        Combine with ``filter`` to get some rows, e.g.
        ``result.filter(statuses="failed").to_frame()``.

        Metadata columns: ``kind`` and ``status`` (categoricals of the
        ``EditKind`` / ``EditStatus`` values), ``object_id`` (-1 when ESRI
        reports none, e.g. a failed add), ``global_id``, ``position`` (the
        row's position in its input frame), then each error dict flattened
        into ``error_<snake_case_key>`` columns. ``error_code``,
        ``error_description``, ``error_exception``, ``error_outcome_unknown``,
        and ``error_status_url`` are always present; other keys (e.g.
        ``extendedCode``, ``message``, ``details`` from a rolled-back batch)
        add columns as they appear. ``error_description`` holds readable text
        for every failure: when ESRI sent none, ``message`` and ``details``
        joined.

        Args:
            include_input: Include the input row of each edit.
            include_metadata: Include the metadata columns. Alongside input
                rows they are prefixed with ``metadata_prefix`` and
                ``position`` is left out.
            metadata_prefix: Prefix for metadata columns when
                ``include_input`` is True; ignored otherwise.

        Returns:
            The DataFrame described above; a GeoDataFrame when an input frame
            is one (rows without geometry, such as deletes, get null
            geometry).

        Raises:
            InvalidParameterError: If both ``include_input`` and
                ``include_metadata`` are False, or if a prefixed metadata
                column already exists in an input frame.
        """
        if not include_input and not include_metadata:
            raise InvalidParameterError(
                "include_input and include_metadata cannot both be False."
            )
        meta = self._metadata_frame()
        if not include_input:
            return meta
        if not self._inputs:
            return pd.DataFrame()
        positions = meta["position"].astype(int)
        rows = self._concat_frames(
            [
                frame.iloc[positions[meta["kind"] == kind].to_numpy()]
                for kind, frame in self._inputs.items()
            ]
        )
        if not include_metadata:
            return rows
        metadata = meta.drop(columns="position").add_prefix(metadata_prefix)
        return self._attach_metadata(rows, metadata)

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    @staticmethod
    def _attach_metadata(
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

    @classmethod
    def _concat_frames(
        cls, frames: list[pd.DataFrame | gpd.GeoDataFrame]
    ) -> pd.DataFrame | gpd.GeoDataFrame:
        """Stack frames row-wise, returning a GeoDataFrame if any stacked one is.

        Empty frames are skipped (unless all are empty) so they don't affect
        the result's columns, dtypes, or type. ``pd.concat`` returns the type
        of the first frame, so the result is rebuilt as a GeoDataFrame per
        ``_geometry_spec``, and integer columns are restored per
        ``_restore_int_columns``.
        """
        frames = [f for f in frames if len(f)] or frames[:1]
        geometry = cls._geometry_spec(frames)
        out = pd.concat(frames) if len(frames) > 1 else frames[0]
        out = cls._restore_int_columns(out, frames)
        if geometry is None:
            return out
        name, crs = geometry
        return gpd.GeoDataFrame(out, geometry=name, crs=crs)

    @staticmethod
    def _error_frame(items: list[EditResultItem]) -> pd.DataFrame:
        """Return one row per item with its error dict flattened into columns.

        Keys become ``error_<snake_case_key>`` columns (``extendedCode`` →
        ``error_extended_code``). ``error_code``, ``error_description``,
        ``error_exception``, ``error_outcome_unknown``, and
        ``error_status_url`` are always present, with fixed dtypes; other keys
        follow in the order they appear, with dtypes from ``convert_dtypes``.
        Where ESRI sent no description (rolled-back batches carry ``message``
        and ``details`` instead), ``error_description`` is filled from those.
        """
        core_dtypes = {
            "code": "Int64",
            "description": "string",
            "exception": "string",
            "outcome_unknown": "boolean",
            "status_url": "string",
        }
        errors = pd.DataFrame(
            [item.error or {} for item in items], index=range(len(items))
        )
        errors = errors.rename(
            columns=lambda c: re.sub(r"(?<!^)(?=[A-Z])", "_", str(c)).lower()
        )
        extras = [c for c in errors.columns if c not in core_dtypes]
        errors = errors.reindex(columns=[*core_dtypes, *extras])
        described = errors["description"].fillna("") != ""
        errors["description"] = errors["description"].where(
            described, ApplyEditsResult._fallback_description(errors)
        )
        errors[extras] = errors[extras].convert_dtypes()
        return errors.astype(core_dtypes).add_prefix("error_")

    @staticmethod
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

    @staticmethod
    def _filter_values(
        values: str | Sequence[str] | None, allowed: tuple[str, ...], name: str
    ) -> set[str] | None:
        """Validate one ``filter`` argument and return its values as a set.

        Type checkers already reject invalid literals; this catches them at
        runtime for callers who pass untyped strings.

        Args:
            values: One value (e.g. ``"adds"``), a list of values, or None.
            allowed: Every valid value, i.e. ``get_args`` of the Literal.
            name: The argument name (e.g. ``"kinds"``), quoted in the error.

        Returns:
            The values as a set, or None when ``values`` is None (no filter).

        Raises:
            InvalidParameterError: If any value is not in ``allowed``. The
                message lists every invalid value and every valid one.
        """
        if values is None:
            return None
        items = {values} if isinstance(values, str) else set(values)
        invalid = sorted(str(v) for v in items - set(allowed))
        if invalid:
            raise InvalidParameterError(
                f"Invalid {name}: {', '.join(invalid)}. "
                f"Expected one of: {', '.join(allowed)}."
            )
        return items

    @classmethod
    def _from_esri_response(cls, body: dict) -> ApplyEditsResult:
        """Parse a single synchronous applyEdits response body.

        Args:
            body: Parsed JSON response dict from the applyEdits endpoint.

        Returns:
            ApplyEditsResult populated from addResults, updateResults, deleteResults.
        """
        return cls(
            add_results=[
                EditResultItem._from_esri(r) for r in body.get("addResults", [])
            ],
            update_results=[
                EditResultItem._from_esri(r) for r in body.get("updateResults", [])
            ],
            delete_results=[
                EditResultItem._from_esri(r) for r in body.get("deleteResults", [])
            ],
        )

    @staticmethod
    def _geometry_spec(
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

    @classmethod
    def _merge(cls, results: list[ApplyEditsResult]) -> ApplyEditsResult:
        """Merge per-batch ApplyEditsResults from one applyEdits call into one.

        Batches hold consecutive runs of each kind's inputs and come back with
        one item per input, so an item's index in its merged list is its row
        position in that kind's input frame. Each item is copied with that
        ``position`` and its ``kind``.

        Args:
            results: List of per-batch results in posting order.

        Returns:
            Single ApplyEditsResult with all items concatenated in order.
        """

        def numbered(kind: EditKind, items: list[EditResultItem]) -> list:
            """Copies of ``items`` with ``kind`` and their index as ``position``."""
            return [replace(i, kind=kind, position=n) for n, i in enumerate(items)]

        return cls(
            add_results=numbered("adds", [i for r in results for i in r.add_results]),
            update_results=numbered(
                "updates", [i for r in results for i in r.update_results]
            ),
            delete_results=numbered(
                "deletes", [i for r in results for i in r.delete_results]
            ),
        )

    def _metadata_frame(self) -> pd.DataFrame:
        """Return one row per item, in adds, updates, deletes order.

        Columns: ``kind`` and ``status`` (categoricals of the ``EditKind`` /
        ``EditStatus`` values), ``object_id`` (-1 when ESRI reports none),
        ``global_id``, ``position`` (null when unknown), then the error
        columns from ``_error_frame``.
        """
        items = self._items
        dtypes = {
            "kind": pd.CategoricalDtype(list(get_args(EditKind))),
            "status": pd.CategoricalDtype(list(get_args(EditStatus))),
            "object_id": "int64",
            "global_id": "string",
            "position": "Int64",
        }
        records = [
            (item.kind, item.status, item.object_id, item.global_id, item.position)
            for item in items
        ]
        core = pd.DataFrame.from_records(records, columns=list(dtypes)).astype(dtypes)
        return pd.concat([core, self._error_frame(items)], axis=1)

    @staticmethod
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
