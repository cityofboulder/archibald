"""BaseLayer: shared layer resource base class for ESRI REST API layers."""

from __future__ import annotations

import dataclasses

from archibald.client import ArchieClient
from archibald.exceptions import LayerCapabilityError
from archibald.models.attachments_query_result import AttachmentsQueryResult
from archibald.models.fields_result import FieldsResult
from archibald.models.query_result import QueryResult
from archibald.operations.query import QueryOperation
from archibald.operations.query_attachments import QueryAttachmentsOperation
from archibald.services.base import BaseService


class BaseLayer(BaseService):
    """Abstract base for a single layer within an ESRI service.

    Provides layer init, metadata caching, field inspection, and query execution.
    Subclasses must define expected_type and may add editing support.
    """

    def __init__(self, client: ArchieClient, service_path: str, layer_id: int) -> None:
        """Construct a BaseLayer.

        Args:
            client: The ArchieClient instance.
            service_path: Service path validated by BaseService against expected_type.
            layer_id: Layer index within the service (e.g., 0, 1, 2).
        """
        super().__init__(client, service_path)
        self._layer_id = layer_id
        self._layer_path = f"{self._service_path}/{layer_id}"
        self._layer_metadata: dict | None = None
        self._query_op = QueryOperation(self)
        self._query_attachments_op = QueryAttachmentsOperation(self)

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
            The name of the OBJECTID field, used for pagination and often as a
            unique identifier for features.
        """
        metadata = await self._get_layer_metadata()
        return metadata.get("objectIdField", "OBJECTID")

    async def globalid_field(self) -> str | None:
        """Name of the GlobalID field for this layer, if present.

        Returns:
            The name of the GlobalID field, a UUID string used for unique
            identification across systems. None if not defined.
        """
        metadata = await self._get_layer_metadata()
        return metadata.get("globalIdField")

    async def supports_query(self) -> bool:
        """Whether this layer supports query operations.

        Returns:
            True if the layer's capabilities include querying, False otherwise.
        """
        metadata = await self._get_layer_metadata()
        return "query" in metadata.get("capabilities", "").lower()

    async def supports_attachments(self) -> bool:
        """Whether this layer supports file attachments.

        Returns:
            True if the layer metadata advertises hasAttachments=True.
        """
        metadata = await self._get_layer_metadata()
        return bool(metadata.get("hasAttachments", False))

    async def supports_query_attachments(self) -> bool:
        """Whether this layer supports the queryAttachments operation.

        Returns:
            True if the layer advertises supportsQueryAttachments in its
            advancedQueryCapabilities.
        """
        metadata = await self._get_layer_metadata()
        adv = metadata.get("advancedQueryCapabilities", {})
        return bool(adv.get("supportsQueryAttachments", False))

    async def supports_query_attachments_count_only(self) -> bool:
        """Whether this layer supports queryAttachments with returnCountOnly.

        Map service layers do not support returnCountOnly and omit this key.

        Returns:
            True if the layer advertises supportsQueryAttachmentsCountOnly in its
            advancedQueryCapabilities.
        """
        metadata = await self._get_layer_metadata()
        adv = metadata.get("advancedQueryCapabilities", {})
        return bool(adv.get("supportsQueryAttachmentsCountOnly", False))

    async def supports_query_attachments_order_by_fields(self) -> bool:
        """Whether this layer supports queryAttachments with orderByFields.

        Returns:
            True if the layer advertises supportsQueryAttachmentsOrderByFields in
            its advancedQueryCapabilities.
        """
        metadata = await self._get_layer_metadata()
        adv = metadata.get("advancedQueryCapabilities", {})
        return bool(adv.get("supportsQueryAttachmentsOrderByFields", False))

    async def fields(self) -> FieldsResult:
        """Field definitions from layer metadata.

        Returns:
            FieldsResult providing access to field names and definitions.
        """
        field_list = (await self._get_layer_metadata()).get("fields", [])
        return FieldsResult(fields=field_list)

    async def attachment_fields(self) -> FieldsResult:
        """Attachment table field definitions from layer metadata.

        Returns:
            FieldsResult built from the layer metadata's attachmentFields key,
            describing the columns available on each attachment.
        """
        field_list = (await self._get_layer_metadata()).get("attachmentFields", [])
        return FieldsResult(fields=field_list)

    async def attachment_properties(self) -> list[dict]:
        """Attachment property crosswalk from layer metadata.

        Returns:
            The layer metadata's attachmentProperties list. Each entry maps a
            camelCase queryAttachments response property (``name``) to its ESRI
            attachment-table field (``fieldName``) and carries an ``isEnabled``
            flag. Empty list when the layer omits the key.
        """
        return (await self._get_layer_metadata()).get("attachmentProperties", [])

    async def query(
        self,
        where: str = "1=1",
        out_fields: list[str] | str | None = None,
        return_geometry: bool = True,
        out_sr: int | None = None,
        apply_coded_values: bool = False,
        **kwargs,
    ) -> QueryResult:
        """Execute a query on this layer.

        Args:
            where: WHERE clause (default "1=1" returns all features).
            out_fields: Field names to return. Can be None (→ all), a list, or
                a comma-separated string.
            return_geometry: Include feature geometries in the response.
            out_sr: Output spatial reference (EPSG code) for geometries.
            apply_coded_values: When True, ``to_frame()`` and
                ``to_geodataframe()`` methods in the QueryResult will replace coded
                domain values with their human-readable names automatically.
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

        result = await self._query_op.execute(
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            out_sr=out_sr,
            **kwargs,
        )

        if apply_coded_values:
            result = dataclasses.replace(result, apply_coded_values=True)
        return result

    async def query_attachments(
        self,
        *,
        object_ids: list[int] | str | None = None,
        global_ids: list[str] | str | None = None,
        definition_expression: str | None = None,
        attachments_definition_expression: str | None = None,
        attachment_types: list[str] | str | None = None,
        size: tuple[int, ...] | list[int] | str | None = None,
        keywords: list[str] | str | None = None,
        return_url: bool | None = None,
        return_metadata: bool | None = None,
        order_by_fields: str | None = None,
        result_offset: int | None = None,
        result_record_count: int | None = None,
        return_count_only: bool = False,
        **kwargs,
    ) -> AttachmentsQueryResult:
        """Query attachments on this layer.

        Works on both feature service and map service layers. Each ESRI
        queryAttachments parameter is exposed as a named argument. ``return_count_only``
        is only supported on feature service layers.

        At least one feature selector — ``object_ids``, ``global_ids``, or
        ``definition_expression`` — must be supplied. ``object_ids`` and
        ``global_ids`` are mutually exclusive: ESRI silently ignores
        ``object_ids`` when ``global_ids`` is given, so supplying both raises
        rather than dropping one.

        Args:
            object_ids: Parent feature OBJECTIDs to query. Mutually exclusive with
                global_ids; ignored by the server when global_ids is also supplied.
            global_ids: Parent feature GlobalIDs to query. Mutually exclusive with
                object_ids.
            definition_expression: SQL expression filtering parent features.
            attachments_definition_expression: SQL expression filtering attachments.
            attachment_types: Attachment file types to return (e.g. ["jpeg", "pdf"]).
            size: Attachment file size filter in bytes. A single minimum
                (``(1000,)`` or ``"1000"``) returns attachments at least that
                large; a ``(min, max)`` pair or ``"min,max"`` string returns a
                range. A max-only range (``",1000"``) is rejected since the server
                ignores it.
            keywords: Filter attachments by keyword. A single string or a list of
                strings (comma-joined).
            return_url: Include attachment download URLs.
            return_metadata: Include EXIF metadata when available.
            order_by_fields: Fields to sort attachments by.
            result_offset: Number of attachments to skip (pagination).
            result_record_count: Maximum number of attachments to return.
            return_count_only: Return only per-feature attachment counts.
            **kwargs: Additional raw API parameters passed through unchanged.

        Returns:
            AttachmentsQueryResult with attachment groups and field metadata.

        Raises:
            LayerCapabilityError: If the layer does not support queryAttachments, or
                if return_count_only is requested but unsupported (e.g. map layers).
            InvalidParameterError: If no feature selector is supplied, if both
                object_ids and global_ids are supplied, if size is malformed, if
                keywords or return_metadata is requested while the layer disables
                the corresponding property, or if order_by_fields is supplied while
                the layer does not support it.
        """
        if not await self.supports_query_attachments():
            raise LayerCapabilityError(
                f"Layer {self._layer_path} does not support querying attachments."
            )
        if return_count_only and not await self.supports_query_attachments_count_only():
            raise LayerCapabilityError(
                f"Layer {self._layer_path} does not support querying attachment "
                "counts only."
            )

        return await self._query_attachments_op.execute(
            object_ids=object_ids,
            global_ids=global_ids,
            definition_expression=definition_expression,
            attachments_definition_expression=attachments_definition_expression,
            attachment_types=attachment_types,
            size=size,
            keywords=keywords,
            return_url=return_url,
            return_metadata=return_metadata,
            order_by_fields=order_by_fields,
            result_offset=result_offset,
            result_record_count=result_record_count,
            return_count_only=return_count_only,
            **kwargs,
        )
