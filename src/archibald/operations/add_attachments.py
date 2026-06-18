"""AddAttachmentsOperation: post file attachments to individual features concurrently."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Iterable

import anyio

from archibald.exceptions import InvalidParameterError
from archibald.models.attachments_result import AddAttachmentsResult
from archibald.models.edit_result_item import EditResultItem

if TYPE_CHECKING:
    from archibald.services import FeatureLayer


class AddAttachmentsOperation:
    """Post file attachments to one or more features via the addAttachment endpoint.

    Holds a reference to its owning FeatureLayer to access the client and layer
    path. Instantiated once at FeatureLayer.__init__ time.
    """

    def __init__(self, layer: FeatureLayer) -> None:
        self._layer = layer

    async def execute(
        self,
        object_ids: Iterable[int],
        files: Iterable[Path | BinaryIO | bytes],
        filenames: Iterable[str | None] | None = None,
        content_types: Iterable[str | None] | None = None,
    ) -> AddAttachmentsResult:
        """Post attachments to multiple features concurrently.

        Filenames and content types are fully resolved during coercion before
        any requests are made. Each attachment's content type is guessed from
        its resolved filename when not provided explicitly.

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

        Returns:
            AddAttachmentsResult with one result per input item, in input order.

        Raises:
            InvalidParameterError: If any iterables differ in length, or if a
                bytes file has no resolvable filename.
        """
        coerced = self._coerce_attachments(object_ids, files, filenames, content_types)
        results: list[EditResultItem | None] = [None] * len(coerced)

        async def post_one(
            idx: int, oid: int, file: Path | BinaryIO | bytes, name: str, ct: str
        ) -> None:
            results[idx] = await self._post_one(oid, file, name, ct)

        async with anyio.create_task_group() as tg:
            for idx, (oid, file, name, ct) in enumerate(coerced):
                tg.start_soon(post_one, idx, oid, file, name, ct)

        return AddAttachmentsResult(results=results)  # type: ignore[arg-type]

    def _coerce_attachments(
        self,
        object_ids: Iterable[int],
        files: Iterable[Path | BinaryIO | bytes],
        filenames: Iterable[str | None] | None,
        content_types: Iterable[str | None] | None,
    ) -> list[tuple[int, Path | BinaryIO | bytes, str, str]]:
        """Validate parallel iterables, resolve filenames, and guess content types.

        Materializes all iterables, checks equal lengths, resolves each filename
        from its corresponding file when not provided explicitly, and guesses each
        content type from the resolved filename when not provided explicitly.

        Args:
            object_ids: Feature OBJECTIDs.
            files: Files to attach.
            filenames: Per-item filename overrides, or None to auto-detect all.
            content_types: Per-item MIME type overrides, or None to guess all.

        Returns:
            List of (object_id, file, resolved_filename, resolved_content_type)
            in input order. All filename and content type strings are fully
            resolved — no None values remain after this call.

        Raises:
            InvalidParameterError: If any iterables differ in length, or if a
                filename cannot be determined for a bytes or unnamed BinaryIO file.
        """
        ids = list(object_ids)
        fls = list(files)
        nms = list(filenames) if filenames is not None else [None] * len(ids)
        cts = list(content_types) if content_types is not None else [None] * len(ids)

        if not (len(ids) == len(fls) == len(nms) == len(cts)):
            raise InvalidParameterError(
                "object_ids, files, filenames, and content_types must all be the "
                f"same length (got {len(ids)}, {len(fls)}, {len(nms)}, {len(cts)})."
            )

        result = []
        for oid, file, name, ct in zip(ids, fls, nms, cts):
            resolved_name = self._resolve_filename(file, name)
            resolved_ct = (
                ct
                or mimetypes.guess_type(resolved_name)[0]
                or "application/octet-stream"
            )
            result.append((oid, file, resolved_name, resolved_ct))
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
    ) -> EditResultItem:
        """POST a single file attachment to one feature and return the result.

        Args:
            object_id: Feature OBJECTID to attach the file to.
            file: File to attach.
            filename: Resolved filename to send in the multipart form.
            content_type: Resolved MIME type to send in the multipart form.

        Returns:
            EditResultItem parsed from the addAttachmentResult response.
        """
        endpoint = f"{self._layer._layer_path}/{object_id}/addAttachment"
        data = await self._read_file(file)
        response = await self._layer._client.post(
            endpoint=endpoint,
            data={},
            files={"attachment": (filename, data, content_type)},
        )
        return EditResultItem._from_esri(response.json()["addAttachmentResult"])

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
