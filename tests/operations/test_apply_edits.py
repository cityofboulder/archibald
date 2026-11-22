"""Tests for ApplyEditsOperation."""

from __future__ import annotations

import json

import anyio
import httpx
import pandas as pd
import pytest

from archibald.exceptions import InvalidParameterError, ServiceError
from archibald.models import ApplyEditsResult
from archibald.operations.apply_edits import ApplyEditsOperation
from archibald.serializers._features import MAX_BATCH_BYTES
from tests.helpers import (
    BASE_URL,
    REJECTED_POLL_ERROR_CASES,
    make_arcgis_error,
    make_http_status_error,
    STATUS_URL,
    TRANSIENT_POLL_ERROR_CASES,
    make_apply_edits_result,
    make_edit_result_item,
    make_esri_apply_edits_response,
    make_response,
    make_small_feature,
)


class TestNormalizeDeletes:
    @pytest.mark.parametrize(
        "deletes, objectid_field, expected",
        [
            ([1, 2], "OBJECTID", pd.DataFrame({"OBJECTID": [1, 2]})),
            ([5, 6], "FID", pd.DataFrame({"FID": [5, 6]})),
            (
                pd.Series([7, 8], index=["x", "y"], name="oids"),
                "OBJECTID",
                pd.DataFrame({"OBJECTID": [7, 8]}, index=["x", "y"]),
            ),
        ],
        ids=["list", "list-custom-objectid-field", "series-keeps-index"],
    )
    def test_returns_objectid_frame_when_given_ids(
        self, deletes, objectid_field, expected
    ):
        result = ApplyEditsOperation._normalize_deletes(deletes, objectid_field)

        assert result is not None
        pd.testing.assert_frame_equal(result, expected)

    def test_returns_frame_unchanged_when_given_dataframe(self):
        df = pd.DataFrame({"OBJECTID": [10, 20], "Name": ["a", "b"]})

        result = ApplyEditsOperation._normalize_deletes(df, "OBJECTID")

        assert result is df

    def test_returns_none_when_deletes_is_none(self):
        result = ApplyEditsOperation._normalize_deletes(None, "OBJECTID")

        assert result is None


class TestPostBatch:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "key,feature",
        [
            ("adds", make_small_feature(1)),
            ("updates", make_small_feature(2)),
        ],
        ids=["adds", "updates"],
    )
    async def test_feature_list_json_encoded_in_body(
        self, apply_edits_op, mock_layer, key, feature
    ):
        batch = {key: [feature]}
        mock_layer._client.post.return_value = make_response(
            make_esri_apply_edits_response()
        )

        await apply_edits_op._post_batch(
            batch,
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=False,
            poll_timeout=300.0,
        )

        data = mock_layer._client.post.call_args.kwargs["data"]
        assert isinstance(data[key], str)
        assert json.loads(data[key]) == batch[key]

    @pytest.mark.anyio
    async def test_deletes_passed_as_string_verbatim(self, apply_edits_op, mock_layer):
        batch = {"deletes": "1,2,3"}
        mock_layer._client.post.return_value = make_response(
            make_esri_apply_edits_response(delete_ids=[1, 2, 3])
        )

        await apply_edits_op._post_batch(
            batch,
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=False,
            poll_timeout=300.0,
        )

        data = mock_layer._client.post.call_args.kwargs["data"]
        assert data["deletes"] == "1,2,3"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "rollback_on_failure,expected",
        [(True, "true"), (False, "false")],
        ids=["rollback", "no_rollback"],
    )
    async def test_rollback_key_always_sent_when_flag_set(
        self, apply_edits_op, mock_layer, rollback_on_failure, expected
    ):
        batch = {"adds": [make_small_feature(1)]}
        mock_layer._client.post.return_value = make_response(
            make_esri_apply_edits_response(add_ids=[1])
        )

        await apply_edits_op._post_batch(
            batch,
            objectid_field="OBJECTID",
            rollback_on_failure=rollback_on_failure,
            use_async=False,
            poll_timeout=300.0,
        )

        data = mock_layer._client.post.call_args.kwargs["data"]
        assert data["rollbackOnFailure"] == expected

    @pytest.mark.anyio
    async def test_async_key_included_when_use_async_true(
        self, apply_edits_op, mock_layer, mocker
    ):
        batch = {"adds": [make_small_feature(1)]}
        mock_layer._client.post.return_value = make_response(
            {"statusUrl": "https://example.com/status/1"}
        )
        mocker.patch.object(
            apply_edits_op,
            "_poll_status",
            return_value=make_esri_apply_edits_response(add_ids=[1]),
        )

        await apply_edits_op._post_batch(
            batch,
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=True,
            poll_timeout=300.0,
        )

        data = mock_layer._client.post.call_args.kwargs["data"]
        assert data["async"] == "true"

    @pytest.mark.anyio
    async def test_async_key_absent_when_use_async_false(
        self, apply_edits_op, mock_layer
    ):
        batch = {"adds": [make_small_feature(1)]}
        mock_layer._client.post.return_value = make_response(
            make_esri_apply_edits_response(add_ids=[1])
        )

        await apply_edits_op._post_batch(
            batch,
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=False,
            poll_timeout=300.0,
        )

        data = mock_layer._client.post.call_args.kwargs["data"]
        assert "async" not in data

    @pytest.mark.anyio
    async def test_sync_path_returns_apply_edits_result(
        self, apply_edits_op, mock_layer
    ):
        batch = {"adds": [make_small_feature(1)]}
        mock_layer._client.post.return_value = make_response(
            make_esri_apply_edits_response(add_ids=[10])
        )

        result = await apply_edits_op._post_batch(
            batch,
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=False,
            poll_timeout=300.0,
        )

        assert isinstance(result, ApplyEditsResult)
        assert len(result.add_results) == 1
        assert result.add_results[0].object_id == 10

    @pytest.mark.anyio
    async def test_async_path_calls_poll_status_with_status_url(
        self, apply_edits_op, mock_layer, mocker
    ):
        batch = {"adds": [make_small_feature(1)]}
        mock_layer._client.post.return_value = make_response(
            {"statusUrl": "https://example.com/status/42"}
        )
        mock_poll = mocker.patch.object(
            apply_edits_op,
            "_poll_status",
            return_value=make_esri_apply_edits_response(),
        )

        await apply_edits_op._post_batch(
            batch,
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=True,
            poll_timeout=300.0,
        )

        mock_poll.assert_awaited_once_with(
            "https://example.com/status/42", timeout=300.0
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "post_effect, expected",
        [
            pytest.param(
                make_arcgis_error(ServiceError, 400, "Unable to complete operation."),
                {
                    "message": "Unable to complete operation.",
                    "exception": None,
                    "outcome_unknown": None,
                },
                id="esri-envelope",
            ),
            pytest.param(
                httpx.ReadTimeout("slow"),
                {"message": None, "exception": "ReadTimeout", "outcome_unknown": True},
                id="read-timeout",
            ),
            pytest.param(
                httpx.ConnectError("refused"),
                {
                    "message": None,
                    "exception": "ConnectError",
                    "outcome_unknown": False,
                },
                id="connect-error",
            ),
            pytest.param(
                httpx.Response(
                    200, content=b"<html>", request=httpx.Request("POST", BASE_URL)
                ),
                {
                    "message": None,
                    "exception": "JSONDecodeError",
                    "outcome_unknown": True,
                },
                id="malformed-body",
            ),
        ],
    )
    async def test_returns_failed_items_when_post_fails(
        self, apply_edits_op, mock_layer, mixed_edit_batch, post_effect, expected
    ):
        if isinstance(post_effect, Exception):
            mock_layer._client.post.side_effect = post_effect
        else:
            mock_layer._client.post.return_value = post_effect

        result = await apply_edits_op._post_batch(
            mixed_edit_batch,
            objectid_field="OBJECTID",
            rollback_on_failure=True,
            use_async=False,
            poll_timeout=300.0,
        )

        items = result.add_results + result.update_results + result.delete_results
        assert [(item.object_id, item.success) for item in items] == [
            (-1, False),
            (7, False),
            (4, False),
        ]
        assert [
            {key: (item.error or {}).get(key) for key in expected} for item in items
        ] == [expected] * 3

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "poll_effect, expected",
        [
            pytest.param(
                ServiceError(
                    code=-1,
                    message="Async applyEdits job failed.",
                    raw_response={"status": "Failed"},
                ),
                {"message": None, "exception": "ServiceError", "outcome_unknown": True},
                id="job-failed",
            ),
            pytest.param(
                TimeoutError(),
                {"message": None, "exception": "TimeoutError", "outcome_unknown": True},
                id="timeout",
            ),
            pytest.param(
                make_http_status_error(404),
                {
                    "message": None,
                    "exception": "HTTPStatusError",
                    "outcome_unknown": True,
                },
                id="http-404",
            ),
            pytest.param(
                make_arcgis_error(
                    ServiceError, 400, "Requested operation is not supported."
                ),
                {
                    "message": "Requested operation is not supported.",
                    "exception": None,
                    "outcome_unknown": None,
                },
                id="result-url-envelope",
            ),
        ],
    )
    async def test_returns_failed_items_with_status_url_when_async_job_fails(
        self,
        apply_edits_op,
        mock_layer,
        mocker,
        mixed_edit_batch,
        poll_effect,
        expected,
    ):
        mock_layer._client.post.return_value = make_response({"statusUrl": STATUS_URL})
        mocker.patch.object(apply_edits_op, "_poll_status", side_effect=poll_effect)

        result = await apply_edits_op._post_batch(
            mixed_edit_batch,
            objectid_field="OBJECTID",
            rollback_on_failure=True,
            use_async=True,
            poll_timeout=300.0,
        )

        items = result.add_results + result.update_results + result.delete_results
        assert [(item.object_id, item.success) for item in items] == [
            (-1, False),
            (7, False),
            (4, False),
        ]
        assert [
            {key: (item.error or {}).get(key) for key in expected} for item in items
        ] == [expected] * 3
        assert [(item.error or {}).get("status_url") for item in items] == [
            STATUS_URL
        ] * 3

    @pytest.mark.anyio
    async def test_returns_unknown_outcome_items_when_async_response_lacks_status_url(
        self, apply_edits_op, mock_layer, mocker, mixed_edit_batch
    ):
        mock_layer._client.post.return_value = make_response({})
        mock_poll = mocker.patch.object(apply_edits_op, "_poll_status")

        result = await apply_edits_op._post_batch(
            mixed_edit_batch,
            objectid_field="OBJECTID",
            rollback_on_failure=True,
            use_async=True,
            poll_timeout=300.0,
        )

        items = result.add_results + result.update_results + result.delete_results
        assert [
            (item.success, (item.error or {}).get("outcome_unknown")) for item in items
        ] == [(False, True)] * 3
        assert all("status_url" not in (item.error or {}) for item in items)
        mock_poll.assert_not_awaited()


class TestFailedBatchResult:
    @pytest.mark.parametrize(
        "batch, expected_ids",
        [
            pytest.param(
                {"adds": [make_small_feature(1), make_small_feature(2)]},
                ([-1, -1], [], []),
                id="adds",
            ),
            pytest.param(
                {
                    "updates": [
                        {"attributes": {"OBJECTID": 7}},
                        {"attributes": {"OBJECTID": 9}},
                    ]
                },
                ([], [7, 9], []),
                id="updates",
            ),
            pytest.param({"deletes": "4,5,6"}, ([], [], [4, 5, 6]), id="deletes"),
            pytest.param(
                {
                    "adds": [make_small_feature(1)],
                    "updates": [{"attributes": {"OBJECTID": 7}}],
                    "deletes": "4",
                },
                ([-1], [7], [4]),
                id="mixed",
            ),
            pytest.param(
                {"updates": [{"attributes": {"name": "no oid"}}]},
                ([], [-1], []),
                id="update-missing-objectid",
            ),
            pytest.param({}, ([], [], []), id="empty"),
        ],
    )
    def test_reports_object_ids_per_edit_type_when_batch_fails(
        self, batch, expected_ids
    ):
        result = ApplyEditsOperation._failed_batch_result(
            batch, httpx.ReadTimeout("slow"), "OBJECTID", outcome_unknown=True
        )

        assert (
            [item.object_id for item in result.add_results],
            [item.object_id for item in result.update_results],
            [item.object_id for item in result.delete_results],
        ) == expected_ids

    @pytest.mark.parametrize("outcome_unknown", [True, False], ids=["unknown", "known"])
    def test_marks_every_item_failed_with_batch_details_when_batch_fails(
        self, outcome_unknown, mixed_edit_batch
    ):
        result = ApplyEditsOperation._failed_batch_result(
            mixed_edit_batch,
            httpx.ReadTimeout("slow"),
            "OBJECTID",
            outcome_unknown=outcome_unknown,
            status_url=STATUS_URL,
        )

        items = result.add_results + result.update_results + result.delete_results
        assert [item.success for item in items] == [False] * 3
        assert [
            (
                (item.error or {}).get("exception"),
                (item.error or {}).get("outcome_unknown"),
                (item.error or {}).get("status_url"),
            )
            for item in items
        ] == [("ReadTimeout", outcome_unknown, STATUS_URL)] * 3


class TestPollStatus:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "status",
        ["Completed", "CompletedWithErrors"],
        ids=["completed", "completed_with_errors"],
    )
    async def test_returns_results_body_on_success_terminal_status(
        self, apply_edits_op, mock_layer, mocker, status
    ):
        mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        results_body = make_esri_apply_edits_response(add_ids=[1])
        mock_layer._client.get.side_effect = [
            make_response(
                {"status": status, "resultUrl": "https://results.example.com/1"}
            ),
            make_response(results_body),
        ]

        result = await apply_edits_op._poll_status(
            "https://status.example.com/1", timeout=300.0
        )

        assert result == results_body

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "status",
        ["Completed", "CompletedWithErrors"],
        ids=["completed", "completed_with_errors"],
    )
    async def test_fetches_result_url_on_success_terminal_status(
        self, apply_edits_op, mock_layer, mocker, status
    ):
        mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.side_effect = [
            make_response(
                {
                    "status": status,
                    "resultUrl": "https://results.example.com/job/42.json",
                }
            ),
            make_response(make_esri_apply_edits_response()),
        ]

        await apply_edits_op._poll_status("https://status.example.com/1", timeout=300.0)

        assert mock_layer._client.get.call_args_list[1].kwargs["url"] == (
            "https://results.example.com/job/42.json"
        )

    @pytest.mark.anyio
    async def test_raises_service_error_on_failed_status(
        self, apply_edits_op, mock_layer, mocker
    ):
        mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.return_value = make_response({"status": "Failed"})

        with pytest.raises(ServiceError, match="Async applyEdits job failed"):
            await apply_edits_op._poll_status(
                "https://status.example.com/1", timeout=300.0
            )

        assert mock_layer._client.get.call_count == 1

    @pytest.mark.anyio
    async def test_polls_until_completed(self, apply_edits_op, mock_layer, mocker):
        mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        results_body = make_esri_apply_edits_response()
        mock_layer._client.get.side_effect = [
            make_response({"status": "Pending"}),
            make_response({"status": "InProgress"}),
            make_response(
                {"status": "Completed", "resultUrl": "https://results.example.com/1"}
            ),
            make_response(results_body),
        ]

        result = await apply_edits_op._poll_status(
            "https://status.example.com/1", timeout=300.0
        )

        assert mock_layer._client.get.call_count == 4
        assert result == results_body

    @pytest.mark.anyio
    async def test_status_get_called_with_url_kwarg(
        self, apply_edits_op, mock_layer, mocker
    ):
        mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.side_effect = [
            make_response(
                {
                    "status": "Completed",
                    "resultUrl": "https://results.example.com/1",
                }
            ),
            make_response(make_esri_apply_edits_response()),
        ]

        await apply_edits_op._poll_status(
            "https://status.example.com/job/42", timeout=300.0
        )

        assert mock_layer._client.get.call_args_list[0].kwargs["url"] == (
            "https://status.example.com/job/42"
        )

    @pytest.mark.anyio
    async def test_raises_timeout_error_when_polling_exceeds_timeout(
        self, apply_edits_op, mock_layer
    ):
        # anyio.sleep is NOT mocked so it creates a real checkpoint where
        # anyio.fail_after can deliver cancellation.
        mock_layer._client.get.return_value = make_response({"status": "InProgress"})

        with pytest.raises(TimeoutError):
            await apply_edits_op._poll_status(
                "https://status.example.com/1", timeout=0.001
            )

    @pytest.mark.anyio
    async def test_exponential_backoff_delay(self, apply_edits_op, mock_layer, mocker):
        mock_sleep = mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        results_body = make_esri_apply_edits_response()
        mock_layer._client.get.side_effect = [
            make_response({"status": "InProgress"}),
            make_response({"status": "InProgress"}),
            make_response({"status": "InProgress"}),
            make_response(
                {"status": "Completed", "resultUrl": "https://results.example.com/1"}
            ),
            make_response(results_body),
        ]

        await apply_edits_op._poll_status("https://status.example.com/1", timeout=300.0)

        delays = [call.args[0] for call in mock_sleep.await_args_list]
        assert delays == [0.5, 1.0, 2.0]

    @pytest.mark.anyio
    async def test_delay_capped_at_max(self, apply_edits_op, mock_layer, mocker):
        mock_sleep = mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        results_body = make_esri_apply_edits_response()
        mock_layer._client.get.side_effect = [
            make_response({"status": "InProgress"}),
            make_response({"status": "InProgress"}),
            make_response({"status": "InProgress"}),
            make_response({"status": "InProgress"}),
            make_response({"status": "InProgress"}),
            make_response({"status": "InProgress"}),
            make_response(
                {"status": "Completed", "resultUrl": "https://results.example.com/1"}
            ),
            make_response(results_body),
        ]

        await apply_edits_op._poll_status("https://status.example.com/1", timeout=300.0)

        delays = [call.args[0] for call in mock_sleep.await_args_list]
        # 0.5 → 1.0 → 2.0 → 4.0 → capped at 5.0 → 5.0
        assert delays[-2] == 5.0
        assert delays[-1] == 5.0

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc", TRANSIENT_POLL_ERROR_CASES)
    async def test_retries_status_get_when_transient_error_raised(
        self, apply_edits_op, mock_layer, mocker, exc
    ):
        mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        results_body = make_esri_apply_edits_response(add_ids=[1])
        mock_layer._client.get.side_effect = [
            exc,
            make_response(
                {"status": "Completed", "resultUrl": "https://results.example.com/1"}
            ),
            make_response(results_body),
        ]

        result = await apply_edits_op._poll_status(
            "https://status.example.com/1", timeout=300.0
        )

        assert result == results_body
        assert mock_layer._client.get.call_count == 3

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc", TRANSIENT_POLL_ERROR_CASES)
    async def test_retries_result_url_get_when_transient_error_raised(
        self, apply_edits_op, mock_layer, mocker, exc
    ):
        mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        results_body = make_esri_apply_edits_response(add_ids=[1])
        completed = make_response(
            {"status": "Completed", "resultUrl": "https://results.example.com/1"}
        )
        mock_layer._client.get.side_effect = [
            completed,
            exc,
            completed,
            make_response(results_body),
        ]

        result = await apply_edits_op._poll_status(
            "https://status.example.com/1", timeout=300.0
        )

        assert result == results_body
        assert mock_layer._client.get.call_count == 4

    @pytest.mark.anyio
    @pytest.mark.parametrize("exc, match", REJECTED_POLL_ERROR_CASES)
    async def test_raises_without_retry_when_status_get_rejected(
        self, apply_edits_op, mock_layer, mocker, exc, match
    ):
        mocker.patch("archibald.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.side_effect = exc

        with pytest.raises(type(exc), match=match):
            await apply_edits_op._poll_status(
                "https://status.example.com/1", timeout=300.0
            )

        assert mock_layer._client.get.call_count == 1

    @pytest.mark.anyio
    async def test_raises_timeout_error_when_transient_errors_persist(
        self, apply_edits_op, mock_layer
    ):
        # anyio.sleep is NOT mocked so fail_after can deliver cancellation.
        mock_layer._client.get.side_effect = httpx.ReadTimeout("slow")

        with pytest.raises(TimeoutError):
            await apply_edits_op._poll_status(
                "https://status.example.com/1", timeout=0.001
            )


class TestPostBatches:
    @pytest.mark.anyio
    async def test_single_batch_returns_single_result(self, apply_edits_op, mocker):
        expected = make_apply_edits_result(adds=[make_edit_result_item(1)])
        mocker.patch.object(apply_edits_op, "_post_batch", return_value=expected)

        result = await apply_edits_op._post_batches(
            [{"adds": [make_small_feature(1)]}],
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=False,
            poll_timeout=300.0,
        )

        assert [r.object_id for r in result.add_results] == [1]

    @pytest.mark.anyio
    async def test_multiple_batches_merged_in_order(self, apply_edits_op, mocker):
        batch1 = {"adds": [make_small_feature(1)]}
        batch2 = {"adds": [make_small_feature(2)]}
        r1 = make_apply_edits_result(adds=[make_edit_result_item(1)])
        r2 = make_apply_edits_result(adds=[make_edit_result_item(2)])

        async def post_side_effect(
            batch, *, objectid_field, rollback_on_failure, use_async, poll_timeout
        ):
            return r1 if batch is batch1 else r2

        mocker.patch.object(apply_edits_op, "_post_batch", side_effect=post_side_effect)

        result = await apply_edits_op._post_batches(
            [batch1, batch2],
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=False,
            poll_timeout=300.0,
        )

        assert [r.object_id for r in result.add_results] == [1, 2]

    @pytest.mark.anyio
    async def test_rollback_and_async_flags_propagated_to_each_batch(
        self, apply_edits_op, mocker
    ):
        mock_post = mocker.patch.object(
            apply_edits_op,
            "_post_batch",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op._post_batches(
            [{}, {}],
            objectid_field="OBJECTID",
            rollback_on_failure=True,
            use_async=True,
            poll_timeout=300.0,
        )

        for call in mock_post.call_args_list:
            assert call.kwargs["rollback_on_failure"] is True
            assert call.kwargs["use_async"] is True

    @pytest.mark.anyio
    async def test_poll_timeout_propagated_to_each_batch(self, apply_edits_op, mocker):
        mock_post = mocker.patch.object(
            apply_edits_op,
            "_post_batch",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op._post_batches(
            [{}, {}],
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=True,
            poll_timeout=60.0,
        )

        for call in mock_post.call_args_list:
            assert call.kwargs["poll_timeout"] == 60.0

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "max_jobs, num_batches",
        [(1, 4), (2, 5)],
        ids=["cap-of-1", "cap-of-2"],
    )
    async def test_async_jobs_never_exceed_job_limiter_cap(
        self, apply_edits_op, mock_layer, mocker, max_jobs, num_batches
    ):
        mock_layer._client._job_limiter = anyio.CapacityLimiter(max_jobs)
        in_flight = 0
        max_observed = 0

        async def tracking_post(batch, **kwargs):
            nonlocal in_flight, max_observed
            in_flight += 1
            max_observed = max(max_observed, in_flight)
            await anyio.sleep(0.01)
            in_flight -= 1
            return make_apply_edits_result()

        mocker.patch.object(apply_edits_op, "_post_batch", side_effect=tracking_post)

        await apply_edits_op._post_batches(
            [{} for _ in range(num_batches)],
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=True,
            poll_timeout=300.0,
        )

        assert max_observed == max_jobs

    @pytest.mark.anyio
    async def test_sync_batches_do_not_take_job_permits(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer._client._job_limiter = anyio.CapacityLimiter(1)
        borrowed_during_post = []

        async def recording_post(batch, **kwargs):
            borrowed_during_post.append(mock_layer._client._job_limiter.borrowed_tokens)
            return make_apply_edits_result()

        mocker.patch.object(apply_edits_op, "_post_batch", side_effect=recording_post)

        await apply_edits_op._post_batches(
            [{}, {}, {}],
            objectid_field="OBJECTID",
            rollback_on_failure=False,
            use_async=False,
            poll_timeout=300.0,
        )

        assert borrowed_during_post == [0, 0, 0]

    @pytest.mark.anyio
    async def test_returns_failed_and_successful_batches_in_order_when_one_batch_fails(
        self, apply_edits_op, mock_layer
    ):
        async def post(*, endpoint, data):
            """Fail the batch deleting OID 1; succeed for the others."""
            if data["deletes"] == "1":
                raise httpx.ReadTimeout("slow")
            oid = int(data["deletes"])
            return make_response(make_esri_apply_edits_response(delete_ids=[oid]))

        mock_layer._client.post.side_effect = post

        result = await apply_edits_op._post_batches(
            [{"deletes": "0"}, {"deletes": "1"}, {"deletes": "2"}],
            objectid_field="OBJECTID",
            rollback_on_failure=True,
            use_async=False,
            poll_timeout=300.0,
        )

        assert [(r.object_id, r.success) for r in result.delete_results] == [
            (0, True),
            (1, False),
            (2, True),
        ]

    @pytest.mark.anyio
    async def test_job_permit_released_when_batch_raises(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer._client._job_limiter = anyio.CapacityLimiter(1)
        mocker.patch.object(
            apply_edits_op, "_post_batch", side_effect=ServiceError(500, "boom")
        )

        with pytest.raises(Exception):
            await apply_edits_op._post_batches(
                [{}],
                objectid_field="OBJECTID",
                rollback_on_failure=False,
                use_async=True,
                poll_timeout=300.0,
            )

        assert mock_layer._client._job_limiter.borrowed_tokens == 0


class TestExecute:
    @pytest.mark.anyio
    async def test_all_none_inputs_returns_empty_result_without_http_call(
        self, apply_edits_op, mock_layer
    ):
        result = await apply_edits_op.execute()

        assert isinstance(result, ApplyEditsResult)
        assert result.add_results == []
        assert result.update_results == []
        assert result.delete_results == []
        mock_layer._client.post.assert_not_called()

    @pytest.mark.anyio
    async def test_returns_apply_edits_result(self, apply_edits_op, mock_layer):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        mock_layer._client.post.return_value = make_response(
            make_esri_apply_edits_response(add_ids=[5])
        )

        result = await apply_edits_op.execute(adds=adds_df)

        assert isinstance(result, ApplyEditsResult)
        assert len(result.add_results) == 1
        assert result.add_results[0].object_id == 5

    @pytest.mark.anyio
    @pytest.mark.usefixtures("all_kinds_post")
    async def test_items_carry_kind_and_position_when_all_kinds_sent(
        self, apply_edits_op, all_kinds_edit_inputs
    ):
        result = await apply_edits_op.execute(**all_kinds_edit_inputs)

        assert [(i.kind, i.position) for i in result._items] == [
            ("adds", 0),
            ("adds", 1),
            ("updates", 0),
            ("deletes", 0),
        ]

    @pytest.mark.anyio
    @pytest.mark.usefixtures("all_kinds_post")
    async def test_inputs_stored_in_kind_order_when_all_kinds_sent(
        self, apply_edits_op, all_kinds_edit_inputs
    ):
        result = await apply_edits_op.execute(**all_kinds_edit_inputs)

        assert list(result._inputs) == ["adds", "updates", "deletes"]
        pd.testing.assert_frame_equal(
            result._inputs["adds"], all_kinds_edit_inputs["adds"]
        )
        pd.testing.assert_frame_equal(
            result._inputs["updates"], all_kinds_edit_inputs["updates"]
        )
        pd.testing.assert_frame_equal(
            result._inputs["deletes"], pd.DataFrame({"OBJECTID": [9]})
        )

    @pytest.mark.anyio
    @pytest.mark.usefixtures("all_kinds_post")
    async def test_stored_input_unchanged_when_caller_mutates_frame_afterwards(
        self, apply_edits_op, all_kinds_edit_inputs
    ):
        adds = all_kinds_edit_inputs["adds"]
        result = await apply_edits_op.execute(**all_kinds_edit_inputs)

        adds.loc[7, "Name"] = "changed"
        adds.drop(index=7, inplace=True)

        assert result._inputs["adds"]["Name"].tolist() == ["a", "b"]

    @pytest.mark.anyio
    async def test_inputs_stored_when_nothing_to_send(self, apply_edits_op, mock_layer):
        empty = pd.DataFrame({"Name": pd.Series([], dtype=str)})

        result = await apply_edits_op.execute(adds=empty)

        assert list(result._inputs) == ["adds"]
        mock_layer._client.post.assert_not_called()

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({}, True),
            ({"rollback_on_failure": True}, True),
            ({"rollback_on_failure": False}, False),
        ],
        ids=["default", "true", "false"],
    )
    async def test_rollback_forwarded_to_post_batches_when_given(
        self, apply_edits_op, mocker, kwargs, expected
    ):
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1], **kwargs)

        assert mock_post_batches.call_args.kwargs["rollback_on_failure"] is expected

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "rollback_on_failure,rollback_supported",
        [(True, True), (True, False), (False, True), (False, False)],
        ids=[
            "rollback_supported",
            "rollback_unsupported",
            "no_rollback_supported",
            "no_rollback_unsupported",
        ],
    )
    async def test_no_rollback_warnings_when_multiple_batches(
        self,
        apply_edits_op,
        mock_layer,
        mocker,
        recwarn,
        rollback_on_failure,
        rollback_supported,
    ):
        mock_layer.supports_rollback_on_failure.return_value = rollback_supported
        mocker.patch(
            "archibald.operations.apply_edits.pack_batches",
            return_value=[{"deletes": "1"}, {"deletes": "2"}],
        )
        mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(
            deletes=[1, 2], rollback_on_failure=rollback_on_failure
        )

        assert len(recwarn) == 0

    @pytest.mark.anyio
    async def test_async_false_for_single_batch_even_when_layer_supports_async(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer.supports_async_apply_edits.return_value = True
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1])

        assert mock_post_batches.call_args.kwargs["use_async"] is False

    @pytest.mark.anyio
    async def test_async_true_for_multiple_batches_when_layer_supports_async(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer.supports_async_apply_edits.return_value = True
        mocker.patch(
            "archibald.operations.apply_edits.pack_batches",
            return_value=[{"deletes": "1"}, {"deletes": "2"}],
        )
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1, 2])

        assert mock_post_batches.call_args.kwargs["use_async"] is True

    @pytest.mark.anyio
    async def test_async_flag_false_when_layer_does_not_support_async(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer.supports_async_apply_edits.return_value = False
        mocker.patch(
            "archibald.operations.apply_edits.pack_batches",
            return_value=[{"deletes": "1"}, {"deletes": "2"}],
        )
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1, 2])

        assert mock_post_batches.call_args.kwargs["use_async"] is False

    @pytest.mark.anyio
    async def test_poll_timeout_forwarded_to_post_batches(self, apply_edits_op, mocker):
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1], poll_timeout=60.0)

        assert mock_post_batches.call_args.kwargs["poll_timeout"] == 60.0

    @pytest.mark.anyio
    async def test_poll_timeout_defaults_to_client_job_timeout(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer._client._job_timeout = 42.0
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1])

        assert mock_post_batches.call_args.kwargs["poll_timeout"] == 42.0

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "per_call,client_default,num_batches,layer_supports_async,expected",
        [
            (True, None, 1, False, True),
            (False, None, 2, True, False),
            (None, True, 1, False, True),
            (None, False, 2, True, False),
            (True, False, 1, False, True),
            (False, True, 2, True, False),
        ],
        ids=[
            "per-call-true-single-batch-unsupported",
            "per-call-false-multi-batch-supported",
            "client-true-single-batch-unsupported",
            "client-false-multi-batch-supported",
            "per-call-true-overrides-client-false",
            "per-call-false-overrides-client-true",
        ],
    )
    async def test_use_async_follows_explicit_setting_when_use_server_async_set(
        self,
        apply_edits_op,
        mock_layer,
        mocker,
        per_call,
        client_default,
        num_batches,
        layer_supports_async,
        expected,
    ):
        mock_layer._client._use_server_async = client_default
        mock_layer.supports_async_apply_edits.return_value = layer_supports_async
        mocker.patch(
            "archibald.operations.apply_edits.pack_batches",
            return_value=[{"deletes": str(i)} for i in range(num_batches)],
        )
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1, 2], use_server_async=per_call)

        assert mock_post_batches.call_args.kwargs["use_async"] is expected

    @pytest.mark.anyio
    @pytest.mark.parametrize("use_server_async", [True, False], ids=["true", "false"])
    async def test_layer_async_support_not_checked_when_use_server_async_set(
        self, apply_edits_op, mock_layer, mocker, use_server_async
    ):
        mocker.patch(
            "archibald.operations.apply_edits.pack_batches",
            return_value=[{"deletes": "1"}, {"deletes": "2"}],
        )
        mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1, 2], use_server_async=use_server_async)

        mock_layer.supports_async_apply_edits.assert_not_awaited()

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "max_batch_bytes",
        [1, 500_000, MAX_BATCH_BYTES],
        ids=["minimum", "custom", "ceiling"],
    )
    async def test_max_batch_bytes_forwarded_to_pack_batches(
        self, apply_edits_op, mocker, max_batch_bytes
    ):
        mock_pack_batches = mocker.patch(
            "archibald.operations.apply_edits.pack_batches",
            return_value=[{"deletes": "1"}],
        )
        mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1], max_batch_bytes=max_batch_bytes)

        assert mock_pack_batches.call_args.kwargs["max_bytes"] == max_batch_bytes

    @pytest.mark.anyio
    async def test_max_batch_bytes_defaults_to_client_max_batch_bytes(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer._client._max_batch_bytes = 750_000
        mock_pack_batches = mocker.patch(
            "archibald.operations.apply_edits.pack_batches",
            return_value=[{"deletes": "1"}],
        )
        mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1])

        assert mock_pack_batches.call_args.kwargs["max_bytes"] == 750_000

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "max_batch_bytes",
        [0, -1, MAX_BATCH_BYTES + 1],
        ids=["zero", "negative", "above-ceiling"],
    )
    async def test_raises_when_max_batch_bytes_out_of_range(
        self, apply_edits_op, max_batch_bytes
    ):
        with pytest.raises(InvalidParameterError, match="max_batch_bytes"):
            await apply_edits_op.execute(deletes=[1], max_batch_bytes=max_batch_bytes)
