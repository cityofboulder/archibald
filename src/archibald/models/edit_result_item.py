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
