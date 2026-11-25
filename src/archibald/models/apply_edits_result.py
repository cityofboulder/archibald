"""ApplyEditsResult: aggregated response from an applyEdits operation."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field, replace
from typing import get_args

import geopandas as gpd
import pandas as pd

from archibald.exceptions import InvalidParameterError
from archibald.models._literals import validate_literal_values
from archibald.models.edit_result_item import EditKind, EditResultItem, EditStatus
from archibald.serializers._frames import attach_metadata, concat_frames, error_frame

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
        kind_set = validate_literal_values(kinds, EditKind, "kinds")
        status_set = validate_literal_values(statuses, EditStatus, "statuses")
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
        rows = concat_frames(
            [
                frame.iloc[positions[meta["kind"] == kind].to_numpy()]
                for kind, frame in self._inputs.items()
            ]
        )
        if not include_metadata:
            return rows
        metadata = meta.drop(columns="position").add_prefix(metadata_prefix)
        return attach_metadata(rows, metadata)

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

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
        columns from ``error_frame``.
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
        return pd.concat([core, error_frame([item.error for item in items])], axis=1)
