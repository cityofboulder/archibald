"""QueryAttachmentsOperation: execute queryAttachments against a layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from archibald.exceptions import InvalidParameterError
from archibald.models.attachments_query_result import AttachmentsQueryResult

if TYPE_CHECKING:
    from archibald.services import BaseLayer


class QueryAttachmentsOperation:
    """Execute queryAttachments on a BaseLayer.

    Holds a reference to its owning layer to access the client, layer path, and
    attachment property metadata. Instantiated once at BaseLayer.__init__ time.
    """

    def __init__(self, layer: BaseLayer) -> None:
        self._layer = layer
        self._endpoint = f"{layer._layer_path}/queryAttachments"

    async def execute(
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
        """Execute a queryAttachments request and parse the response.

        Every ESRI queryAttachments parameter is exposed as a named argument and
        mapped to its camelCase API name. List values are comma-joined; booleans
        are stringified; None values are omitted. The ``f=json`` format is
        enforced by the client.

        Args:
            object_ids: Parent feature OBJECTIDs to query. Mutually exclusive with
                global_ids per ESRI.
            global_ids: Parent feature GlobalIDs to query.
            definition_expression: SQL expression filtering parent features.
            attachments_definition_expression: SQL expression filtering attachments.
            attachment_types: Attachment file types to return (e.g. ["jpeg", "pdf"]).
            size: Attachment file size filter in bytes. A single minimum
                (``(1000,)``, ``[1000]``, or ``"1000"``) returns attachments at
                least that large; a ``(min, max)`` pair or ``"min,max"`` string
                returns a range. A max-only range (``",1000"``) is rejected since
                the server ignores it.
            keywords: Filter attachments by keyword. A single string or a list of
                strings (comma-joined).
            return_url: Include attachment download URLs.
            return_metadata: Include EXIF metadata when available.
            order_by_fields: Fields to sort attachments by.
            result_offset: Number of attachments to skip (pagination).
            result_record_count: Maximum number of attachments to return.
            return_count_only: Return only per-feature attachment counts. Only
                supported on feature service layers.
            **kwargs: Additional raw API parameters passed through unchanged.

        Returns:
            AttachmentsQueryResult with the attachment groups, the layer's
            attachment-property crosswalk, and the return_count_only flag.

        Raises:
            InvalidParameterError: If no feature selector is supplied, if both
                object_ids and global_ids are supplied, if size has the wrong
                number of values or a missing minimum, if keywords or
                return_metadata is requested while the layer disables the
                corresponding property, or if order_by_fields is supplied while the
                layer does not support it.
        """
        attachment_properties = await self._layer.attachment_properties()

        await self._validate_params(
            object_ids=object_ids,
            global_ids=global_ids,
            definition_expression=definition_expression,
            size=size,
            keywords=keywords,
            return_metadata=return_metadata,
            order_by_fields=order_by_fields,
        )

        params = self._build_params(
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

        response = await self._layer._client.get(endpoint=self._endpoint, params=params)
        groups = response.json().get("attachmentGroups", [])

        return AttachmentsQueryResult(
            attachment_groups=groups,
            attachment_properties=attachment_properties,
            return_count_only=return_count_only,
        )

    async def _validate_params(
        self,
        *,
        object_ids: list[int] | str | None,
        global_ids: list[str] | str | None,
        definition_expression: str | None,
        size: tuple[int, ...] | list[int] | str | None,
        keywords: list[str] | str | None = None,
        return_metadata: bool | None = None,
        order_by_fields: str | None = None,
    ) -> None:
        """Validate parameter combinations before building the request.

        ESRI requires at least one feature selector (objectIds, globalIds, or
        definitionExpression). objectIds and globalIds are mutually exclusive: the
        server silently ignores objectIds when globalIds is supplied, so this
        raises rather than letting that surprise through. size may be a single
        minimum or a (min, max) pair (as a sequence or comma string); it must hold
        one or two values, contain no None entries (which serialize to the literal
        "None" the server rejects), and have a present minimum — a max-only range
        (e.g. ``",1000"``) is rejected because the server ignores it. keywords and
        return_metadata are rejected when the layer's attachmentProperties mark the
        ``keywords`` / ``exifInfo`` property as disabled, and order_by_fields is
        rejected when the layer does not advertise support for it, since the server
        cannot honor any of these.

        Args:
            object_ids: Parent feature OBJECTIDs, or None.
            global_ids: Parent feature GlobalIDs, or None.
            definition_expression: SQL expression filtering parent features, or None.
            size: Attachment file size filter, or None.
            keywords: Keyword filter (string or list of strings), or None.
            return_metadata: Whether EXIF metadata was requested, or None.
            order_by_fields: Attachment sort fields, or None.

        Raises:
            InvalidParameterError: If no feature selector is supplied, if both
                object_ids and global_ids are supplied, if size has the wrong
                number of values or a missing minimum, if keywords or
                return_metadata is requested while the layer disables the
                corresponding property, or if order_by_fields is supplied while the
                layer does not support it.
        """
        if object_ids is None and global_ids is None and definition_expression is None:
            raise InvalidParameterError(
                "queryAttachments requires at least one of object_ids, global_ids, "
                "or definition_expression."
            )

        if object_ids is not None and global_ids is not None:
            raise InvalidParameterError(
                "object_ids and global_ids are mutually exclusive; the server "
                "ignores object_ids when global_ids is supplied. Provide only one."
            )

        if size is not None:
            parts = size.split(",") if isinstance(size, str) else list(size)
            if not 1 <= len(parts) <= 2:
                raise InvalidParameterError(
                    "size must be a single minimum or a (min, max) pair of bytes; "
                    f"got {len(parts)} value(s)."
                )
            if any(part is None for part in parts):
                raise InvalidParameterError(
                    "size values must not be None; pass a single minimum like "
                    "(1000,) for an unbounded maximum."
                )
            minimum = parts[0]
            if isinstance(minimum, str) and not minimum.strip():
                raise InvalidParameterError(
                    "size must include a minimum value; a max-only range "
                    "(e.g. ',1000') is ignored by the server."
                )

        attachment_properties = await self._layer.attachment_properties()
        if keywords is not None:
            self._require_property_enabled(
                attachment_properties, "keywords", "keywords filtering"
            )
        if return_metadata:
            self._require_property_enabled(
                attachment_properties, "exifInfo", "EXIF metadata (return_metadata)"
            )

        supports_order_by_fields = (
            await self._layer.supports_query_attachments_order_by_fields()
        )
        if order_by_fields is not None and not supports_order_by_fields:
            raise InvalidParameterError(
                "order_by_fields is not supported: the layer does not advertise "
                "supportsQueryAttachmentsOrderByFields."
            )

    def _build_params(
        self,
        *,
        object_ids: list[int] | str | None,
        global_ids: list[str] | str | None,
        definition_expression: str | None,
        attachments_definition_expression: str | None,
        attachment_types: list[str] | str | None,
        size: tuple[int, ...] | list[int] | str | None,
        keywords: list[str] | str | None,
        return_url: bool | None,
        return_metadata: bool | None,
        order_by_fields: str | None,
        result_offset: int | None,
        result_record_count: int | None,
        return_count_only: bool,
        **kwargs,
    ) -> dict:
        """Map named arguments to ESRI camelCase query parameters.

        Lists are comma-joined, booleans are stringified to "true"/"false", and
        any argument left as None is omitted. Extra kwargs are merged first so
        explicit named arguments take precedence.

        Returns:
            Dict of queryAttachments parameters for the ESRI REST API.
        """
        params = kwargs.copy()

        params["returnCountOnly"] = "true" if return_count_only else "false"

        optional = {
            "objectIds": self._join(object_ids),
            "globalIds": self._join(global_ids),
            "definitionExpression": definition_expression,
            "attachmentsDefinitionExpression": attachments_definition_expression,
            "attachmentTypes": self._join(attachment_types),
            "size": self._join(size),
            "keywords": self._join(keywords),
            "orderByFields": order_by_fields,
            "resultOffset": result_offset,
            "resultRecordCount": result_record_count,
        }
        params.update({k: v for k, v in optional.items() if v is not None})

        if return_url is not None:
            params["returnUrl"] = "true" if return_url else "false"
        if return_metadata is not None:
            params["returnMetadata"] = "true" if return_metadata else "false"

        return params

    @staticmethod
    def _join(value: list | tuple | str | None) -> str | None:
        """Comma-join a list/tuple of values; pass through strings and None."""
        if value is None or isinstance(value, str):
            return value
        return ",".join(str(v) for v in value)

    @staticmethod
    def _require_property_enabled(
        attachment_properties: list[dict] | None,
        property_name: str,
        feature_label: str,
    ) -> None:
        """Raise if an attachmentProperties entry is present but disabled.

        Args:
            attachment_properties: The layer's attachmentProperties crosswalk.
            property_name: The response property the request feature depends on
                (e.g. ``"keywords"`` or ``"exifInfo"``).
            feature_label: Human-readable name of the request feature, used in the
                error message.

        Raises:
            InvalidParameterError: If the property is present with isEnabled=False.
        """
        prop = next(
            (
                p
                for p in (attachment_properties or [])
                if p.get("name") == property_name
            ),
            None,
        )
        if prop is not None and not prop.get("isEnabled", True):
            raise InvalidParameterError(
                f"{feature_label} is not available: the layer's attachmentProperties "
                f"mark the '{property_name}' property as disabled (isEnabled=False)."
            )
