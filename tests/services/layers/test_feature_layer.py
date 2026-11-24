"""Tests for FeatureLayer editing capabilities."""

import pandas as pd
import pytest

from archibald.exceptions import InvalidParameterError, LayerCapabilityError
from archibald.services import FeatureLayer
from tests.helpers import (
    DEFAULT_BATCHING_KWARGS,
    make_attachments_result,
    make_apply_edits_result,
    make_attachment_result_item,
    make_response,
)


class TestValidateKeyFields:
    @pytest.mark.parametrize(
        "key_fields,df,match",
        [
            ([], pd.DataFrame({"Name": ["Alice"]}), "must not be empty"),
            (["Nope"], pd.DataFrame({"Name": ["Alice"]}), "'Nope'"),
            (
                ["Name"],
                pd.DataFrame({"Name": ["Alice", "Alice"]}),
                "do not uniquely identify",
            ),
            (
                ["Name", "Status"],
                pd.DataFrame(
                    {
                        "Name": ["Alice", "Alice"],
                        "Status": ["Active", "Active"],
                    }
                ),
                "do not uniquely identify",
            ),
        ],
        ids=[
            "empty_key_fields",
            "unknown_column",
            "duplicate_key",
            "duplicate_composite_key",
        ],
    )
    def test_raises_on_invalid_key_fields(self, key_fields, df, match):
        with pytest.raises(InvalidParameterError, match=match):
            FeatureLayer._validate_key_fields(df, key_fields)

    def test_passes_for_valid_unique_keys(self):
        df = pd.DataFrame({"Name": ["Alice", "Bob"]})
        FeatureLayer._validate_key_fields(df, ["Name"])

    def test_passes_for_empty_df_with_matching_columns(self):
        df = pd.DataFrame(columns=["Name"])

        FeatureLayer._validate_key_fields(df, ["Name"])


class TestSupportsUpdate:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({"capabilities": "Query,Create,Update"}, True),
            ({"capabilities": "UPDATE"}, True),
            ({"capabilities": "Query,Create"}, False),
            ({}, False),
        ],
        ids=[
            "update_present",
            "update_uppercase",
            "update_absent",
            "capabilities_key_missing",
        ],
    )
    @pytest.mark.anyio
    async def test_returns_expected_value(
        self, feature_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        assert await feature_layer.supports_update() is expected


class TestSupportsRollbackOnFailure:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({"supportsRollbackOnFailureParameter": True}, True),
            ({"supportsRollbackOnFailureParameter": False}, False),
            (
                {
                    "advancedEditingCapabilities": {
                        "supportsRollbackOnFailureParameter": True
                    }
                },
                False,
            ),
            ({}, False),
        ],
        ids=["root_true", "root_false", "nested_only", "key_missing"],
    )
    @pytest.mark.anyio
    async def test_reads_layer_root_when_metadata_given(
        self, feature_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        assert await feature_layer.supports_rollback_on_failure() is expected


class TestSupportsAsyncApplyEdits:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({"advancedEditingCapabilities": {"supportsAsyncApplyEdits": True}}, True),
            (
                {"advancedEditingCapabilities": {"supportsAsyncApplyEdits": False}},
                False,
            ),
            ({"supportsAsyncApplyEdits": True}, False),
            ({}, False),
        ],
        ids=["nested_true", "nested_false", "root_only", "key_missing"],
    )
    @pytest.mark.anyio
    async def test_reads_advanced_editing_capabilities_when_metadata_given(
        self, feature_layer, mock_client, metadata, expected
    ):
        mock_client.get.return_value = make_response(metadata)

        assert await feature_layer.supports_async_apply_edits() is expected


class TestApplyEdits:
    @pytest.mark.anyio
    async def test_raises_when_not_supported(self, feature_layer, mocker):
        mocker.patch.object(feature_layer, "supports_apply_edits", return_value=False)

        with pytest.raises(
            LayerCapabilityError, match="does not support edit operations"
        ):
            await feature_layer.apply_edits()

    @pytest.mark.anyio
    async def test_delegates_to_apply_edits_op(self, feature_layer, mocker):
        df = pd.DataFrame({"Name": ["Alice"]})
        expected = make_apply_edits_result()
        mocker.patch.object(feature_layer, "supports_apply_edits", return_value=True)
        mock_execute = mocker.patch.object(
            feature_layer._apply_edits_op, "execute", return_value=expected
        )

        result = await feature_layer.apply_edits(adds=df, rollback_on_failure=True)

        mock_execute.assert_called_once_with(
            adds=df,
            updates=None,
            deletes=None,
            rollback_on_failure=True,
            apply_coded_values=False,
            use_server_async=None,
            max_batch_bytes=None,
            poll_timeout=None,
        )
        assert result is expected

    @pytest.mark.anyio
    async def test_threads_apply_coded_values_true_to_execute(
        self, feature_layer, mocker
    ):
        df = pd.DataFrame({"Status": ["Active"]})
        expected = make_apply_edits_result()
        mocker.patch.object(feature_layer, "supports_apply_edits", return_value=True)
        mock_execute = mocker.patch.object(
            feature_layer._apply_edits_op, "execute", return_value=expected
        )

        await feature_layer.apply_edits(adds=df, apply_coded_values=True)

        mock_execute.assert_called_once_with(
            adds=df,
            updates=None,
            deletes=None,
            rollback_on_failure=True,
            apply_coded_values=True,
            use_server_async=None,
            max_batch_bytes=None,
            poll_timeout=None,
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "kwargs,rollback_supported,expected",
        [
            ({}, True, True),
            ({"rollback_on_failure": True}, False, True),
            ({"rollback_on_failure": False}, True, False),
            pytest.param(
                {"rollback_on_failure": False},
                False,
                True,
                marks=pytest.mark.filterwarnings("ignore:.*rollbackOnFailure=False"),
            ),
        ],
        ids=[
            "default",
            "rollback_unsupported",
            "no_rollback_supported",
            "no_rollback_unsupported",
        ],
    )
    async def test_forwards_effective_rollback_to_execute_when_requested(
        self,
        feature_layer,
        mock_apply_edits_execute,
        mocker,
        kwargs,
        rollback_supported,
        expected,
    ):
        mocker.patch.object(
            feature_layer,
            "supports_rollback_on_failure",
            return_value=rollback_supported,
        )

        await feature_layer.apply_edits(deletes=[1], **kwargs)

        assert mock_apply_edits_execute.call_args.kwargs["rollback_on_failure"] is (
            expected
        )

    @pytest.mark.anyio
    async def test_warns_when_rollback_disabled_on_unsupported_layer(
        self, feature_layer, mock_apply_edits_execute, mocker
    ):
        mocker.patch.object(
            feature_layer, "supports_rollback_on_failure", return_value=False
        )

        with pytest.warns(
            UserWarning, match=r"does not support rollbackOnFailure=False"
        ):
            await feature_layer.apply_edits(deletes=[1], rollback_on_failure=False)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "kwargs,rollback_supported",
        [
            ({}, False),
            ({"rollback_on_failure": True}, False),
            ({"rollback_on_failure": False}, True),
        ],
        ids=["default_unsupported", "rollback_unsupported", "no_rollback_supported"],
    )
    async def test_no_warning_when_rollback_request_is_honored(
        self,
        feature_layer,
        mock_apply_edits_execute,
        mocker,
        recwarn,
        kwargs,
        rollback_supported,
    ):
        mocker.patch.object(
            feature_layer,
            "supports_rollback_on_failure",
            return_value=rollback_supported,
        )

        await feature_layer.apply_edits(deletes=[1], **kwargs)

        assert len(recwarn) == 0

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "per_call,client_default,async_supported,expected",
        [
            (None, None, False, None),
            (True, None, True, True),
            (None, True, True, True),
            (False, True, True, False),
            pytest.param(
                True,
                None,
                False,
                False,
                marks=pytest.mark.filterwarnings("ignore:.*async applyEdits"),
            ),
            pytest.param(
                None,
                True,
                False,
                False,
                marks=pytest.mark.filterwarnings("ignore:.*async applyEdits"),
            ),
        ],
        ids=[
            "default-auto",
            "per-call-true-supported",
            "client-true-supported",
            "per-call-false-overrides-client-true",
            "per-call-true-unsupported",
            "client-true-unsupported",
        ],
    )
    async def test_forwards_effective_use_server_async_to_execute(
        self,
        feature_layer,
        mock_apply_edits_execute,
        mocker,
        per_call,
        client_default,
        async_supported,
        expected,
    ):
        feature_layer._client._use_server_async = client_default
        mocker.patch.object(
            feature_layer, "supports_async_apply_edits", return_value=async_supported
        )

        await feature_layer.apply_edits(deletes=[1], use_server_async=per_call)

        assert mock_apply_edits_execute.call_args.kwargs["use_server_async"] is (
            expected
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "per_call,client_default",
        [(True, None), (None, True)],
        ids=["per-call", "client"],
    )
    async def test_warns_when_server_async_requested_on_unsupported_layer(
        self,
        feature_layer,
        mock_apply_edits_execute,
        mocker,
        per_call,
        client_default,
    ):
        feature_layer._client._use_server_async = client_default
        mocker.patch.object(
            feature_layer, "supports_async_apply_edits", return_value=False
        )

        with pytest.warns(UserWarning, match=r"does not support async applyEdits"):
            await feature_layer.apply_edits(deletes=[1], use_server_async=per_call)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "per_call,client_default,async_supported",
        [
            (None, None, False),
            (False, None, False),
            (True, None, True),
            (None, True, True),
        ],
        ids=["default-auto", "false-unsupported", "true-supported", "client-true"],
    )
    async def test_no_warning_when_server_async_request_is_honored(
        self,
        feature_layer,
        mock_apply_edits_execute,
        mocker,
        recwarn,
        per_call,
        client_default,
        async_supported,
    ):
        feature_layer._client._use_server_async = client_default
        mocker.patch.object(
            feature_layer, "supports_async_apply_edits", return_value=async_supported
        )

        await feature_layer.apply_edits(deletes=[1], use_server_async=per_call)

        assert len(recwarn) == 0

    @pytest.mark.anyio
    async def test_forwards_max_batch_bytes_and_poll_timeout_to_execute(
        self, feature_layer, mock_apply_edits_execute
    ):
        await feature_layer.apply_edits(
            deletes=[1], max_batch_bytes=500_000, poll_timeout=60.0
        )

        assert mock_apply_edits_execute.call_args.kwargs["max_batch_bytes"] == 500_000
        assert mock_apply_edits_execute.call_args.kwargs["poll_timeout"] == 60.0


class TestAppend:
    @pytest.mark.anyio
    async def test_delegates_to_apply_edits_with_adds(self, feature_layer, mocker):
        df = pd.DataFrame({"Name": ["Alice"]})
        expected = make_apply_edits_result()
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=expected
        )

        result = await feature_layer.append(df)

        mock_apply.assert_called_once_with(
            adds=df, apply_coded_values=False, **DEFAULT_BATCHING_KWARGS
        )
        assert result is expected


class TestUpsert:
    @pytest.mark.anyio
    async def test_routes_adds_and_updates(self, feature_layer, mocker):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        updates_df = pd.DataFrame({"Name": ["Bob"], "OBJECTID": [1]})
        mocker.patch.object(
            feature_layer,
            "_diff",
            return_value=(
                adds_df,
                updates_df,
                pd.DataFrame(columns=["OBJECTID", "Name"]),
            ),
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await feature_layer.upsert(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=adds_df,
            updates=updates_df,
            apply_coded_values=False,
            **DEFAULT_BATCHING_KWARGS,
        )

    @pytest.mark.parametrize(
        "adds_rows,updates_rows",
        [
            ([], [{"Name": "Bob", "OBJECTID": 1}]),
            ([{"Name": "Alice"}], []),
        ],
        ids=["empty_adds", "empty_updates"],
    )
    @pytest.mark.anyio
    async def test_passes_none_for_empty_partition(
        self, feature_layer, mocker, adds_rows, updates_rows
    ):
        adds_df = (
            pd.DataFrame(adds_rows) if adds_rows else pd.DataFrame(columns=["Name"])
        )
        updates_df = (
            pd.DataFrame(updates_rows)
            if updates_rows
            else pd.DataFrame(columns=["Name"])
        )
        mocker.patch.object(
            feature_layer,
            "_diff",
            return_value=(
                adds_df,
                updates_df,
                pd.DataFrame(columns=["OBJECTID", "Name"]),
            ),
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await feature_layer.upsert(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=None if adds_df.empty else adds_df,
            updates=None if updates_df.empty else updates_df,
            apply_coded_values=False,
            **DEFAULT_BATCHING_KWARGS,
        )


class TestSync:
    @pytest.mark.anyio
    async def test_routes_all_three(self, feature_layer, mocker):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        updates_df = pd.DataFrame({"Name": ["Bob"], "OBJECTID": [1]})
        deletes_df = pd.DataFrame({"OBJECTID": [2, 3], "Name": ["Cy", "Dee"]})
        expected = make_apply_edits_result()
        mocker.patch.object(
            feature_layer, "_diff", return_value=(adds_df, updates_df, deletes_df)
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=expected
        )

        await feature_layer.sync(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=adds_df,
            updates=updates_df,
            deletes=deletes_df,
            apply_coded_values=False,
            **DEFAULT_BATCHING_KWARGS,
        )

    @pytest.mark.anyio
    async def test_passes_none_for_empty_deletes(self, feature_layer, mocker):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        updates_df = pd.DataFrame({"Name": ["Bob"], "OBJECTID": [1]})
        mocker.patch.object(
            feature_layer,
            "_diff",
            return_value=(
                adds_df,
                updates_df,
                pd.DataFrame(columns=["OBJECTID", "Name"]),
            ),
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await feature_layer.sync(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=adds_df,
            updates=updates_df,
            deletes=None,
            apply_coded_values=False,
            **DEFAULT_BATCHING_KWARGS,
        )


class TestEditWrappers:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,extra_args",
        [("append", ()), ("upsert", (["Name"],)), ("sync", (["Name"],))],
        ids=["append", "upsert", "sync"],
    )
    async def test_forwards_batching_kwargs_to_apply_edits(
        self, feature_layer, mocker, method, extra_args
    ):
        df = pd.DataFrame({"Name": ["Alice"]})
        batching_kwargs = {
            "rollback_on_failure": False,
            "use_server_async": False,
            "max_batch_bytes": 500_000,
            "poll_timeout": 60.0,
        }
        mocker.patch.object(
            feature_layer,
            "_diff",
            return_value=(
                df,
                pd.DataFrame(columns=["Name"]),
                pd.DataFrame(columns=["OBJECTID", "Name"]),
            ),
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await getattr(feature_layer, method)(df, *extra_args, **batching_kwargs)

        assert {
            key: mock_apply.call_args.kwargs[key] for key in batching_kwargs
        } == batching_kwargs


class TestDiff:
    @pytest.mark.anyio
    async def test_new_rows_are_adds(self, feature_layer, mocker):
        input_df = pd.DataFrame({"Name": ["Alice", "Bob"]})
        existing_df = pd.DataFrame(columns=["OBJECTID", "Name"])
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, deletes = await feature_layer._diff(input_df, ["Name"])

        assert sorted(adds["Name"].tolist()) == ["Alice", "Bob"]
        assert updates.empty
        assert deletes.empty

    @pytest.mark.anyio
    async def test_matched_rows_become_updates_with_objectid(
        self, feature_layer, mocker
    ):
        input_df = pd.DataFrame({"Name": ["Alice"]})
        existing_df = pd.DataFrame({"OBJECTID": [5], "Name": ["Alice"]})
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, deletes = await feature_layer._diff(input_df, ["Name"])

        assert adds.empty
        assert updates["Name"].tolist() == ["Alice"]
        assert updates["OBJECTID"].tolist() == [5]
        assert deletes.empty

    @pytest.mark.anyio
    async def test_unmatched_existing_rows_are_deletes(self, feature_layer, mocker):
        input_df = pd.DataFrame({"Name": ["Alice"]})
        existing_df = pd.DataFrame({"OBJECTID": [1, 2], "Name": ["Alice", "Bob"]})
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, deletes = await feature_layer._diff(input_df, ["Name"])

        assert adds.empty
        assert updates["Name"].tolist() == ["Alice"]
        assert updates["OBJECTID"].tolist() == [1]
        assert deletes["OBJECTID"].tolist() == [2]

    @pytest.mark.anyio
    async def test_composite_key_uses_all_fields(self, feature_layer, mocker):
        input_df = pd.DataFrame(
            {
                "Name": ["Alice", "Alice"],
                "Status": ["Active", "Inactive"],
            }
        )
        existing_df = pd.DataFrame(
            {
                "OBJECTID": [1],
                "Name": ["Alice"],
                "Status": ["Active"],
            }
        )
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, deletes = await feature_layer._diff(input_df, ["Name", "Status"])

        assert adds["Status"].tolist() == ["Inactive"]
        assert updates["Status"].tolist() == ["Active"]
        assert updates["OBJECTID"].tolist() == [1]
        assert deletes.empty

    @pytest.mark.anyio
    async def test_empty_input_df_produces_all_deletes(self, feature_layer, mocker):
        input_df = pd.DataFrame(columns=["Name"])
        existing_df = pd.DataFrame({"OBJECTID": [1, 2], "Name": ["Alice", "Bob"]})
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, deletes = await feature_layer._diff(input_df, ["Name"])

        assert adds.empty
        assert updates.empty
        assert deletes["OBJECTID"].tolist() == [1, 2]

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "key_fields, expected_columns",
        [
            (["Name", "Status"], ["OBJECTID", "Name", "Status"]),
            (["Status", "Name"], ["OBJECTID", "Status", "Name"]),
        ],
        ids=["name-then-status", "status-then-name"],
    )
    async def test_deletes_hold_objectid_then_key_fields_when_layer_orders_differently(
        self, feature_layer, diff_query, key_fields, expected_columns
    ):
        input_df = pd.DataFrame({"Name": ["Alice"], "Status": ["A"]})

        _, _, deletes = await feature_layer._diff(input_df, key_fields)

        assert list(deletes.columns) == expected_columns
        assert deletes["OBJECTID"].tolist() == [2, 3]

    @pytest.mark.anyio
    async def test_query_requests_objectid_then_key_fields_when_diffing(
        self, feature_layer, diff_query
    ):
        input_df = pd.DataFrame({"Name": ["Alice"], "Status": ["A"]})

        await feature_layer._diff(input_df, ["Status", "Name"])

        diff_query.assert_called_once_with(
            out_fields=["OBJECTID", "Status", "Name"], return_geometry=False
        )


class TestAddAttachmentMethods:
    @pytest.mark.anyio
    async def test_raises_when_layer_has_no_attachments(self, feature_layer, mocker):
        mocker.patch.object(feature_layer, "supports_attachments", return_value=False)

        with pytest.raises(LayerCapabilityError, match="does not support attachments"):
            await feature_layer.add_attachments(1, b"data", "f.jpg")

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "object_ids,files,filenames,content_types,expected_oids,expected_files,expected_fns,expected_cts",
        [
            (
                1,
                b"data",
                "img.jpg",
                "image/jpeg",
                [1],
                [b"data"],
                ["img.jpg"],
                ["image/jpeg"],
            ),
            (
                1,
                [b"a", b"b"],
                ["a.jpg", "b.jpg"],
                None,
                [1, 1],
                [b"a", b"b"],
                ["a.jpg", "b.jpg"],
                None,
            ),
            (
                [1, 2],
                [b"a", b"b"],
                ["a.jpg", "b.jpg"],
                None,
                [1, 2],
                [b"a", b"b"],
                ["a.jpg", "b.jpg"],
                None,
            ),
        ],
        ids=["single", "fan_out", "multi"],
    )
    async def test_dispatches_to_operation(
        self,
        feature_layer,
        mocker,
        object_ids,
        files,
        filenames,
        content_types,
        expected_oids,
        expected_files,
        expected_fns,
        expected_cts,
    ):
        mocker.patch.object(feature_layer, "supports_attachments", return_value=True)
        expected = make_attachments_result([make_attachment_result_item(99)])
        mock_execute = mocker.patch.object(
            feature_layer._add_attachments_op, "execute", return_value=expected
        )

        result = await feature_layer.add_attachments(
            object_ids, files, filenames, content_types
        )

        mock_execute.assert_called_once_with(
            expected_oids, expected_files, expected_fns, expected_cts
        )
        assert result is expected


class TestDeleteAttachmentMethods:
    @pytest.mark.anyio
    async def test_raises_when_layer_has_no_attachments(self, feature_layer, mocker):
        mocker.patch.object(feature_layer, "supports_attachments", return_value=False)

        with pytest.raises(LayerCapabilityError, match="does not support attachments"):
            await feature_layer.delete_attachments(1, 10)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "object_ids,attachment_ids,expected_oids,expected_att_ids",
        [
            (1, 10, [1], [10]),
            (1, [10, 11], [1, 1], [10, 11]),
            ([1, 2], [10, 11], [1, 2], [10, 11]),
        ],
        ids=["single", "fan_out", "multi"],
    )
    async def test_dispatches_to_operation(
        self,
        feature_layer,
        mocker,
        object_ids,
        attachment_ids,
        expected_oids,
        expected_att_ids,
    ):
        mocker.patch.object(feature_layer, "supports_attachments", return_value=True)
        expected = make_attachments_result([make_attachment_result_item(10)])
        mock_execute = mocker.patch.object(
            feature_layer._delete_attachments_op, "execute", return_value=expected
        )

        result = await feature_layer.delete_attachments(object_ids, attachment_ids)

        mock_execute.assert_called_once_with(expected_oids, expected_att_ids)
        assert result is expected


class TestUpdateAttachmentMethods:
    @pytest.mark.anyio
    async def test_raises_when_layer_has_no_attachments(self, feature_layer, mocker):
        mocker.patch.object(feature_layer, "supports_attachments", return_value=False)

        with pytest.raises(LayerCapabilityError, match="does not support attachments"):
            await feature_layer.update_attachments(1, 10, b"data", "f.jpg")

    @pytest.mark.anyio
    async def test_raises_when_layer_does_not_support_update(
        self, feature_layer, mocker
    ):
        mocker.patch.object(feature_layer, "supports_attachments", return_value=True)
        mocker.patch.object(feature_layer, "supports_update", return_value=False)

        with pytest.raises(
            LayerCapabilityError, match="does not support updating attachments"
        ):
            await feature_layer.update_attachments(1, 10, b"data", "f.jpg")

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "object_ids,attachment_ids,files,filenames,content_types,expected_oids,expected_files,expected_fns,expected_cts,expected_att_ids",
        [
            (
                1,
                42,
                b"data",
                "img.jpg",
                "image/jpeg",
                [1],
                [b"data"],
                ["img.jpg"],
                ["image/jpeg"],
                [42],
            ),
            (
                1,
                [42, 43],
                [b"a", b"b"],
                ["a.jpg", "b.jpg"],
                None,
                [1, 1],
                [b"a", b"b"],
                ["a.jpg", "b.jpg"],
                None,
                [42, 43],
            ),
            (
                [1, 2],
                [42, 43],
                [b"a", b"b"],
                ["a.jpg", "b.jpg"],
                None,
                [1, 2],
                [b"a", b"b"],
                ["a.jpg", "b.jpg"],
                None,
                [42, 43],
            ),
        ],
        ids=["single", "fan_out", "multi"],
    )
    async def test_dispatches_to_operation(
        self,
        feature_layer,
        mocker,
        object_ids,
        attachment_ids,
        files,
        filenames,
        content_types,
        expected_oids,
        expected_files,
        expected_fns,
        expected_cts,
        expected_att_ids,
    ):
        mocker.patch.object(feature_layer, "supports_attachments", return_value=True)
        mocker.patch.object(feature_layer, "supports_update", return_value=True)
        expected = make_attachments_result([make_attachment_result_item(99)])
        mock_execute = mocker.patch.object(
            feature_layer._update_attachments_op, "execute", return_value=expected
        )

        result = await feature_layer.update_attachments(
            object_ids, attachment_ids, files, filenames, content_types
        )

        mock_execute.assert_called_once_with(
            expected_oids, expected_files, expected_fns, expected_cts, expected_att_ids
        )
        assert result is expected
