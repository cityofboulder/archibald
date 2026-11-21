"""ApplyEditsResult: aggregated response from an applyEdits operation."""

from __future__ import annotations

import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import get_args

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

    Built only by applyEdits, which sets every item's ``kind`` and stores
    each kind's input frame in ``_inputs``; an item's ``position`` is its row
    in that frame. ``_inputs`` is excluded from equality and repr.
    """

    add_results: list[EditResultItem]
    update_results: list[EditResultItem]
    delete_results: list[EditResultItem]
    _inputs: dict[EditKind, pd.DataFrame] = field(
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

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

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

    @classmethod
    def _merge(cls, results: list[ApplyEditsResult]) -> ApplyEditsResult:
        """Merge per-batch ApplyEditsResults from one applyEdits call into one.

        Args:
            results: List of per-batch results in posting order.

        Returns:
            Single ApplyEditsResult with all items concatenated in order.
        """
        return cls(
            add_results=[i for r in results for i in r.add_results],
            update_results=[i for r in results for i in r.update_results],
            delete_results=[i for r in results for i in r.delete_results],
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
