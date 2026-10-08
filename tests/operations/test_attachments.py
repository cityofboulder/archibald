import io
from pathlib import Path

import httpx
import pytest

from archibald.exceptions import (
    AuthorizationError,
    InvalidParameterError,
    NotFoundError,
    ServiceError,
    TokenRefreshError,
)
from archibald.models.edit_result_item import EditResultItem
from archibald.operations.attachments import (
    AddAttachmentsOperation,
    _is_outcome_unknown,
)
from tests.helpers import (
    NonRecoverableSignal,
    make_arcgis_error,
    make_delete_post_failing_for,
    make_esri_add_attachment_response,
    make_esri_delete_attachments_response,
    make_esri_update_attachment_response,
    make_http_status_error,
    make_rejecting_post,
    make_response,
)

ESRI_ERROR_CASES = [
    pytest.param(AuthorizationError, 403, id="authorization"),
    pytest.param(NotFoundError, 404, id="not-found"),
    pytest.param(ServiceError, 500, id="service"),
]

POST_FAILURES = [
    pytest.param(make_http_status_error(413), id="http-413"),
    pytest.param(make_http_status_error(503), id="http-503"),
    pytest.param(httpx.ReadTimeout("slow"), id="read-timeout"),
    pytest.param(httpx.ConnectError("refused"), id="connect-error"),
    pytest.param(TokenRefreshError("refresh failed"), id="token-refresh"),
    pytest.param(OSError("boom"), id="os-error"),
]

POST_OUTCOME_CASES = [
    pytest.param(make_http_status_error(503), True, id="http-503-unknown"),
    pytest.param(make_http_status_error(413), False, id="http-413-known"),
    pytest.param(httpx.ReadTimeout("slow"), True, id="read-timeout-unknown"),
    pytest.param(httpx.ConnectError("refused"), False, id="connect-error-known"),
]

OUTCOME_UNKNOWN_CASES = [
    pytest.param(make_http_status_error(500), True, id="http-500"),
    pytest.param(make_http_status_error(502), True, id="http-502"),
    pytest.param(make_http_status_error(400), False, id="http-400"),
    pytest.param(make_http_status_error(413), False, id="http-413"),
    pytest.param(httpx.ConnectError("refused"), False, id="connect-error"),
    pytest.param(httpx.ConnectTimeout("slow"), False, id="connect-timeout"),
    pytest.param(httpx.PoolTimeout("busy"), False, id="pool-timeout"),
    pytest.param(httpx.ReadTimeout("slow"), True, id="read-timeout"),
    pytest.param(httpx.WriteTimeout("slow"), True, id="write-timeout"),
    pytest.param(httpx.ReadError("reset"), True, id="read-error"),
    pytest.param(httpx.RemoteProtocolError("bad"), True, id="remote-protocol-error"),
    pytest.param(ValueError("not json"), True, id="value-error"),
    pytest.param(KeyError("addAttachmentResult"), True, id="key-error"),
    pytest.param(make_arcgis_error(), False, id="arcgis-error"),
    pytest.param(TokenRefreshError("refresh failed"), False, id="token-refresh"),
    pytest.param(OSError("boom"), False, id="os-error"),
]

MALFORMED_RESPONSES = [
    pytest.param(
        httpx.Response(200, content=b"<html>not json</html>"),
        "JSONDecodeError",
        id="non-json-body",
    ),
    pytest.param(
        make_response({"unexpected": {}}), "KeyError", id="missing-result-key"
    ),
]


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
        oids, _, names, _, _ = zip(*result)

        assert list(oids) == [1, 2]
        assert list(names) == ["a.jpg", "b.jpg"]

    def test_fills_none_filenames_and_content_types_when_omitted(
        self, add_attachments_op
    ):
        result = add_attachments_op._coerce_attachments(
            [1], [Path("photo.jpg")], None, None
        )
        _, _, name, ct, att_id = result[0]

        assert name == "photo.jpg"
        assert ct == "image/jpeg"
        assert att_id is None

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
        "ids, files, names, cts, att_ids, expected",
        [
            ([1, 2], [b"a"], ["a.jpg", "b.jpg"], None, None, "got 2, 1, 2, 2, 2"),
            ([1], [b"a", b"b"], ["a.jpg"], None, None, "got 1, 2, 1, 1, 1"),
            ([1], [b"a"], ["a.jpg", "b.jpg"], None, None, "got 1, 1, 2, 1, 1"),
            (
                [1],
                [b"a"],
                ["a.jpg"],
                ["image/jpeg", "image/png"],
                None,
                "got 1, 1, 1, 2, 1",
            ),
            ([1, 2], [b"a", b"b"], ["a.jpg", "b.jpg"], None, [10], "got 2, 2, 2, 2, 1"),
        ],
        ids=[
            "too-few-files",
            "too-few-ids",
            "too-many-names",
            "too-many-types",
            "too-few-attachment-ids",
        ],
    )
    def test_raises_on_length_mismatch(
        self, add_attachments_op, ids, files, names, cts, att_ids, expected
    ):
        with pytest.raises(InvalidParameterError, match=expected):
            add_attachments_op._coerce_attachments(ids, files, names, cts, att_ids)

    def test_threads_attachment_ids_into_tuples(self, add_attachments_op):
        result = add_attachments_op._coerce_attachments(
            [1, 2], [b"a", b"b"], ["a.jpg", "b.jpg"], None, [10, 11]
        )
        assert [row[4] for row in result] == [10, 11]


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


class TestAddAttachmentsPostOne:
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

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc_class, code", ESRI_ERROR_CASES)
    async def test_post_one_returns_failed_item_when_server_rejects(
        self, add_attachments_op, exc_class, code
    ):
        add_attachments_op._layer._client.post.side_effect = make_arcgis_error(
            exc_class, code, "Rejected."
        )

        result = await add_attachments_op._post_one(5, b"data", "img.exe", "image/jpeg")

        assert result.success is False
        assert result.object_id == -1
        assert result.global_id is None
        assert result.error == {"code": code, "message": "Rejected."}

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc", POST_FAILURES)
    async def test_post_one_returns_failed_item_when_post_raises(
        self, add_attachments_op, exc
    ):
        add_attachments_op._layer._client.post.side_effect = exc

        result = await add_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg")

        assert result.success is False
        assert result.object_id == -1
        assert result.global_id is None
        assert result.error["exception"] == type(exc).__name__

    @pytest.mark.anyio
    @pytest.mark.parametrize("response, exception_name", MALFORMED_RESPONSES)
    async def test_post_one_returns_failed_item_when_response_is_malformed(
        self, add_attachments_op, response, exception_name
    ):
        add_attachments_op._layer._client.post.return_value = response

        result = await add_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg")

        assert result.success is False
        assert result.error["exception"] == exception_name

    @pytest.mark.anyio
    async def test_post_one_returns_failed_item_without_posting_when_file_unreadable(
        self, add_attachments_op, tmp_path
    ):
        missing = tmp_path / "missing.jpg"

        result = await add_attachments_op._post_one(5, missing, "img.jpg", "image/jpeg")

        assert result.success is False
        assert result.error["exception"] == "FileNotFoundError"
        add_attachments_op._layer._client.post.assert_not_called()

    @pytest.mark.anyio
    async def test_post_one_returns_failed_item_when_arcgis_error_has_no_raw_response(
        self, add_attachments_op
    ):
        add_attachments_op._layer._client.post.side_effect = ServiceError(
            code=500, message="Server exploded."
        )

        result = await add_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg")

        assert result.success is False
        assert result.error["code"] == 500
        assert result.error["description"] == "ArcGIS error 500: Server exploded."
        assert result.error["exception"] == "ServiceError"

    @pytest.mark.anyio
    async def test_post_one_propagates_when_exception_is_not_an_exception_subclass(
        self, add_attachments_op
    ):
        add_attachments_op._layer._client.post.side_effect = NonRecoverableSignal()

        with pytest.raises(NonRecoverableSignal):
            await add_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg")

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc, expected", POST_OUTCOME_CASES)
    async def test_post_one_flags_outcome_unknown_according_to_exception(
        self, add_attachments_op, exc, expected
    ):
        add_attachments_op._layer._client.post.side_effect = exc

        result = await add_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg")

        assert result.error["outcome_unknown"] is expected

    @pytest.mark.anyio
    @pytest.mark.parametrize("response, exception_name", MALFORMED_RESPONSES)
    async def test_post_one_flags_outcome_unknown_when_response_is_malformed(
        self, add_attachments_op, response, exception_name
    ):
        add_attachments_op._layer._client.post.return_value = response

        result = await add_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg")

        assert result.error["outcome_unknown"] is True

    @pytest.mark.anyio
    async def test_post_one_does_not_flag_outcome_unknown_when_file_read_fails(
        self, add_attachments_op
    ):
        closed = io.BytesIO(b"data")
        closed.close()

        result = await add_attachments_op._post_one(5, closed, "img.jpg", "image/jpeg")

        assert result.error["exception"] == "ValueError"
        assert result.error["outcome_unknown"] is False
        add_attachments_op._layer._client.post.assert_not_called()

    @pytest.mark.anyio
    async def test_post_one_does_not_flag_outcome_unknown_when_raw_response_missing(
        self, add_attachments_op
    ):
        add_attachments_op._layer._client.post.side_effect = ServiceError(
            code=500, message="Server exploded."
        )

        result = await add_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg")

        assert result.error["outcome_unknown"] is False


class TestIsOutcomeUnknown:
    @pytest.mark.parametrize("exc, expected", OUTCOME_UNKNOWN_CASES)
    def test_classifies_exception(self, exc, expected):
        assert _is_outcome_unknown(exc) is expected


class TestAddAttachmentsExecute:
    @pytest.mark.anyio
    async def test_returns_one_result_per_attachment_in_input_order(
        self, add_attachments_op, mocker
    ):
        async def fake_post_one(oid, file, filename, content_type, attachment_id=None):
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

        async def fake_post_one(oid, file, filename, content_type, attachment_id=None):
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

    @pytest.mark.anyio
    async def test_execute_reports_rejected_file_in_position_when_siblings_succeed(
        self, add_attachments_op
    ):
        add_attachments_op._layer._client.post.side_effect = make_rejecting_post(
            {"bad.exe"}, make_arcgis_error(), make_esri_add_attachment_response(99)
        )

        result = await add_attachments_op.execute(
            [1, 2, 3], [b"a", b"b", b"c"], ["a.jpg", "bad.exe", "c.jpg"]
        )

        assert [r.success for r in result.results] == [True, False, True]
        assert result.has_failures is True
        assert result.failed == [result.results[1]]

    @pytest.mark.anyio
    async def test_execute_does_not_raise_when_all_files_rejected(
        self, add_attachments_op
    ):
        add_attachments_op._layer._client.post.side_effect = make_rejecting_post(
            {"a.exe", "b.exe"},
            make_arcgis_error(),
            make_esri_add_attachment_response(99),
        )

        result = await add_attachments_op.execute(
            [1, 2], [b"a", b"b"], ["a.exe", "b.exe"]
        )

        assert len(result.failed) == 2

    @pytest.mark.anyio
    async def test_execute_keeps_siblings_when_one_upload_raises_unexpectedly(
        self, add_attachments_op
    ):
        add_attachments_op._layer._client.post.side_effect = make_rejecting_post(
            {"bad.jpg"},
            httpx.ReadTimeout("slow"),
            make_esri_add_attachment_response(99),
        )

        result = await add_attachments_op.execute(
            [1, 2, 3], [b"a", b"b", b"c"], ["a.jpg", "bad.jpg", "c.jpg"]
        )

        assert [r.success for r in result.results] == [True, False, True]
        assert result.results[1].error["exception"] == "ReadTimeout"


class TestUpdateAttachmentsPostOne:
    @pytest.mark.anyio
    async def test_posts_to_update_endpoint(self, update_attachments_op):
        update_attachments_op._layer._client.post.return_value = make_response(
            make_esri_update_attachment_response(99)
        )

        await update_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg", 42)
        call = update_attachments_op._layer._client.post.call_args

        assert (
            call.kwargs["endpoint"]
            == "services/MyService/FeatureServer/0/5/updateAttachment"
        )

    @pytest.mark.anyio
    async def test_sends_attachment_id_in_form_data(self, update_attachments_op):
        update_attachments_op._layer._client.post.return_value = make_response(
            make_esri_update_attachment_response(99)
        )

        await update_attachments_op._post_one(5, b"data", "img.jpg", "image/jpeg", 42)
        call = update_attachments_op._layer._client.post.call_args

        assert call.kwargs["data"] == {"attachmentId": 42}

    @pytest.mark.anyio
    async def test_returns_parsed_edit_result_item(self, update_attachments_op):
        update_attachments_op._layer._client.post.return_value = make_response(
            make_esri_update_attachment_response(77)
        )

        result = await update_attachments_op._post_one(
            5, b"data", "img.jpg", "image/jpeg", 42
        )

        assert isinstance(result, EditResultItem)
        assert result.object_id == 77
        assert result.success is True

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc_class, code", ESRI_ERROR_CASES)
    async def test_post_one_returns_failed_item_when_server_rejects(
        self, update_attachments_op, exc_class, code
    ):
        update_attachments_op._layer._client.post.side_effect = make_arcgis_error(
            exc_class, code, "Rejected."
        )

        result = await update_attachments_op._post_one(
            5, b"data", "img.exe", "image/jpeg", 42
        )
        call = update_attachments_op._layer._client.post.call_args

        assert result.success is False
        assert result.object_id == -1
        assert result.error == {"code": code, "message": "Rejected."}
        assert call.kwargs["data"] == {"attachmentId": 42}


class TestUpdateAttachmentsExecute:
    @pytest.mark.anyio
    async def test_passes_attachment_ids_to_each_post(
        self, update_attachments_op, mocker
    ):
        captured = {}

        async def fake_post_one(oid, file, filename, content_type, attachment_id=None):
            captured[oid] = attachment_id
            return EditResultItem(
                object_id=oid, global_id=None, success=True, error=None
            )

        mocker.patch.object(
            update_attachments_op, "_post_one", side_effect=fake_post_one
        )

        await update_attachments_op.execute(
            [1, 2], [b"a", b"b"], ["a.jpg", "b.jpg"], attachment_ids=[10, 11]
        )

        assert captured == {1: 10, 2: 11}

    @pytest.mark.anyio
    async def test_execute_reports_rejected_file_in_position_when_siblings_succeed(
        self, update_attachments_op
    ):
        update_attachments_op._layer._client.post.side_effect = make_rejecting_post(
            {"bad.exe"}, make_arcgis_error(), make_esri_update_attachment_response(99)
        )

        result = await update_attachments_op.execute(
            [1, 2, 3],
            [b"a", b"b", b"c"],
            ["a.jpg", "bad.exe", "c.jpg"],
            attachment_ids=[10, 11, 12],
        )

        assert [r.success for r in result.results] == [True, False, True]
        assert result.failed == [result.results[1]]

    @pytest.mark.anyio
    async def test_execute_keeps_siblings_when_one_update_raises_unexpectedly(
        self, update_attachments_op
    ):
        update_attachments_op._layer._client.post.side_effect = make_rejecting_post(
            {"bad.jpg"},
            httpx.ReadTimeout("slow"),
            make_esri_update_attachment_response(99),
        )

        result = await update_attachments_op.execute(
            [1, 2, 3],
            [b"a", b"b", b"c"],
            ["a.jpg", "bad.jpg", "c.jpg"],
            attachment_ids=[10, 11, 12],
        )

        assert [r.success for r in result.results] == [True, False, True]
        assert result.results[1].error["exception"] == "ReadTimeout"


class TestDeleteForObject:
    @pytest.mark.anyio
    async def test_posts_to_correct_endpoint(self, delete_attachments_op):
        delete_attachments_op._layer._client.post.return_value = make_response(
            make_esri_delete_attachments_response([10])
        )

        await delete_attachments_op._delete_for_object(5, [10])
        call = delete_attachments_op._layer._client.post.call_args

        assert (
            call.kwargs["endpoint"]
            == "services/MyService/FeatureServer/0/5/deleteAttachments"
        )

    @pytest.mark.anyio
    async def test_sends_comma_separated_attachment_ids(self, delete_attachments_op):
        delete_attachments_op._layer._client.post.return_value = make_response(
            make_esri_delete_attachments_response([10, 11])
        )

        await delete_attachments_op._delete_for_object(5, [10, 11])
        call = delete_attachments_op._layer._client.post.call_args

        assert call.kwargs["data"]["attachmentIds"] == "10,11"

    @pytest.mark.anyio
    async def test_returns_parsed_edit_result_items(self, delete_attachments_op):
        delete_attachments_op._layer._client.post.return_value = make_response(
            make_esri_delete_attachments_response([10, 11])
        )

        results = await delete_attachments_op._delete_for_object(5, [10, 11])

        assert len(results) == 2
        assert all(isinstance(r, EditResultItem) for r in results)
        assert [r.object_id for r in results] == [10, 11]

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc", POST_FAILURES)
    async def test_returns_failed_item_per_attachment_when_post_raises(
        self, delete_attachments_op, exc
    ):
        delete_attachments_op._layer._client.post.side_effect = exc

        results = await delete_attachments_op._delete_for_object(5, [10, 11])

        assert [r.object_id for r in results] == [10, 11]
        assert [r.success for r in results] == [False, False]
        assert [r.error["exception"] for r in results] == [type(exc).__name__] * 2

    @pytest.mark.anyio
    @pytest.mark.parametrize("response, exception_name", MALFORMED_RESPONSES)
    async def test_returns_failed_item_per_attachment_when_response_is_malformed(
        self, delete_attachments_op, response, exception_name
    ):
        delete_attachments_op._layer._client.post.return_value = response

        results = await delete_attachments_op._delete_for_object(5, [10, 11])

        assert [r.object_id for r in results] == [10, 11]
        assert [r.error["exception"] for r in results] == [exception_name] * 2

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc_class, code", ESRI_ERROR_CASES)
    async def test_returns_raw_esri_error_per_attachment_when_server_rejects(
        self, delete_attachments_op, exc_class, code
    ):
        delete_attachments_op._layer._client.post.side_effect = make_arcgis_error(
            exc_class, code, "Rejected."
        )

        results = await delete_attachments_op._delete_for_object(5, [10, 11])

        assert [r.object_id for r in results] == [10, 11]
        assert [r.success for r in results] == [False, False]
        assert [r.error for r in results] == [
            {"code": code, "message": "Rejected."}
        ] * 2

    @pytest.mark.anyio
    async def test_returns_synthesized_error_when_arcgis_error_has_no_raw_response(
        self, delete_attachments_op
    ):
        delete_attachments_op._layer._client.post.side_effect = ServiceError(
            code=500, message="Server exploded."
        )

        results = await delete_attachments_op._delete_for_object(5, [10, 11])

        assert [r.object_id for r in results] == [10, 11]
        assert [r.error["exception"] for r in results] == ["ServiceError"] * 2
        assert [r.error["outcome_unknown"] for r in results] == [False, False]

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc, expected", POST_OUTCOME_CASES)
    async def test_flags_outcome_unknown_on_every_attachment_according_to_exception(
        self, delete_attachments_op, exc, expected
    ):
        delete_attachments_op._layer._client.post.side_effect = exc

        results = await delete_attachments_op._delete_for_object(5, [10, 11])

        assert [r.error["outcome_unknown"] for r in results] == [expected, expected]


class TestDeleteAttachmentsExecute:
    @pytest.mark.anyio
    async def test_raises_on_length_mismatch(self, delete_attachments_op):
        with pytest.raises(InvalidParameterError, match="got 2, 1"):
            await delete_attachments_op.execute([1, 2], [10])

    @pytest.mark.anyio
    async def test_groups_same_oid_into_one_request(
        self, delete_attachments_op, mocker
    ):
        async def fake_delete(oid, att_ids):
            return [
                EditResultItem(object_id=i, global_id=None, success=True, error=None)
                for i in att_ids
            ]

        mock = mocker.patch.object(
            delete_attachments_op, "_delete_for_object", side_effect=fake_delete
        )

        await delete_attachments_op.execute([1, 1], [10, 11])

        mock.assert_called_once_with(1, [10, 11])

    @pytest.mark.anyio
    async def test_fires_one_request_per_unique_oid(
        self, delete_attachments_op, mocker
    ):
        async def fake_delete(oid, att_ids):
            return [
                EditResultItem(object_id=i, global_id=None, success=True, error=None)
                for i in att_ids
            ]

        mock = mocker.patch.object(
            delete_attachments_op, "_delete_for_object", side_effect=fake_delete
        )

        await delete_attachments_op.execute([1, 2], [10, 20])

        assert mock.call_count == 2

    @pytest.mark.anyio
    async def test_preserves_input_order_across_groups(
        self, delete_attachments_op, mocker
    ):
        async def fake_delete(oid, att_ids):
            return [
                EditResultItem(object_id=i, global_id=None, success=True, error=None)
                for i in att_ids
            ]

        mocker.patch.object(
            delete_attachments_op, "_delete_for_object", side_effect=fake_delete
        )

        # Input order: (oid=1, att=10), (oid=2, att=20), (oid=1, att=11)
        result = await delete_attachments_op.execute([1, 2, 1], [10, 20, 11])

        assert [r.object_id for r in result.results] == [10, 20, 11]

    @pytest.mark.anyio
    async def test_keeps_other_groups_when_one_group_request_fails(
        self, delete_attachments_op
    ):
        delete_attachments_op._layer._client.post.side_effect = (
            make_delete_post_failing_for({1}, httpx.ReadTimeout("slow"))
        )

        result = await delete_attachments_op.execute([1, 2, 1], [10, 20, 11])

        assert [r.object_id for r in result.results] == [10, 20, 11]
        assert [r.success for r in result.results] == [False, True, False]
        assert result.results[0].error["exception"] == "ReadTimeout"

    @pytest.mark.anyio
    async def test_reports_failure_for_attachment_missing_from_server_response(
        self, delete_attachments_op
    ):
        delete_attachments_op._layer._client.post.return_value = make_response(
            make_esri_delete_attachments_response([10])
        )

        result = await delete_attachments_op.execute([1, 1], [10, 11])

        assert result.results[0].success is True
        assert result.results[1].success is False
        assert result.results[1].object_id == 11
        assert result.results[1].error["exception"] == "LookupError"
        assert result.results[1].error["outcome_unknown"] is True
