"""FeatureLayer: API for a single layer within an ESRI FeatureServer."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from archie.client import ArchieClient
from archie.exceptions import InvalidParameterError, LayerCapabilityError
from archie.models.apply_edits_result import ApplyEditsResult
from archie.operations.apply_edits import ApplyEditsOperation
from archie.services.feature_service import FeatureService
from archie.services.layers.base import BaseLayer


class FeatureLayer(FeatureService, BaseLayer):
    """Single layer within an ESRI FeatureServer service.

    Inherits FeatureServer path validation from FeatureService and shared layer
    capability (metadata caching, field inspection, querying) from BaseLayer.
    Adds editing operations (applyEdits, upsert, sync).
    """

    def __init__(self, client: ArchieClient, service_path: str, layer_id: int) -> None:
        """Construct a FeatureLayer.

        Args:
            client: The ArchieClient instance.
            service_path: Service path ending in FeatureServer (e.g.,
                "services/MyService/FeatureServer"). Validated by FeatureService.
            layer_id: Layer index within the service (e.g., 0, 1, 2).
        """
        super().__init__(client, service_path, layer_id)
        self._apply_edits_op = ApplyEditsOperation(self)

    async def supports_apply_edits(self) -> bool:
        """Whether this layer supports applyEdits operations.

        Returns:
            True if the layer's capabilities include editing.
        """
        metadata = await self._get_layer_metadata()
        return "editing" in metadata.get("capabilities", "").lower()

    async def supports_rollback_on_failure(self) -> bool:
        """Whether this layer supports the rollbackOnFailure parameter.

        Returns:
            True if the layer advertises supportsRollbackOnFailureParameter in
            its advancedEditingCapabilities.
        """
        metadata = await self._get_layer_metadata()
        adv = metadata.get("advancedEditingCapabilities", {})
        return bool(adv.get("supportsRollbackOnFailureParameter", False))

    async def supports_async_apply_edits(self) -> bool:
        """Whether this layer supports server-side async applyEdits processing.

        Returns:
            True if the layer advertises supportsAsyncApplyEdits in its
            advancedEditingCapabilities.
        """
        metadata = await self._get_layer_metadata()
        adv = metadata.get("advancedEditingCapabilities", {})
        return bool(adv.get("supportsAsyncApplyEdits", False))

    async def apply_edits(
        self,
        adds: pd.DataFrame | gpd.GeoDataFrame | None = None,
        updates: pd.DataFrame | gpd.GeoDataFrame | None = None,
        deletes: pd.DataFrame | pd.Series | list[int] | None = None,
        *,
        rollback_on_failure: bool = False,
    ) -> ApplyEditsResult:
        """Add, update, and/or delete features in a single batched operation.

        Validates that the layer supports applyEdits, then delegates all
        serialization, batching, and posting to ApplyEditsOperation.

        Args:
            adds: Rows to add as new features. OBJECTIDs are excluded.
            updates: Rows to update (must include the OBJECTID column).
            deletes: OBJECTIDs to delete — list[int], DataFrame with an OBJECTID
                column, or a Series of integer OBJECTIDs.
            rollback_on_failure: Request server-side rollback on failure. Silently
                degraded to False with a warning if the layer does not support it.

        Returns:
            ApplyEditsResult with all add, update, and delete results merged.

        Raises:
            LayerCapabilityError: If the layer does not support edit operations.
        """
        if not await self.supports_apply_edits():
            raise LayerCapabilityError(
                f"Layer {self._layer_path} does not support edit operations."
            )
        return await self._apply_edits_op.execute(
            adds=adds,
            updates=updates,
            deletes=deletes,
            rollback_on_failure=rollback_on_failure,
        )

    async def append(
        self,
        df: pd.DataFrame | gpd.GeoDataFrame,
    ) -> ApplyEditsResult:
        """Add all rows in df as new features.

        Convenience wrapper around apply_edits(adds=df). Raises LayerCapabilityError
        if the layer does not support applyEdits.

        Args:
            df: Rows to add. OBJECTIDs are excluded from the payload.

        Returns:
            ApplyEditsResult with add results for each row.
        """
        return await self.apply_edits(adds=df)

    async def upsert(
        self,
        df: pd.DataFrame | gpd.GeoDataFrame,
        key_fields: list[str],
    ) -> ApplyEditsResult:
        """Add new features and update existing features matched by key_fields.

        Performs a slim query (key fields + OBJECTID, no geometry) to build an
        existing-key index, then partitions df into adds (keys absent from the
        layer) and updates (keys present, with OBJECTID injected). Never deletes.

        Args:
            df: Source DataFrame or GeoDataFrame.
            key_fields: Column names whose combined values uniquely identify a
                feature. Used to match rows in df against existing layer features.

        Returns:
            ApplyEditsResult with add and update results.

        Raises:
            LayerCapabilityError: If the layer does not support applyEdits or query operations.
            InvalidParameterError: If key_fields is invalid.
        """
        adds_df, updates_df, _ = await self._diff(df, key_fields)
        return await self.apply_edits(
            adds=adds_df if not adds_df.empty else None,
            updates=updates_df if not updates_df.empty else None,
        )

    async def sync(
        self,
        df: pd.DataFrame | gpd.GeoDataFrame,
        key_fields: list[str],
    ) -> ApplyEditsResult:
        """Full sync: add new features, update existing features, delete removed features.

        Same diff logic as upsert, plus features present in the layer but absent
        from df are collected as deletes. After sync, the layer's keyed contents
        exactly mirror df.

        Args:
            df: Source DataFrame or GeoDataFrame representing the desired state.
            key_fields: Column names whose combined values uniquely identify a
                feature. Used to match rows in df against existing layer features.

        Returns:
            ApplyEditsResult with add, update, and delete results.

        Raises:
            LayerCapabilityError: If the layer does not support applyEdits or query operations.
            InvalidParameterError: If key_fields is invalid.
        """
        adds_df, updates_df, delete_oids = await self._diff(df, key_fields)
        return await self.apply_edits(
            adds=adds_df if not adds_df.empty else None,
            updates=updates_df if not updates_df.empty else None,
            deletes=delete_oids if delete_oids else None,
        )

    @staticmethod
    def _validate_key_fields(
        df: pd.DataFrame | gpd.GeoDataFrame,
        key_fields: list[str],
    ) -> None:
        """Validate that key_fields can uniquely identify rows in df.

        Args:
            df: Input DataFrame or GeoDataFrame.
            key_fields: Column names that jointly identify a feature.

        Raises:
            InvalidParameterError: If key_fields is empty, contains unknown column names,
                or produces non-unique composite keys.
        """
        if not key_fields:
            raise InvalidParameterError("key_fields must not be empty.")

        missing = [f for f in key_fields if f not in df.columns]
        if missing:
            missing_repr = ", ".join(repr(f) for f in missing)
            raise InvalidParameterError(
                f"key_fields contains columns not present in df: {missing_repr}."
            )

        composite = df[key_fields].astype(str).agg("||".join, axis=1)
        dupes = composite[composite.duplicated()].unique().tolist()
        if dupes:
            raise InvalidParameterError(
                f"key_fields {key_fields!r} do not uniquely identify rows in df. "
                f"Duplicate key examples: {dupes[:5]}"
            )

    async def _diff(
        self,
        df: pd.DataFrame | gpd.GeoDataFrame,
        key_fields: list[str],
    ) -> tuple[pd.DataFrame, pd.DataFrame, list[int]]:
        """Shared diff logic for upsert and sync.

        Issues a slim query (key_fields + OBJECTID, no geometry) and builds
        composite key Series (field values joined by '||') for both the layer
        and the input df, then uses pandas membership checks to partition rows
        into adds, updates, and deletes. Automatically injects OBJECTIDs into the
        updates_df based on the query result.

        Args:
            df: Input DataFrame or GeoDataFrame to diff against the layer.
            key_fields: Column names that jointly identify a feature.

        Returns:
            Tuple of (adds_df, updates_df, delete_oids):
                adds_df: Rows whose composite key is absent from the layer.
                updates_df: Rows whose composite key is present in the layer, with
                    OBJECTID injected from the existing layer data.
                delete_oids: OIDs in the layer whose composite key is absent from df.

        Raises:
            InvalidParameterError: If key_fields fails the uniqueness gate (see _validate_key_fields).
        """
        self._validate_key_fields(df, key_fields)
        objectid_field = await self.objectid_field()

        query_fields = list(set([objectid_field, *key_fields]))
        existing_result = await self.query(out_fields=query_fields, return_geometry=False)
        existing_df = existing_result.to_frame()

        # Composite key Series: each row becomes "val1||val2||..."
        input_keys = df[key_fields].astype(str).agg("||".join, axis=1)
        existing_keys = existing_df[key_fields].astype(str).agg("||".join, axis=1)

        adds = df[~input_keys.isin(existing_keys)]

        updates_mask = input_keys.isin(existing_keys)
        key_to_oid = dict(zip(existing_keys, existing_df[objectid_field]))
        updates = df[updates_mask].copy()
        updates[objectid_field] = input_keys[updates_mask].map(key_to_oid)  # type: ignore

        deletes = existing_df[~existing_keys.isin(input_keys)][objectid_field].tolist()

        return adds, updates, deletes
