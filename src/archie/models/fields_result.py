"""FieldsResult: wraps layer field definitions from ESRI metadata."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

_ESRI_FIELD_TYPES = [
    "esriFieldTypeSmallInteger",
    "esriFieldTypeInteger",
    "esriFieldTypeBigInteger",
    "esriFieldTypeOID",
    "esriFieldTypeSingle",
    "esriFieldTypeDouble",
    "esriFieldTypeDate",
    "esriFieldTypeGUID",
    "esriFieldTypeGlobalID",
    "esriFieldTypeXML",
    "esriFieldTypeString",
    "esriFieldTypeGeometry",
    "esriFieldTypeBlob",
    "esriFieldTypeRaster"
]


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

    def filter(
        self,
        *,
        names: list[str] | None = None,
        types: list[str] | str | None = None,
        editable: bool | None = None,
        nullable: bool | None = None,
    ) -> FieldsResult:
        """Return a new FieldsResult matching all supplied criteria.

        ``names`` and ``types`` are mutually exclusive. Boolean filters
        (``editable``, ``nullable``) may be combined with either.

        Args:
            names: Retain only fields whose name is in this list.
            types: Retain only fields whose ESRI type matches. Accepts a
                single type string or a list of type strings. Types align with
                ESRI field types from the REST API, e.g. "esriFieldTypeString",
                "esriFieldTypeInteger", etc.
            editable: If True, retain only editable fields; if False, only
                non-editable.
            nullable: If True, retain only nullable fields; if False, only
                non-nullable. Fields without a ``nullable`` key are treated
                as nullable.

        Returns:
            A new FieldsResult containing only the fields that satisfy every
            supplied criterion.

        Raises:
            ValueError: If both ``names`` and ``types`` are provided.
            ValueError: If any value in ``types`` is not a valid ESRI field type.
        """
        if names is not None and types is not None:
            raise ValueError("names and types cannot be specified together.")

        if types is not None:
            type_values = [types] if isinstance(types, str) else list(types)
            invalid = [t for t in type_values if t not in _ESRI_FIELD_TYPES]
            if invalid:
                raise ValueError(
                    f"Invalid ESRI type(s): {', '.join(sorted(invalid))}. "
                    "Field types must match standard ESRI types found here: "
                    "https://developers.arcgis.com/enterprise-sdk/api-reference/net/esriFieldType/"
                )

        name_set = set(names) if names is not None else None
        type_set = (
            {types}
            if isinstance(types, str)
            else (set(types) if types is not None else None)
        )

        result = self.fields
        if name_set is not None:
            result = [f for f in result if f["name"] in name_set]
        if type_set is not None:
            result = [f for f in result if f.get("type") in type_set]
        if editable is not None:
            result = [f for f in result if f.get("editable", False) == editable]
        if nullable is not None:
            result = [f for f in result if f.get("nullable", True) == nullable]

        return FieldsResult(fields=result)

    def to_frame(self) -> pd.DataFrame:
        """Return field definitions as a DataFrame (one row per field)."""
        return pd.DataFrame(self.fields)
