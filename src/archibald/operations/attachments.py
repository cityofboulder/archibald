"""Attachment operations: add, update, and delete file attachments on feature layer records."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Iterable

import anyio

from archibald.exceptions import InvalidParameterError
from archibald.models.attachments_result import AttachmentsResult
from archibald.models.edit_result_item import EditResultItem

if TYPE_CHECKING:
    from archibald.services import FeatureLayer


class BaseAttachmentUploadOperation:
    """Shared machinery for uploading file attachments to features.

    Concrete subclasses set ``_endpoint`` to the per-feature endpoint action
    (e.g. ``addAttachment`` or ``updateAttachment``); the response key is derived
    as ``f"{_endpoint}Result"``. Handles coercion of parallel iterables, filename
    resolution, MIME-type guessing, file reading, and concurrent POSTs. Holds a
    reference to its owning FeatureLayer to access the client and layer path.
    Instantiated once at FeatureLayer.__init__ time.
    """

    _endpoint: str

    def __init__(self, layer: FeatureLayer) -> None:
        self._layer = layer

    async def execute(
        self,
        object_ids: Iterable[int],
        files: Iterable[Path | BinaryIO | bytes],
        filenames: Iterable[str | None] | None = None,
        content_types: Iterable[str | None] | None = None,
        attachment_ids: Iterable[int] | None = None,
    ) -> AttachmentsResult:
        """Upload attachments to multiple features concurrently.

        Filenames and content types are fully resolved during coercion before
        any requests are made. Each attachment's content type is guessed from
        its resolved filename when not provided explicitly. When ``attachment_ids``
        is provided, each upload targets that existing attachment (update);
        otherwise a new attachment is created (add).

        Args:
            object_ids: Feature OBJECTIDs to attach files to. OBJECTIDs can be repeated
                if multiple files are to be attached to the same feature.
            files: Files to attach, one per object_id. Each item may be a
                pathlib.Path, an open binary file object, or raw bytes.
            filenames: Per-item filename overrides. When omitted, filenames are
                inferred from each file (Path.name or file.name). Required
                per-item for any raw bytes entries.
            content_types: Per-item MIME type overrides. When omitted or None
                for an item, the type is guessed from the resolved filename and
                falls back to ``application/octet-stream``.
            attachment_ids: Per-item existing attachment IDs to update. When
                omitted, a new attachment is added for each item.

        Returns:
            AttachmentsResult with one result per input item, in input order.

        Raises:
            InvalidParameterError: If any iterables differ in length, or if a
                bytes file has no resolvable filename.
        """
        coerced = self._coerce_attachments(
            object_ids, files, filenames, content_types, attachment_ids
        )
        results: list[EditResultItem | None] = [None] * len(coerced)

        async def post_one(
            idx: int,
            oid: int,
            file: Path | BinaryIO | bytes,
            name: str,
            ct: str,
            att_id: int | None,
        ) -> None:
            results[idx] = await self._post_one(oid, file, name, ct, att_id)

        async with anyio.create_task_group() as tg:
            for idx, (oid, file, name, ct, att_id) in enumerate(coerced):
                tg.start_soon(post_one, idx, oid, file, name, ct, att_id)

        return AttachmentsResult(results=results)  # type: ignore[arg-type]

    def _coerce_attachments(
        self,
        object_ids: Iterable[int],
        files: Iterable[Path | BinaryIO | bytes],
        filenames: Iterable[str | None] | None,
        content_types: Iterable[str | None] | None,
        attachment_ids: Iterable[int] | None = None,
    ) -> list[tuple[int, Path | BinaryIO | bytes, str, str, int | None]]:
        """Validate parallel iterables, resolve filenames, and guess content types.

        Materializes all iterables, checks equal lengths, resolves each filename
        from its corresponding file when not provided explicitly, and guesses each
        content type from the resolved filename when not provided explicitly.

        Args:
            object_ids: Feature OBJECTIDs.
            files: Files to attach.
            filenames: Per-item filename overrides, or None to auto-detect all.
            content_types: Per-item MIME type overrides, or None to guess all.
            attachment_ids: Per-item existing attachment IDs (update), or None to
                add new attachments for all items.

        Returns:
            List of (object_id, file, resolved_filename, resolved_content_type,
            attachment_id) in input order. All filename and content type strings
            are fully resolved — no None values remain after this call.
            attachment_id is None for every item when adding.

        Raises:
            InvalidParameterError: If any iterables differ in length, or if a
                filename cannot be determined for a bytes or unnamed BinaryIO file.
        """
        ids = list(object_ids)
        fls = list(files)
        nms = list(filenames) if filenames is not None else [None] * len(ids)
        cts = list(content_types) if content_types is not None else [None] * len(ids)
        att = list(attachment_ids) if attachment_ids is not None else [None] * len(ids)

        if not (len(ids) == len(fls) == len(nms) == len(cts) == len(att)):
            raise InvalidParameterError(
                "object_ids, files, filenames, content_types, and attachment_ids "
                "must all be the same length (got "
                f"{len(ids)}, {len(fls)}, {len(nms)}, {len(cts)}, {len(att)})."
            )

        result = []
        for oid, file, name, ct, att_id in zip(ids, fls, nms, cts, att):
            resolved_name = self._resolve_filename(file, name)
            resolved_ct = (
                ct
                or mimetypes.guess_type(resolved_name)[0]
                or "application/octet-stream"
            )
            result.append((oid, file, resolved_name, resolved_ct, att_id))
        return result

    @staticmethod
    def _resolve_filename(file: Path | BinaryIO | bytes, filename: str | None) -> str:
        """Determine the filename for a file, using the override when provided.

        Args:
            file: Source file.
            filename: Explicit filename override.

        Returns:
            Resolved filename string.

        Raises:
            InvalidParameterError: If the filename cannot be determined.
        """
        if isinstance(file, Path):
            return filename or file.name

        if isinstance(file, bytes):
            if not filename:
                raise InvalidParameterError(
                    "filename must be provided when file is bytes."
                )
            return filename

        # BinaryIO
        resolved = filename or Path(getattr(file, "name", "") or "").name or None
        if not resolved:
            raise InvalidParameterError(
                "filename must be provided when file is a file-like object "
                "without a name attribute."
            )
        return resolved

    async def _post_one(
        self,
        object_id: int,
        file: Path | BinaryIO | bytes,
        filename: str,
        content_type: str,
        attachment_id: int | None = None,
    ) -> EditResultItem:
        """POST a single file attachment to one feature and return the result.

        Args:
            object_id: Feature OBJECTID to attach the file to.
            file: File to attach.
            filename: Resolved filename to send in the multipart form.
            content_type: Resolved MIME type to send in the multipart form.
            attachment_id: Existing attachment ID to update. When None, a new
                attachment is added; otherwise it is sent as the ``attachmentId``
                form field to target the existing attachment.

        Returns:
            EditResultItem parsed from the ``f"{self._endpoint}Result"`` response.
        """
        endpoint = f"{self._layer._layer_path}/{object_id}/{self._endpoint}"
        data = {} if attachment_id is None else {"attachmentId": attachment_id}
        body = await self._read_file(file)
        response = await self._layer._client.post(
            endpoint=endpoint,
            data=data,
            files={"attachment": (filename, body, content_type)},
        )
        return EditResultItem._from_esri(response.json()[f"{self._endpoint}Result"])

    @staticmethod
    async def _read_file(file: Path | BinaryIO | bytes) -> bytes:
        """Read file contents as bytes.

        Args:
            file: Source file as a Path, binary file object, or raw bytes.

        Returns:
            File contents as bytes.
        """
        if isinstance(file, Path):
            return await anyio.Path(file).read_bytes()
        if isinstance(file, bytes):
            return file
        return file.read()  # type: ignore


class AddAttachmentsOperation(BaseAttachmentUploadOperation):
    """Add new file attachments to features via the addAttachment endpoint."""

    _endpoint = "addAttachment"


class UpdateAttachmentsOperation(BaseAttachmentUploadOperation):
    """Replace existing file attachments on features via the updateAttachment endpoint."""

    _endpoint = "updateAttachment"


class DeleteAttachmentsOperation:
    """Delete file attachments from one or more features via the deleteAttachments endpoint.

    Accepts flat parallel iterables of feature OBJECTIDs and attachment IDs, groups
    them by OBJECTID internally, and fires one batched DELETE request per unique
    feature concurrently. Instantiated once at FeatureLayer.__init__ time.
    """

    def __init__(self, layer: FeatureLayer) -> None:
        self._layer = layer

    async def execute(
        self,
        object_ids: Iterable[int],
        attachment_ids: Iterable[int],
    ) -> AttachmentsResult:
        """Delete attachments from multiple features concurrently.

        Pairs are grouped by OBJECTID so that all attachments belonging to the
        same feature are deleted in a single request. Result order matches the
        input order of (object_id, attachment_id) pairs.

        Args:
            object_ids: Feature OBJECTIDs. May be repeated when multiple
                attachments on the same feature are to be deleted.
            attachment_ids: Attachment IDs to delete, one per object_id entry.

        Returns:
            AttachmentsResult with one result per input pair, in input order.

        Raises:
            InvalidParameterError: If object_ids and attachment_ids differ in length.
        """
        ids = list(object_ids)
        att_ids = list(attachment_ids)

        if len(ids) != len(att_ids):
            raise InvalidParameterError(
                "object_ids and attachment_ids must be the same length "
                f"(got {len(ids)}, {len(att_ids)})."
            )

        results: list[EditResultItem | None] = [None] * len(ids)

        groups: dict[int, list[tuple[int, int]]] = {}
        for idx, (oid, att_id) in enumerate(zip(ids, att_ids)):
            groups.setdefault(oid, []).append((idx, att_id))

        async def delete_group(oid: int, pairs: list[tuple[int, int]]) -> None:
            group_att_ids = [att_id for _, att_id in pairs]
            group_results = await self._delete_for_object(oid, group_att_ids)
            result_by_att_id = {r.object_id: r for r in group_results}
            for orig_idx, att_id in pairs:
                results[orig_idx] = result_by_att_id[att_id]

        async with anyio.create_task_group() as tg:
            for oid, pairs in groups.items():
                tg.start_soon(delete_group, oid, pairs)

        return AttachmentsResult(results=results)  # type: ignore[arg-type]

    async def _delete_for_object(
        self,
        object_id: int,
        attachment_ids: list[int],
    ) -> list[EditResultItem]:
        """DELETE one or more attachments from a single feature.

        Args:
            object_id: Feature OBJECTID whose attachments are being deleted.
            attachment_ids: Attachment IDs to delete in this request.

        Returns:
            List of EditResultItem parsed from the deleteAttachmentResults response,
            in the order the server returns them.
        """
        endpoint = f"{self._layer._layer_path}/{object_id}/deleteAttachments"
        response = await self._layer._client.post(
            endpoint=endpoint,
            data={"attachmentIds": ",".join(str(i) for i in attachment_ids)},
        )
        return [
            EditResultItem._from_esri(r)
            for r in response.json()["deleteAttachmentResults"]
        ]
