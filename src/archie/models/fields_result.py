"""FieldsResult: wraps layer field definitions from ESRI metadata."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class FieldsResult:
    """Layer field definitions and metadata from ESRI response.

    Provides access to field names (all or editable-only) and field definitions
    as a DataFrame.
    """

    fields: list[dict]

    def names(self, *, editable_only: bool = False) -> list[str]:
        """Return field names, optionally filtered to editable fields only.

        Args:
            editable_only: If True, only return names of fields where editable=True.

        Returns:
            List of field names.
        """
        if editable_only:
            return [f["name"] for f in self.fields if f.get("editable", False)]
        return [f["name"] for f in self.fields]

    def esri_field_types(self) -> dict[str, str]:
        """Return a mapping of field names to their types."""
        return {f["name"]: f["type"] for f in self.fields}

    def to_frame(self) -> pd.DataFrame:
        """Return field definitions as a DataFrame (one row per field)."""
        return pd.DataFrame(self.fields)
