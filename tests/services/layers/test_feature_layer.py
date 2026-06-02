"""Tests for FeatureLayer editing capabilities."""

import pandas as pd
import pytest

from archibald.exceptions import InvalidParameterError, LayerCapabilityError
from archibald.services import FeatureLayer
from tests.helpers import make_apply_edits_result


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
            rollback_on_failure=False,
            apply_coded_values=True,
        )


class TestAppend:
    @pytest.mark.anyio
    async def test_delegates_to_apply_edits_with_adds(self, feature_layer, mocker):
        df = pd.DataFrame({"Name": ["Alice"]})
        expected = make_apply_edits_result()
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=expected
        )

        result = await feature_layer.append(df)

        mock_apply.assert_called_once_with(adds=df, apply_coded_values=False)
        assert result is expected


class TestUpsert:
    @pytest.mark.anyio
    async def test_routes_adds_and_updates(self, feature_layer, mocker):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        updates_df = pd.DataFrame({"Name": ["Bob"], "OBJECTID": [1]})
        mocker.patch.object(
            feature_layer, "_diff", return_value=(adds_df, updates_df, [])
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await feature_layer.upsert(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=adds_df, updates=updates_df, apply_coded_values=False
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
            feature_layer, "_diff", return_value=(adds_df, updates_df, [])
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await feature_layer.upsert(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=None if adds_df.empty else adds_df,
            updates=None if updates_df.empty else updates_df,
            apply_coded_values=False,
        )


class TestSync:
    @pytest.mark.anyio
    async def test_routes_all_three(self, feature_layer, mocker):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        updates_df = pd.DataFrame({"Name": ["Bob"], "OBJECTID": [1]})
        expected = make_apply_edits_result()
        mocker.patch.object(
            feature_layer, "_diff", return_value=(adds_df, updates_df, [2, 3])
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=expected
        )

        await feature_layer.sync(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=adds_df, updates=updates_df, deletes=[2, 3], apply_coded_values=False
        )

    @pytest.mark.anyio
    async def test_passes_none_for_empty_deletes(self, feature_layer, mocker):
        adds_df = pd.DataFrame({"Name": ["Alice"]})
        updates_df = pd.DataFrame({"Name": ["Bob"], "OBJECTID": [1]})
        mocker.patch.object(
            feature_layer, "_diff", return_value=(adds_df, updates_df, [])
        )
        mock_apply = mocker.patch.object(
            feature_layer, "apply_edits", return_value=make_apply_edits_result()
        )

        await feature_layer.sync(adds_df, ["Name"])

        mock_apply.assert_called_once_with(
            adds=adds_df, updates=updates_df, deletes=None, apply_coded_values=False
        )


class TestDiff:
    @pytest.mark.anyio
    async def test_new_rows_are_adds(self, feature_layer, mocker):
        input_df = pd.DataFrame({"Name": ["Alice", "Bob"]})
        existing_df = pd.DataFrame(columns=["OBJECTID", "Name"])
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, delete_oids = await feature_layer._diff(input_df, ["Name"])

        assert sorted(adds["Name"].tolist()) == ["Alice", "Bob"]
        assert updates.empty
        assert delete_oids == []

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

        adds, updates, delete_oids = await feature_layer._diff(input_df, ["Name"])

        assert adds.empty
        assert updates["Name"].tolist() == ["Alice"]
        assert updates["OBJECTID"].tolist() == [5]
        assert delete_oids == []

    @pytest.mark.anyio
    async def test_unmatched_existing_rows_are_deletes(self, feature_layer, mocker):
        input_df = pd.DataFrame({"Name": ["Alice"]})
        existing_df = pd.DataFrame({"OBJECTID": [1, 2], "Name": ["Alice", "Bob"]})
        mocker.patch.object(feature_layer, "objectid_field", return_value="OBJECTID")
        mock_result = mocker.MagicMock()
        mock_result.to_frame.return_value = existing_df
        mocker.patch.object(feature_layer, "query", return_value=mock_result)

        adds, updates, delete_oids = await feature_layer._diff(input_df, ["Name"])

        assert adds.empty
        assert updates["Name"].tolist() == ["Alice"]
        assert updates["OBJECTID"].tolist() == [1]
        assert delete_oids == [2]

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

        adds, updates, delete_oids = await feature_layer._diff(
            input_df, ["Name", "Status"]
        )

        assert adds["Status"].tolist() == ["Inactive"]
        assert updates["Status"].tolist() == ["Active"]
        assert updates["OBJECTID"].tolist() == [1]
        assert delete_oids == []
