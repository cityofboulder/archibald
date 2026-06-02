"""ApplyEditsResult: aggregated response from an applyEdits operation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EditResultItem:
    """Single per-feature result from an applyEdits operation."""

    object_id: int
    global_id: str | None
    success: bool
    error: dict | None  # raw ESRI error dict when success=False; None otherwise

    @classmethod
    def _from_esri(cls, item: dict) -> EditResultItem:
        """Parse one item from an ESRI addResults/updateResults/deleteResults list."""
        return cls(
            object_id=item.get("objectId", -1),
            global_id=item.get("globalId"),
            success=bool(item.get("success", False)),
            error=item.get("error"),
        )


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

    @property
    def has_failures(self) -> bool:
        """True if any add, update, or delete result reports success=False."""
        return any(
            not r.success
            for r in self.add_results + self.update_results + self.delete_results
        )

    @property
    def failed_adds(self) -> list[EditResultItem]:
        """Add results where success=False."""
        return [r for r in self.add_results if not r.success]

    @property
    def failed_updates(self) -> list[EditResultItem]:
        """Update results where success=False."""
        return [r for r in self.update_results if not r.success]

    @property
    def failed_deletes(self) -> list[EditResultItem]:
        """Delete results where success=False."""
        return [r for r in self.delete_results if not r.success]

    @classmethod
    def from_esri_response(cls, body: dict) -> ApplyEditsResult:
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
    def merge(cls, results: list[ApplyEditsResult]) -> ApplyEditsResult:
        """Merge multiple per-batch ApplyEditsResults into one aggregate.

        Args:
            results: List of per-batch results in posting order.

        Returns:
            Single ApplyEditsResult with all items concatenated in order.
        """
        add_results: list[EditResultItem] = []
        update_results: list[EditResultItem] = []
        delete_results: list[EditResultItem] = []
        for r in results:
            add_results.extend(r.add_results)
            update_results.extend(r.update_results)
            delete_results.extend(r.delete_results)
        return cls(
            add_results=add_results,
            update_results=update_results,
            delete_results=delete_results,
        )
