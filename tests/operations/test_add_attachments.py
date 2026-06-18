import io
from pathlib import Path

import pytest

from archibald.exceptions import InvalidParameterError
from archibald.models.edit_result_item import EditResultItem
from archibald.operations.add_attachments import AddAttachmentsOperation
from tests.helpers import make_esri_add_attachment_response, make_response


class TestResolveFilename:
    def test_path_uses_stem(self):
        assert (
            AddAttachmentsOperation._resolve_filename(Path("a/b/photo.jpg"), None)
            == "photo.jpg"
        )

    def test_path_override_wins(self):
        assert (
            AddAttachmentsOperation._resolve_filename(Path("photo.jpg"), "override.png")
            == "override.png"
        )

    def test_bytes_uses_given_filename(self):
        assert (
            AddAttachmentsOperation._resolve_filename(b"data", "doc.pdf") == "doc.pdf"
        )

    def test_bytes_without_filename_raises(self):
        with pytest.raises(InvalidParameterError, match="filename must be provided"):
            AddAttachmentsOperation._resolve_filename(b"data", None)

    def test_binaryio_infers_from_name_attribute(self):
        buf = io.BytesIO(b"x")
        buf.name = "/some/path/report.pdf"
        assert AddAttachmentsOperation._resolve_filename(buf, None) == "report.pdf"

    def test_binaryio_override_wins_over_name_attribute(self):
        buf = io.BytesIO(b"x")
        buf.name = "/some/path/original.pdf"
        assert (
            AddAttachmentsOperation._resolve_filename(buf, "custom.pdf") == "custom.pdf"
        )

    def test_binaryio_without_name_raises(self):
        buf = io.BytesIO(b"x")
        with pytest.raises(InvalidParameterError, match="filename must be provided"):
            AddAttachmentsOperation._resolve_filename(buf, None)


class TestCoerceAttachments:
    def test_zips_parallel_iterables(self, add_attachments_op):
        result = add_attachments_op._coerce_attachments(
            [1, 2], [b"a", b"b"], ["a.jpg", "b.jpg"], [None, None]
        )
        oids, _, names, _ = zip(*result)
        assert list(oids) == [1, 2]
        assert list(names) == ["a.jpg", "b.jpg"]

    def test_fills_none_filenames_and_content_types_when_omitted(
        self, add_attachments_op
    ):
        result = add_attachments_op._coerce_attachments(
            [1], [Path("photo.jpg")], None, None
        )
        oid, file, name, ct = result[0]
        assert name == "photo.jpg"
        assert ct == "image/jpeg"

    def test_guesses_content_type_from_resolved_filename(self, add_attachments_op):
        result = add_attachments_op._coerce_attachments(
            [1], [b"data"], ["report.pdf"], None
        )
        assert result[0][3] == "application/pdf"

    def test_explicit_content_type_overrides_guess(self, add_attachments_op):
        result = add_attachments_op._coerce_attachments(
            [1], [b"data"], ["img.jpg"], ["image/tiff"]
        )
        assert result[0][3] == "image/tiff"

    def test_falls_back_to_octet_stream_for_unknown_extension(self, add_attachments_op):
        result = add_attachments_op._coerce_attachments(
            [1], [b"data"], ["file.xyz"], [None]
        )
        assert result[0][3] == "application/octet-stream"

    def test_accepts_generators(self, add_attachments_op):
        result = add_attachments_op._coerce_attachments(
            iter([1]), iter([b"x"]), iter(["x.pdf"]), iter([None])
        )
        assert result[0][2] == "x.pdf"
        assert result[0][3] == "application/pdf"

    @pytest.mark.parametrize(
        "ids, files, names, cts, expected",
        [
            ([1, 2], [b"a"], ["a.jpg", "b.jpg"], None, "got 2, 1, 2, 2"),
            ([1], [b"a", b"b"], ["a.jpg"], None, "got 1, 2, 1, 1"),
            ([1], [b"a"], ["a.jpg", "b.jpg"], None, "got 1, 1, 2, 1"),
            ([1], [b"a"], ["a.jpg"], ["image/jpeg", "image/png"], "got 1, 1, 1, 2"),
        ],
        ids=["too-few-files", "too-few-ids", "too-many-names", "too-many-types"],
    )
    def test_raises_on_length_mismatch(
        self, add_attachments_op, ids, files, names, cts, expected
    ):
        with pytest.raises(InvalidParameterError, match=expected):
            add_attachments_op._coerce_attachments(ids, files, names, cts)


class TestReadFile:
    @pytest.mark.anyio
    async def test_path_reads_bytes(self, tmp_path):
        p = tmp_path / "photo.jpg"
        p.write_bytes(b"imgdata")

        data = await AddAttachmentsOperation._read_file(p)

        assert data == b"imgdata"

    @pytest.mark.anyio
    async def test_bytes_passthrough(self):
        assert await AddAttachmentsOperation._read_file(b"raw") == b"raw"

    @pytest.mark.anyio
    async def test_binaryio_reads_content(self):
        buf = io.BytesIO(b"content")
        assert await AddAttachmentsOperation._read_file(buf) == b"content"


class TestPostOne:
    @pytest.mark.anyio
    async def test_posts_to_correct_endpoint(self, add_attachments_op):
        add_attachments_op._layer._client.post.return_value = make_response(
            make_esri_add_attachment_response(99)
        )

        await add_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg")
        call = add_attachments_op._layer._client.post.call_args

        assert (
            call.kwargs["endpoint"]
            == "services/MyService/FeatureServer/0/5/addAttachment"
        )

    @pytest.mark.anyio
    async def test_sends_resolved_filename_and_content_type(self, add_attachments_op):
        add_attachments_op._layer._client.post.return_value = make_response(
            make_esri_add_attachment_response(99)
        )

        await add_attachments_op._post_one(5, b"data", "report.pdf", "application/pdf")
        call_args = add_attachments_op._layer._client.post.call_args
        filename, data, ct = call_args.kwargs["files"]["attachment"]

        assert filename == "report.pdf"
        assert data == b"data"
        assert ct == "application/pdf"

    @pytest.mark.anyio
    async def test_returns_parsed_edit_result_item(self, add_attachments_op):
        add_attachments_op._layer._client.post.return_value = make_response(
            make_esri_add_attachment_response(77)
        )

        result = await add_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg")

        assert isinstance(result, EditResultItem)
        assert result.object_id == 77
        assert result.success is True


class TestExecute:
    @pytest.mark.anyio
    async def test_returns_one_result_per_attachment_in_input_order(
        self, add_attachments_op, mocker
    ):
        async def fake_post_one(oid, file, filename, content_type):
            return EditResultItem(
                object_id=oid * 10, global_id=None, success=True, error=None
            )

        mocker.patch.object(add_attachments_op, "_post_one", side_effect=fake_post_one)

        result = await add_attachments_op.execute(
            [1, 2], [b"a", b"b"], ["a.jpg", "b.jpg"]
        )

        assert len(result.results) == 2
        assert result.results[0].object_id == 10  # oid=1 → 1*10
        assert result.results[1].object_id == 20  # oid=2 → 2*10

    @pytest.mark.anyio
    async def test_passes_resolved_content_type_to_each_post(
        self, add_attachments_op, mocker
    ):
        captured: dict[int, str] = {}

        async def fake_post_one(oid, file, filename, content_type):
            captured[oid] = content_type
            return EditResultItem(
                object_id=oid, global_id=None, success=True, error=None
            )

        mocker.patch.object(add_attachments_op, "_post_one", side_effect=fake_post_one)

        await add_attachments_op.execute(
            [1, 2],
            [b"a", b"b"],
            ["a.jpg", "b.png"],
            content_types=["image/tiff", None],
        )

        assert captured[1] == "image/tiff"  # explicit override for oid=1
        assert captured[2] == "image/png"  # guessed from "b.png" for oid=2

    @pytest.mark.anyio
    async def test_raises_on_length_mismatch(self, add_attachments_op):
        with pytest.raises(InvalidParameterError):
            await add_attachments_op.execute([1, 2], [b"a"])
