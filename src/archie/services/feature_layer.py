"""FeatureLayer: API for a single layer within an ESRI FeatureServer."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from archie.client import ArchieClient
from archie.exceptions import InvalidParameterError, LayerCapabilityError
from archie.models.apply_edits_result import ApplyEditsResult
from archie.models.fields_result import FieldsResult
from archie.models.query_result import QueryResult
from archie.operations.apply_edits import ApplyEditsOperation
from archie.operations.query import QueryOperation
from archie.services.feature_service import FeatureService


class FeatureLayer(FeatureService):
    """Single layer within an ESRI FeatureServer service.

    Represents a layer at a specific index (e.g., /FeatureServer/0). Inherits
    service-level properties (CRS, max_record_count, etc.) from FeatureService.
    Provides layer-specific metadata and delegates query/edit operations to
    corresponding operation classes (QueryOperation, ApplyEditsOperation).
    """

    def __init__(self, client: ArchieClient, service_path: str, layer_id: int) -> None:
        """Construct a FeatureLayer.

        Args:
            client: The ArchieClient instance.
            service_path: Service path ending in FeatureServer (e.g.,
                "services/MyService/FeatureServer"). Validated by parent FeatureService.
            layer_id: Layer index within the service (e.g., 0, 1, 2).
        """
        super().__init__(client, service_path)
        self._layer_id = layer_id
        self._layer_path = f"{self._service_path}/{layer_id}"
        self._layer_metadata: dict | None = None

        # Operations
        self._query_op = QueryOperation(self)
        self._apply_edits_op = ApplyEditsOperation(self)

    async def _get_layer_metadata(self) -> dict:
        """Fetch and cache layer-level metadata JSON.

        Subsequent calls return the cached result without I/O.
        """
        if self._layer_metadata is None:
            response = await self._client.get(endpoint=self._layer_path)
            self._layer_metadata = response.json()
        return self._layer_metadata  # type: ignore[return-value]

    async def objectid_field(self) -> str:
        """Name of the OBJECTID field for this layer.

        Returns:
            The name of the OBJECTID field, which is used for pagination and
            often as a unique identifier for features.
        """
        metadata = await self._get_layer_metadata()
        return metadata.get("objectIdField", "OBJECTID")

    async def globalid_field(self) -> str | None:
        """Name of the GlobalID field for this layer, if present.

        Returns:
            The name of the GlobalID field, which is a UUID string used for
            unique identification across systems. May be None if not defined.
        """
        metadata = await self._get_layer_metadata()
        return metadata.get("globalIdField")

    async def supports_query(self) -> bool:
        """Whether this layer supports query operations.

        Returns:
            True if the layer supports queries, False otherwise.
        """
        metadata = await self._get_layer_metadata()
        return "query" in metadata.get("capabilities", "").lower()

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

    async def fields(self) -> FieldsResult:
        """Field definitions from layer metadata.

        Returns:
            FieldsResult providing access to field names and definitions.
        """
        field_list = (await self._get_layer_metadata()).get("fields", [])
        return FieldsResult(fields=field_list)

    async def query(
        self,
        where: str = "1=1",
        out_fields: list[str] | str | None = None,
        return_geometry: bool = True,
        out_sr: int | None = None,
        **kwargs,
    ) -> QueryResult:
        """Execute a query on this layer.

        Args:
            where: WHERE clause (default "1=1" returns all features).
            out_fields: Field names to return. Can be None (→ all), a list, or
                a comma-separated string.
            return_geometry: Include feature geometries in the response.
            out_sr: Output spatial reference (EPSG code) for geometries.
            **kwargs: Additional query parameters (e.g., orderByFields, resultType).

        Returns:
            QueryResult with aggregated features, field definitions, and geometry type.

        Raises:
            InvalidParameterError: If out_fields contains unknown field names.
            LayerCapabilityError: If the layer does not support query operations.
        """
        if not await self.supports_query():
            raise LayerCapabilityError(
                f"Layer {self._layer_path} does not support query operations."
            )

        return await self._query_op.execute(
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            out_sr=out_sr,
            **kwargs,
        )

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
        updates[objectid_field] = input_keys[updates_mask].map(key_to_oid)

        deletes = existing_df[~existing_keys.isin(input_keys)][objectid_field].tolist()

        return adds, updates, deletes