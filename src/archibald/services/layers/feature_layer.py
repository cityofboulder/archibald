"""FeatureLayer: API for a single layer within an ESRI FeatureServer."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Iterable

import geopandas as gpd
import pandas as pd

from archibald.client import ArchieClient
from archibald.exceptions import InvalidParameterError, LayerCapabilityError
from archibald.models.apply_edits_result import ApplyEditsResult
from archibald.models.attachments_result import AttachmentsResult
from archibald.operations.attachments import (
    AddAttachmentsOperation,
    DeleteAttachmentsOperation,
    UpdateAttachmentsOperation,
)
from archibald.operations.apply_edits import ApplyEditsOperation
from archibald.services.feature_service import FeatureService
from archibald.services.layers.base import BaseLayer


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
        self._add_attachments_op = AddAttachmentsOperation(self)
        self._update_attachments_op = UpdateAttachmentsOperation(self)
        self._delete_attachments_op = DeleteAttachmentsOperation(self)

    # ------------------------------------------------------------------
    # Capability checks
    # ------------------------------------------------------------------

    async def supports_apply_edits(self) -> bool:
        """Whether this layer supports applyEdits operations.

        Returns:
            True if the layer's capabilities include editing.
        """
        metadata = await self._get_layer_metadata()
        return "editing" in metadata.get("capabilities", "").lower()

    async def supports_update(self) -> bool:
        """Whether this layer supports updating existing features and attachments.

        Returns:
            True if the layer's capabilities include the Update operation.
        """
        metadata = await self._get_layer_metadata()
        return "update" in metadata.get("capabilities", "").lower()

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

    # ------------------------------------------------------------------
    # Attachment operations
    # ------------------------------------------------------------------

    async def add_attachments(
        self,
        object_ids: int | Iterable[int],
        files: Path | BinaryIO | bytes | Iterable[Path | BinaryIO | bytes],
        filenames: str | None | Iterable[str | None] = None,
        content_types: str | None | Iterable[str | None] = None,
    ) -> AttachmentsResult:
        """Attach one or more files to one or more features.

        Accepts three calling modes:

        * **Single** — one ``int`` object_id and one file object: attach a
          single file to one feature.
        * **Fan-out** — one ``int`` object_id and an iterable of files: attach
          multiple files to the same feature concurrently.
        * **Multi** — iterables of object_ids and files: attach one file per
          feature, all concurrently. Object IDs may be repeated to attach
          multiple files to the same feature.

        Args:
            object_ids: Feature OBJECTID(s) to attach files to.
            files: File(s) to attach. Each item may be a pathlib.Path, an open
                binary file object, or raw bytes.
            filenames: Filename override(s). In single mode, a plain ``str``
                (or ``None`` to auto-detect). In fan-out / multi mode, an
                iterable of per-item overrides (or ``None`` to auto-detect
                all). Required per-item for any raw bytes entries.
            content_types: MIME type override(s). When omitted or ``None`` for
                an item, the type is guessed from the resolved filename and
                falls back to ``application/octet-stream``.

        Returns:
            AttachmentsResult with one result per input file, in input order.

        Raises:
            LayerCapabilityError: If the layer does not support attachments.
            InvalidParameterError: If any iterables differ in length, or if a
                bytes file has no resolvable filename.
        """
        if not await self.supports_attachments():
            raise LayerCapabilityError(
                f"Layer {self._layer_path} does not support attachments."
            )
        oids, fs, fns, cts, _ = self._normalize_attachment_inputs(
            object_ids, files, filenames, content_types
        )
        return await self._add_attachments_op.execute(oids, fs, fns, cts)

    async def update_attachments(
        self,
        object_ids: int | Iterable[int],
        attachment_ids: int | Iterable[int],
        files: Path | BinaryIO | bytes | Iterable[Path | BinaryIO | bytes],
        filenames: str | None | Iterable[str | None] = None,
        content_types: str | None | Iterable[str | None] = None,
    ) -> AttachmentsResult:
        """Replace the files of one or more existing attachments.

        Accepts three calling modes:

        * **Single** — scalar ``object_id``, ``attachment_id``, and one file:
          replace a single attachment on one feature.
        * **Fan-out** — scalar ``object_id``, an iterable of ``attachment_ids``
          and an iterable of files: replace multiple attachments on the same
          feature concurrently.
        * **Multi** — iterables of object_ids, attachment_ids, and files:
          replace one attachment per entry, all concurrently. Object IDs may be
          repeated when updating multiple attachments on the same feature.

        Args:
            object_ids: Feature OBJECTID(s) owning the attachments.
            attachment_ids: ID(s) of the existing attachments to replace.
            files: Replacement file(s). Each item may be a pathlib.Path, an
                open binary file object, or raw bytes.
            filenames: Filename override(s). In single mode, a plain ``str``
                (or ``None`` to auto-detect). In fan-out / multi mode, an
                iterable of per-item overrides (or ``None`` to auto-detect
                all). Required per-item for any raw bytes entries.
            content_types: MIME type override(s). When omitted or ``None`` for
                an item, the type is guessed from the resolved filename and
                falls back to ``application/octet-stream``.

        Returns:
            AttachmentsResult with one result per input file, in input order.

        Raises:
            LayerCapabilityError: If the layer does not support attachments or
                does not support updating.
            InvalidParameterError: If any iterables differ in length, or if a
                bytes file has no resolvable filename.
        """
        await self._require_attachment_update_support()
        oids, fs, fns, cts, att_ids = self._normalize_attachment_inputs(
            object_ids, files, filenames, content_types, attachment_ids
        )
        return await self._update_attachments_op.execute(oids, fs, fns, cts, att_ids)

    async def delete_attachments(
        self,
        object_ids: int | Iterable[int],
        attachment_ids: int | Iterable[int],
    ) -> AttachmentsResult:
        """Delete one or more attachments from one or more features.

        Pairs are grouped by OBJECTID so that all attachments on the same
        feature are removed in a single request.

        Accepts three calling modes:

        * **Single** — scalar ``object_id`` and ``attachment_id``: delete one
          attachment from one feature.
        * **Fan-out** — scalar ``object_id`` and an iterable of
          ``attachment_ids``: delete multiple attachments from the same feature
          in a single batched request.
        * **Multi** — iterables of object_ids and attachment_ids: delete one
          attachment per pair, concurrently. Object IDs may be repeated when
          deleting multiple attachments from the same feature.

        Args:
            object_ids: Feature OBJECTID(s) whose attachments are being deleted.
            attachment_ids: Attachment ID(s) to delete, one per object_id entry.

        Returns:
            AttachmentsResult with one result per input pair, in input order.

        Raises:
            LayerCapabilityError: If the layer does not support attachments.
            InvalidParameterError: If object_ids and attachment_ids differ in length.
        """
        if not await self.supports_attachments():
            raise LayerCapabilityError(
                f"Layer {self._layer_path} does not support attachments."
            )
        oids, att_ids = self._normalize_delete_inputs(object_ids, attachment_ids)
        return await self._delete_attachments_op.execute(oids, att_ids)

    # ------------------------------------------------------------------
    # Edit operations
    # ------------------------------------------------------------------

    async def apply_edits(
        self,
        adds: pd.DataFrame | gpd.GeoDataFrame | None = None,
        updates: pd.DataFrame | gpd.GeoDataFrame | None = None,
        deletes: pd.DataFrame | pd.Series | list[int] | None = None,
        *,
        rollback_on_failure: bool = False,
        apply_coded_values: bool = False,
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
            apply_coded_values: When True, translate human-readable domain names
                in the DataFrame back to their raw codes before serialization.

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
            apply_coded_values=apply_coded_values,
        )

    async def append(
        self,
        df: pd.DataFrame | gpd.GeoDataFrame,
        *,
        apply_coded_values: bool = False,
    ) -> ApplyEditsResult:
        """Add all rows in df as new features.

        Convenience wrapper around apply_edits(adds=df). Raises LayerCapabilityError
        if the layer does not support applyEdits.

        Args:
            df: Rows to add. OBJECTIDs are excluded from the payload.
            apply_coded_values: When True, translate human-readable domain names
                back to their raw codes before serialization.

        Returns:
            ApplyEditsResult with add results for each row.
        """
        return await self.apply_edits(adds=df, apply_coded_values=apply_coded_values)

    async def upsert(
        self,
        df: pd.DataFrame | gpd.GeoDataFrame,
        key_fields: list[str],
        *,
        apply_coded_values: bool = False,
    ) -> ApplyEditsResult:
        """Add new features and update existing features matched by key_fields.

        Performs a slim query (key fields + OBJECTID, no geometry) to build an
        existing-key index, then partitions df into adds (keys absent from the
        layer) and updates (keys present, with OBJECTID injected). Never deletes.

        Args:
            df: Source DataFrame or GeoDataFrame.
            key_fields: Column names whose combined values uniquely identify a
                feature. Used to match rows in df against existing layer features.
            apply_coded_values: When True, translate human-readable domain names
                back to their raw codes before serialization.

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
            apply_coded_values=apply_coded_values,
        )

    async def sync(
        self,
        df: pd.DataFrame | gpd.GeoDataFrame,
        key_fields: list[str],
        *,
        apply_coded_values: bool = False,
    ) -> ApplyEditsResult:
        """Full sync: add new features, update existing features, delete removed features.

        Same diff logic as upsert, plus features present in the layer but absent
        from df are collected as deletes. After sync, the layer's keyed contents
        exactly mirror df.

        Args:
            df: Source DataFrame or GeoDataFrame representing the desired state.
            key_fields: Column names whose combined values uniquely identify a
                feature. Used to match rows in df against existing layer features.
            apply_coded_values: When True, translate human-readable domain names
                back to their raw codes before serialization.

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
            apply_coded_values=apply_coded_values,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_attachment_inputs(
        object_ids: int | Iterable[int],
        files: Path | BinaryIO | bytes | Iterable[Path | BinaryIO | bytes],
        filenames: str | None | Iterable[str | None] = None,
        content_types: str | None | Iterable[str | None] = None,
        attachment_ids: int | Iterable[int] | None = None,
    ) -> tuple[
        Iterable[int],
        Iterable[Path | BinaryIO | bytes],
        Iterable[str | None] | None,
        Iterable[str | None] | None,
        Iterable[int] | None,
    ]:
        """Normalize attachment inputs across single, fan-out, and multi modes.

        Single mode (scalar object_id + single file): wraps all scalars in lists.
        Fan-out mode (scalar object_id + iterable files): broadcasts object_id.
        Multi mode (iterable object_ids): passes all arguments through unchanged.

        Args:
            object_ids: Scalar or iterable of feature OBJECTIDs.
            files: Single file or iterable of files.
            filenames: Scalar filename (single mode) or iterable (fan-out/multi).
            content_types: Scalar MIME type (single mode) or iterable (fan-out/multi).
            attachment_ids: Scalar or iterable of attachment IDs (update only).

        Returns:
            Tuple of (object_ids, files, filenames, content_types, attachment_ids)
            suitable for passing directly to an attachment operation's execute().
        """
        single_file = isinstance(files, (Path, bytes)) or hasattr(files, "read")
        single_oid = isinstance(object_ids, int)

        if single_oid and single_file:
            return (
                [object_ids],
                [files],
                [filenames],
                [content_types],
                [attachment_ids] if attachment_ids is not None else None,
            )  # type: ignore

        if single_oid:
            fs = list(files)  # type: ignore
            return (
                [object_ids] * len(fs),
                fs,
                filenames,
                content_types,
                attachment_ids,
            )  # type: ignore

        return object_ids, files, filenames, content_types, attachment_ids  # type: ignore

    @staticmethod
    def _normalize_delete_inputs(
        object_ids: int | Iterable[int],
        attachment_ids: int | Iterable[int],
    ) -> tuple[Iterable[int], Iterable[int]]:
        """Normalize delete inputs across single, fan-out, and multi modes.

        Single mode (both scalars): wraps in lists.
        Fan-out mode (scalar object_id + iterable attachment_ids): broadcasts object_id.
        Multi mode (iterable object_ids): passes both arguments through unchanged.

        Args:
            object_ids: Scalar or iterable of feature OBJECTIDs.
            attachment_ids: Scalar or iterable of attachment IDs.

        Returns:
            Tuple of (object_ids, attachment_ids) suitable for
            DeleteAttachmentsOperation.execute().
        """
        single_oid = isinstance(object_ids, int)
        single_att = isinstance(attachment_ids, int)

        if single_oid and single_att:
            return [object_ids], [attachment_ids]

        if single_oid:
            return [object_ids] * len(attachment_ids), attachment_ids  # type: ignore

        return object_ids, attachment_ids  # type: ignore

    async def _require_attachment_update_support(self) -> None:
        """Raise unless the layer supports both attachments and updating.

        Raises:
            LayerCapabilityError: If the layer does not support attachments or
                does not support updating.
        """
        if not await self.supports_attachments():
            raise LayerCapabilityError(
                f"Layer {self._layer_path} does not support attachments."
            )
        if not await self.supports_update():
            raise LayerCapabilityError(
                f"Layer {self._layer_path} does not support updating attachments."
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
        existing_result = await self.query(
            out_fields=query_fields, return_geometry=False
        )
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
