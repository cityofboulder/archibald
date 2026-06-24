"""AttachmentsQueryResult: aggregated response from a queryAttachments operation."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import pandas as pd

_PARENT_COLUMNS: list[str] = ["parentObjectId", "parentGlobalId"]

# Response-only columns (added by request params such as returnUrl) that have no
# attachmentProperties crosswalk entry. Preserved as-is under either naming mode.
_EXTRA_COLUMNS: list[str] = ["url"]


@dataclass
class AttachmentsQueryResult:
    """Aggregated attachment groups and the layer's attachment-property crosswalk.

    The ESRI ``queryAttachments`` endpoint returns one ``attachmentGroup`` per
    parent feature. When ``return_count_only`` is False each group carries an
    ``attachmentInfos`` list (one entry per attachment); when True each group
    carries a single ``count``.

    ``attachment_properties`` is the layer metadata's ``attachmentProperties``
    list — the documented crosswalk mapping each camelCase response property
    (``name``) to its ESRI attachment-table field (``fieldName``), with an
    ``isEnabled`` flag indicating which columns the response actually contains.
    ``to_frame`` uses it to project the response onto a stable column schema and,
    optionally, to rename columns to their ESRI field names.
    """

    attachment_groups: list[dict]
    attachment_properties: list[dict]
    return_count_only: bool = False

    def to_frame(self, *, use_field_names: bool = False) -> pd.DataFrame:
        """Return the attachment groups as a pandas DataFrame.

        With ``return_count_only`` True, each row is one parent feature with its
        attachment ``count``. Otherwise each row is a single attachment, flattened
        from ``attachmentInfos`` with ``parentObjectId``/``parentGlobalId``
        propagated onto every row.

        Columns are projected onto the enabled entries of
        ``attachment_properties`` so that empty and non-empty results share an
        identical schema. By default columns use the camelCase response property
        names; with ``use_field_names`` True they are renamed to the ESRI
        attachment-table field names via the crosswalk. Response-only columns that
        have no crosswalk entry (e.g. ``url`` from ``return_url``) are preserved
        as-is under either naming mode.

        When ``attachment_properties`` is empty (the layer omits the metadata),
        the frame falls back to the raw response columns unchanged; requesting
        ``use_field_names`` in that case cannot be honored and emits a warning.

        Args:
            use_field_names: Rename columns from camelCase response properties to
                their ESRI attachment-table field names (e.g. ``name`` →
                ``ATT_NAME``).

        Returns:
            DataFrame with one row per attachment (or per parent feature when
            counting only).
        """
        field_map = self._coerce_fields(use_field_names=use_field_names)
        return self._build_dataframe(field_map)

    def _coerce_fields(self, *, use_field_names: bool) -> dict[str, str]:
        """Resolve the ordered source-to-output column mapping for ``to_frame``.

        Keys are the column names as they appear in the flattened response; values
        are the names they should carry in the output frame. An empty mapping
        signals the agnostic fallback (no crosswalk → return the response as-is).

        - Count-only results map the parent ids and ``count`` to themselves.
        - Without ``attachment_properties`` the mapping is empty; requesting
          ``use_field_names`` there warns, since no rename is possible.
        - Otherwise the parent ids map to themselves and each enabled property
          maps from its camelCase ``name`` to either that name or its ESRI
          ``fieldName``.

        Args:
            use_field_names: Whether enabled properties map to their ESRI field
                names rather than their camelCase property names.

        Returns:
            Ordered mapping of source column name to output column name.
        """
        if self.return_count_only:
            return {column: column for column in [*_PARENT_COLUMNS, "count"]}

        if not self.attachment_properties:
            if use_field_names:
                warnings.warn(
                    "use_field_names=True was requested but the layer exposes no "
                    "attachmentProperties; columns cannot be renamed to ESRI field "
                    "names and are returned as-is.",
                    stacklevel=2,
                )
            return {}

        key = "fieldName" if use_field_names else "name"
        field_map: dict[str, str] = {column: column for column in _PARENT_COLUMNS}
        for prop in self._enabled_properties():
            field_map[prop["name"]] = prop[key]
        return field_map

    def _build_dataframe(self, field_map: dict[str, str]) -> pd.DataFrame:
        """Build the output DataFrame from a source-to-output column mapping.

        An empty ``field_map`` returns the flattened response unchanged (agnostic
        fallback). Otherwise the response is projected onto the mapping's source
        columns — dropping echoed ESRI-name duplicates and disabled properties —
        any present ``_EXTRA_COLUMNS`` (e.g. ``url``) are appended, and the
        selected columns are renamed to their outputs. Empty results yield a frame
        carrying just the mapping's output columns.

        Args:
            field_map: Ordered source-to-output column mapping from
                ``_coerce_fields``.

        Returns:
            The assembled DataFrame.
        """
        if not field_map:
            if not self.attachment_groups:
                return pd.DataFrame(columns=_PARENT_COLUMNS)
            return self._normalize()

        if not self.attachment_groups:
            return pd.DataFrame(columns=list(field_map.values()))

        raw = (
            pd.DataFrame(self.attachment_groups)
            if self.return_count_only
            else self._normalize()
        )
        extras = [c for c in _EXTRA_COLUMNS if c in raw.columns and c not in field_map]
        projected = raw.reindex(columns=[*field_map, *extras])
        return projected.rename(columns=field_map)

    def _enabled_properties(self) -> list[dict]:
        """Attachment properties flagged isEnabled (defaulting to enabled)."""
        return [p for p in self.attachment_properties if p.get("isEnabled", True)]

    def _normalize(self) -> pd.DataFrame:
        """Flatten attachmentInfos into one row per attachment with parent ids."""
        return pd.json_normalize(
            self.attachment_groups,
            record_path="attachmentInfos",
            meta=["parentObjectId", "parentGlobalId"],
        )
