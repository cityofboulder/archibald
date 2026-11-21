"""EditResultItem: single per-feature result from an applyEdits or addAttachment operation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EditKind = Literal["adds", "updates", "deletes"]
"""Kind of edit an applyEdits result item belongs to."""

EditStatus = Literal["succeeded", "failed", "unknown"]
"""Outcome of a single edit, derived from ``success`` and ``error``."""


@dataclass
class EditResultItem:
    """Single per-feature result from an applyEdits or addAttachment operation.

    Attributes:
        object_id: OBJECTID ESRI reported, or -1 when there is none (e.g. a
            failed add).
        global_id: GlobalID ESRI reported, if any.
        success: Whether the edit succeeded.
        error: Raw ESRI error dict when ``success`` is False; None otherwise.
        kind: Which applyEdits list the item belongs to; None for attachment
            results.
        position: Row position of the item's source row in the input frame
            for its kind; None when unknown (attachment results, or results
            whose count did not match their input).
    """

    object_id: int
    global_id: str | None
    success: bool
    error: dict | None
    kind: EditKind | None = None
    position: int | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def status(self) -> EditStatus:
        """``"succeeded"``, ``"unknown"`` when the server may have applied it anyway,
        else ``"failed"``.

        Failures carrying an ESRI error dict have no ``outcome_unknown`` key and
        are therefore ``"failed"``: the server definitively rejected them.
        """
        if self.success:
            return "succeeded"
        if (self.error or {}).get("outcome_unknown"):
            return "unknown"
        return "failed"

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    @classmethod
    def _from_esri(cls, item: dict) -> EditResultItem:
        """Parse one item from an ESRI result list."""
        return cls(
            object_id=item.get("objectId", -1),
            global_id=item.get("globalId"),
            success=bool(item.get("success", False)),
            error=item.get("error"),
        )

    @classmethod
    def _from_exception(
        cls,
        exc: BaseException,
        *,
        object_id: int = -1,
        outcome_unknown: bool = False,
        status_url: str | None = None,
    ) -> EditResultItem:
        """Build a failed item from an exception that produced no ESRI result.

        The error dict mirrors ESRI's per-item ``code``/``description`` shape and
        adds ``exception`` (the exception class name) and ``outcome_unknown``
        (True when the request may have reached the server, so it may have been
        applied despite the failure). ``status_url`` is added only when given.

        Args:
            exc: The exception that prevented a result from being obtained.
            object_id: ID to report on the item; -1 when none is known.
            outcome_unknown: Whether the server may have processed the request.
            status_url: Async job status URL to report, if the request had one.
        """
        error = {
            "code": getattr(exc, "code", -1),
            "description": str(exc) or type(exc).__name__,
            "exception": type(exc).__name__,
            "outcome_unknown": outcome_unknown,
        }
        if status_url is not None:
            error["status_url"] = status_url
        return cls(object_id=object_id, global_id=None, success=False, error=error)
