"""ApplyEditsResult: aggregated response from an applyEdits operation."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from archibald.models.edit_result_item import EditResultItem

__all__ = ["ApplyEditsResult", "EditResultItem"]


@dataclass
class ApplyEditsResult:
    """Aggregated add/update/delete results across all applyEdits batches.

    Per-feature errors are captured in result items rather than raised as
    exceptions. Inspect ``has_failures`` and ``failed_*`` properties to detect
    partial failures without iterating manually.
    """

    add_results: list[EditResultItem]
    update_results: list[EditResultItem]
    delete_results: list[EditResultItem]

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
        return any(
            not r.success
            for r in self.add_results + self.update_results + self.delete_results
        )

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

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
