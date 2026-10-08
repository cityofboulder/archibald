"""EditResultItem: single per-feature result from an applyEdits or addAttachment operation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EditResultItem:
    """Single per-feature result from an applyEdits or addAttachment operation."""

    object_id: int
    global_id: str | None
    success: bool
    error: dict | None  # raw ESRI error dict when success=False; None otherwise

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
    ) -> EditResultItem:
        """Build a failed item from an exception that produced no ESRI result.

        The error dict mirrors ESRI's per-item ``code``/``description`` shape and
        adds ``exception`` (the exception class name) and ``outcome_unknown``
        (True when the request may have reached the server, so it may have been
        applied despite the failure).

        Args:
            exc: The exception that prevented a result from being obtained.
            object_id: ID to report on the item; -1 when none is known.
            outcome_unknown: Whether the server may have processed the request.
        """
        return cls(
            object_id=object_id,
            global_id=None,
            success=False,
            error={
                "code": getattr(exc, "code", -1),
                "description": str(exc) or type(exc).__name__,
                "exception": type(exc).__name__,
                "outcome_unknown": outcome_unknown,
            },
        )
