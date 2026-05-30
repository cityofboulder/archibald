"""Tests for ApplyEditsOperation."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from archie.exceptions import ServiceError
from archie.models import ApplyEditsResult
from tests.helpers import (
    make_apply_edits_result,
    make_edit_result_item,
    make_esri_apply_edits_response,
    make_response,
    make_small_feature,
)


class TestNormalizeDeletes:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "deletes,expected",
        [
            (None, []),
            ([1, 2, 3], [1, 2, 3]),
            (pd.Series([7, 8, 9]), [7, 8, 9]),
        ],
        ids=["none", "list", "series"],
    )
    async def test_normalizes_to_list(self, apply_edits_op, deletes, expected):
        result = await apply_edits_op._normalize_deletes(deletes)

        assert result == expected
        assert isinstance(result, list)

    @pytest.mark.anyio
    async def test_dataframe_uses_objectid_field_column(self, apply_edits_op):
        df = pd.DataFrame({"OBJECTID": [10, 20], "Name": ["a", "b"]})

        result = await apply_edits_op._normalize_deletes(df)

        assert result == [10, 20]

    @pytest.mark.anyio
    async def test_dataframe_uses_custom_objectid_field(
        self, apply_edits_op, mock_layer
    ):
        mock_layer.objectid_field.return_value = "FID"
        df = pd.DataFrame({"FID": [5, 6]})

        result = await apply_edits_op._normalize_deletes(df)

        assert result == [5, 6]


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
            batch, rollback_on_failure=False, use_async=False
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
            batch, rollback_on_failure=False, use_async=False
        )

        data = mock_layer._client.post.call_args.kwargs["data"]
        assert data["deletes"] == "1,2,3"

    @pytest.mark.anyio
    async def test_rollback_key_included_when_true(self, apply_edits_op, mock_layer):
        batch = {"adds": [make_small_feature(1)]}
        mock_layer._client.post.return_value = make_response(
            make_esri_apply_edits_response(add_ids=[1])
        )

        await apply_edits_op._post_batch(
            batch, rollback_on_failure=True, use_async=False
        )

        data = mock_layer._client.post.call_args.kwargs["data"]
        assert data["rollbackOnFailure"] == "true"

    @pytest.mark.anyio
    async def test_rollback_key_absent_when_false(self, apply_edits_op, mock_layer):
        batch = {"adds": [make_small_feature(1)]}
        mock_layer._client.post.return_value = make_response(
            make_esri_apply_edits_response(add_ids=[1])
        )

        await apply_edits_op._post_batch(
            batch, rollback_on_failure=False, use_async=False
        )

        data = mock_layer._client.post.call_args.kwargs["data"]
        assert "rollbackOnFailure" not in data

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
            batch, rollback_on_failure=False, use_async=True
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
            batch, rollback_on_failure=False, use_async=False
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
            batch, rollback_on_failure=False, use_async=False
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
            batch, rollback_on_failure=False, use_async=True
        )

        mock_poll.assert_awaited_once_with("https://example.com/status/42")


class TestPollStatus:
    @pytest.mark.anyio
    async def test_returns_body_on_esri_job_succeeded(
        self, apply_edits_op, mock_layer, mocker
    ):
        mocker.patch("archie.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.return_value = make_response(
            {"status": "esriJobSucceeded"}
        )

        result = await apply_edits_op._poll_status("https://status.example.com/1")

        assert result["status"] == "esriJobSucceeded"

    @pytest.mark.anyio
    async def test_raises_service_error_on_esri_job_failed(
        self, apply_edits_op, mock_layer, mocker
    ):
        mocker.patch("archie.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.return_value = make_response(
            {"status": "esriJobFailed", "statusMessage": "Quota exceeded"}
        )

        with pytest.raises(ServiceError, match="Quota exceeded"):
            await apply_edits_op._poll_status("https://status.example.com/1")

    @pytest.mark.anyio
    async def test_raises_service_error_uses_default_message_when_absent(
        self, apply_edits_op, mock_layer, mocker
    ):
        mocker.patch("archie.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.return_value = make_response(
            {"status": "esriJobFailed"}
        )

        with pytest.raises(ServiceError, match="Async applyEdits job failed"):
            await apply_edits_op._poll_status("https://status.example.com/1")

    @pytest.mark.anyio
    async def test_polls_until_succeeded(self, apply_edits_op, mock_layer, mocker):
        mocker.patch("archie.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.side_effect = [
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobSucceeded"}),
        ]

        result = await apply_edits_op._poll_status("https://status.example.com/1")

        assert mock_layer._client.get.call_count == 3
        assert result["status"] == "esriJobSucceeded"

    @pytest.mark.anyio
    async def test_get_called_with_url_kwarg(self, apply_edits_op, mock_layer, mocker):
        mocker.patch("archie.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.return_value = make_response(
            {"status": "esriJobSucceeded"}
        )

        await apply_edits_op._poll_status("https://status.example.com/job/42")

        mock_layer._client.get.assert_called_once_with(
            url="https://status.example.com/job/42"
        )

    @pytest.mark.anyio
    async def test_exponential_backoff_delay(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_sleep = mocker.patch("archie.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.side_effect = [
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobSucceeded"}),
        ]

        await apply_edits_op._poll_status("https://status.example.com/1")

        delays = [call.args[0] for call in mock_sleep.await_args_list]
        assert delays == [0.5, 1.0, 2.0]

    @pytest.mark.anyio
    async def test_delay_capped_at_max(self, apply_edits_op, mock_layer, mocker):
        mock_sleep = mocker.patch("archie.operations.apply_edits.anyio.sleep")
        mock_layer._client.get.side_effect = [
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobExecuting"}),
            make_response({"status": "esriJobSucceeded"}),
        ]

        await apply_edits_op._poll_status("https://status.example.com/1")

        delays = [call.args[0] for call in mock_sleep.await_args_list]
        # 0.5 → 1.0 → 2.0 → 4.0 → capped at 5.0 → 5.0
        assert delays[-2] == 5.0
        assert delays[-1] == 5.0


class TestPostBatches:
    @pytest.mark.anyio
    async def test_single_batch_returns_single_result(
        self, apply_edits_op, mocker
    ):
        expected = make_apply_edits_result(adds=[make_edit_result_item(1)])
        mocker.patch.object(apply_edits_op, "_post_batch", return_value=expected)

        result = await apply_edits_op._post_batches(
            [{"adds": [make_small_feature(1)]}],
            rollback_on_failure=False,
            use_async=False,
        )

        assert result.add_results == expected.add_results

    @pytest.mark.anyio
    async def test_multiple_batches_merged_in_order(self, apply_edits_op, mocker):
        batch1 = {"adds": [make_small_feature(1)]}
        batch2 = {"adds": [make_small_feature(2)]}
        r1 = make_apply_edits_result(adds=[make_edit_result_item(1)])
        r2 = make_apply_edits_result(adds=[make_edit_result_item(2)])

        async def post_side_effect(batch, *, rollback_on_failure, use_async):
            return r1 if batch is batch1 else r2

        mocker.patch.object(apply_edits_op, "_post_batch", side_effect=post_side_effect)

        result = await apply_edits_op._post_batches(
            [batch1, batch2], rollback_on_failure=False, use_async=False
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
            [{}, {}], rollback_on_failure=True, use_async=True
        )

        for call in mock_post.call_args_list:
            assert call.kwargs["rollback_on_failure"] is True
            assert call.kwargs["use_async"] is True


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
    async def test_warns_and_disables_rollback_when_layer_does_not_support_it(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer.supports_rollback_on_failure.return_value = False
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        with pytest.warns(UserWarning, match="does not support rollbackOnFailure"):
            await apply_edits_op.execute(deletes=[1], rollback_on_failure=True)

        assert mock_post_batches.call_args.kwargs["rollback_on_failure"] is False

    @pytest.mark.anyio
    async def test_no_warning_when_rollback_false(
        self, apply_edits_op, mocker, recwarn
    ):
        mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1], rollback_on_failure=False)

        assert len(recwarn) == 0

    @pytest.mark.anyio
    async def test_warns_when_rollback_true_and_multiple_batches(
        self, apply_edits_op, mocker
    ):
        mocker.patch(
            "archie.operations.apply_edits.pack_batches",
            return_value=[{"deletes": "1"}, {"deletes": "2"}],
        )
        mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        with pytest.warns(UserWarning, match="multiple batches"):
            await apply_edits_op.execute(deletes=[1, 2], rollback_on_failure=True)

    @pytest.mark.anyio
    async def test_no_multi_batch_warning_when_rollback_false(
        self, apply_edits_op, mocker, recwarn
    ):
        mocker.patch(
            "archie.operations.apply_edits.pack_batches",
            return_value=[{"deletes": "1"}, {"deletes": "2"}],
        )
        mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1, 2], rollback_on_failure=False)

        assert len(recwarn) == 0

    @pytest.mark.anyio
    async def test_async_flag_true_when_layer_supports_async(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer.supports_async_apply_edits.return_value = True
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1])

        assert mock_post_batches.call_args.kwargs["use_async"] is True

    @pytest.mark.anyio
    async def test_async_flag_false_when_layer_does_not_support_async(
        self, apply_edits_op, mock_layer, mocker
    ):
        mock_layer.supports_async_apply_edits.return_value = False
        mock_post_batches = mocker.patch.object(
            apply_edits_op,
            "_post_batches",
            return_value=make_apply_edits_result(),
        )

        await apply_edits_op.execute(deletes=[1])

        assert mock_post_batches.call_args.kwargs["use_async"] is False
