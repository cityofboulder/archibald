"""Tests for ApplyEditsResult."""

from __future__ import annotations

import pandas as pd
import pytest

from archibald.exceptions import InvalidParameterError
from archibald.models.apply_edits_result import ApplyEditsResult
from tests.helpers import (
    CORE_FRAME_DTYPES,
    DEPRECATED_METHOD_CASES,
    ESRI_ROLLBACK_ERROR,
    make_apply_edits_result,
    make_edit_result_item,
    positions_by_kind,
)


class TestApplyEditsResultFromEsriResponse:
    def test_returns_correct_type(self):
        body: dict = {}

        result = ApplyEditsResult._from_esri_response(body)

        assert isinstance(result, ApplyEditsResult)

    @pytest.mark.parametrize(
        "esri_key, attr",
        [
            ("addResults", "add_results"),
            ("updateResults", "update_results"),
            ("deleteResults", "delete_results"),
        ],
        ids=["add", "update", "delete"],
    )
    def test_parses_result_list(self, esri_key, attr):
        body = {esri_key: [{"objectId": 1, "success": True}]}

        result = ApplyEditsResult._from_esri_response(body)

        items = getattr(result, attr)
        assert len(items) == 1
        assert items[0].object_id == 1

    def test_defaults_empty_when_key_absent(self):
        body: dict = {}

        result = ApplyEditsResult._from_esri_response(body)

        assert result.add_results == []
        assert result.update_results == []
        assert result.delete_results == []

    def test_preserves_item_order(self):
        body = {
            "addResults": [
                {"objectId": 10, "success": True},
                {"objectId": 20, "success": True},
                {"objectId": 30, "success": True},
            ]
        }

        result = ApplyEditsResult._from_esri_response(body)

        assert [r.object_id for r in result.add_results] == [10, 20, 30]


class TestApplyEditsResultHasFailures:
    def test_has_failures_false_when_all_succeed(self):
        result = make_apply_edits_result(
            adds=[make_edit_result_item(1)],
            updates=[make_edit_result_item(2)],
            deletes=[make_edit_result_item(3)],
        )

        assert result.has_failures is False

    @pytest.mark.parametrize(
        "kwarg",
        ["adds", "updates", "deletes"],
        ids=["add-fails", "update-fails", "delete-fails"],
    )
    def test_has_failures_true_when_any_item_fails(self, kwarg):
        result = make_apply_edits_result(
            **{kwarg: [make_edit_result_item(1, success=False)]}
        )

        assert result.has_failures is True

    def test_has_failures_false_when_all_lists_empty(self):
        result = make_apply_edits_result()

        assert result.has_failures is False

    def test_has_failures_returns_bool(self):
        result = make_apply_edits_result()

        assert type(result.has_failures) is bool


class TestApplyEditsResultFailedProperties:
    @pytest.mark.parametrize(
        "prop, kwarg",
        [
            ("failed_adds", "adds"),
            ("failed_updates", "updates"),
            ("failed_deletes", "deletes"),
        ],
        ids=["failed_adds", "failed_updates", "failed_deletes"],
    )
    def test_failed_property_returns_only_failures(self, prop, kwarg):
        items = [
            make_edit_result_item(1, success=True),
            make_edit_result_item(2, success=False, error={"code": 1001}),
        ]
        result = make_apply_edits_result(**{kwarg: items})

        failures = getattr(result, prop)

        assert len(failures) == 1
        assert failures[0].object_id == 2

    @pytest.mark.parametrize(
        "prop, failure_kwarg",
        [
            ("failed_adds", "updates"),
            ("failed_adds", "deletes"),
            ("failed_updates", "adds"),
            ("failed_updates", "deletes"),
            ("failed_deletes", "adds"),
            ("failed_deletes", "updates"),
        ],
        ids=[
            "adds-not-contaminated-by-updates",
            "adds-not-contaminated-by-deletes",
            "updates-not-contaminated-by-adds",
            "updates-not-contaminated-by-deletes",
            "deletes-not-contaminated-by-adds",
            "deletes-not-contaminated-by-updates",
        ],
    )
    def test_failed_property_does_not_cross_contaminate(self, prop, failure_kwarg):
        result = make_apply_edits_result(
            **{failure_kwarg: [make_edit_result_item(1, success=False)]}
        )

        assert getattr(result, prop) == []

    @pytest.mark.parametrize(
        "prop, kwarg",
        [
            ("failed_adds", "adds"),
            ("failed_updates", "updates"),
            ("failed_deletes", "deletes"),
        ],
        ids=["adds", "updates", "deletes"],
    )
    def test_failed_property_empty_when_no_failures(self, prop, kwarg):
        result = make_apply_edits_result(
            **{kwarg: [make_edit_result_item(1), make_edit_result_item(2)]}
        )

        assert getattr(result, prop) == []


class TestApplyEditsResultMerge:
    @pytest.mark.parametrize(
        "kwarg, attr",
        [
            ("adds", "add_results"),
            ("updates", "update_results"),
            ("deletes", "delete_results"),
        ],
        ids=["adds", "updates", "deletes"],
    )
    def test_merge_concatenates_results_in_order(self, kwarg, attr):
        r1 = make_apply_edits_result(**{kwarg: [make_edit_result_item(1)]})
        r2 = make_apply_edits_result(**{kwarg: [make_edit_result_item(2)]})

        merged = ApplyEditsResult._merge([r1, r2])

        assert [r.object_id for r in getattr(merged, attr)] == [1, 2]

    def test_merge_empty_list_returns_empty_result(self):
        merged = ApplyEditsResult._merge([])

        assert merged.add_results == []
        assert merged.update_results == []
        assert merged.delete_results == []

    def test_merge_single_item_list_is_identity(self):
        r = make_apply_edits_result(
            adds=[make_edit_result_item(1)],
            updates=[make_edit_result_item(2)],
            deletes=[make_edit_result_item(3)],
        )

        merged = ApplyEditsResult._merge([r])

        assert len(merged.add_results) == 1
        assert len(merged.update_results) == 1
        assert len(merged.delete_results) == 1

    def test_merge_preserves_total_item_count(self):
        results = [
            make_apply_edits_result(adds=[make_edit_result_item(i)]) for i in range(5)
        ]

        merged = ApplyEditsResult._merge(results)

        assert len(merged.add_results) == 5

    def test_merge_does_not_mutate_input_results(self):
        r1 = make_apply_edits_result(adds=[make_edit_result_item(1)])
        r2 = make_apply_edits_result(adds=[make_edit_result_item(2)])
        original_r1_adds = list(r1.add_results)

        ApplyEditsResult._merge([r1, r2])

        assert r1.add_results == original_r1_adds

    def test_merge_batch_with_empty_sublists_does_not_inflate_result(self):
        r1 = make_apply_edits_result(adds=[make_edit_result_item(1)])
        r2 = make_apply_edits_result()

        merged = ApplyEditsResult._merge([r1, r2])

        assert len(merged.add_results) == 1
        assert len(merged.update_results) == 0
        assert len(merged.delete_results) == 0


class TestApplyEditsResultDeprecatedMethods:
    @pytest.mark.parametrize("name, arg", DEPRECATED_METHOD_CASES)
    def test_public_method_warns_when_called(self, name, arg):
        method = getattr(ApplyEditsResult, name)

        with pytest.warns(DeprecationWarning, match=f"{name} is deprecated"):
            method(arg)

    @pytest.mark.parametrize("name, arg", DEPRECATED_METHOD_CASES)
    def test_public_method_matches_private_method_when_called(self, name, arg):
        expected = getattr(ApplyEditsResult, f"_{name}")(arg)

        with pytest.warns(DeprecationWarning):
            result = getattr(ApplyEditsResult, name)(arg)

        assert result == expected


class TestApplyEditsResultEquality:
    def test_results_are_equal_when_only_inputs_differ(self):
        item = make_edit_result_item(1)
        with_inputs = make_apply_edits_result(
            adds=[item], inputs={"adds": pd.DataFrame({"a": [1]})}
        )

        result = with_inputs == make_apply_edits_result(adds=[item])

        assert result is True


class TestApplyEditsResultFilter:
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({}, ([0, 1, 2], [0, 1], [0])),
            ({"kinds": "adds"}, ([0, 1, 2], [], [])),
            ({"kinds": ["updates", "deletes"]}, ([], [0, 1], [0])),
            ({"statuses": "failed"}, ([1], [1], [])),
            ({"statuses": ["succeeded", "unknown"]}, ([0, 2], [0], [0])),
            ({"kinds": "updates", "statuses": "failed"}, ([], [1], [])),
        ],
        ids=[
            "no-filter",
            "one-kind",
            "kind-list",
            "one-status",
            "status-list",
            "kind-and-status",
        ],
    )
    def test_filter_keeps_matching_items_when_criteria_given(
        self, mixed_status_result, kwargs, expected
    ):
        result = mixed_status_result.filter(**kwargs)

        assert positions_by_kind(result) == expected

    def test_filter_carries_inputs_when_filtering(self, mixed_status_result):
        result = mixed_status_result.filter(statuses="failed")

        assert result._inputs is mixed_status_result._inputs

    def test_filter_leaves_original_unchanged_when_filtering(self, mixed_status_result):
        mixed_status_result.filter(kinds="adds", statuses="failed")

        assert positions_by_kind(mixed_status_result) == ([0, 1, 2], [0, 1], [0])

    @pytest.mark.parametrize(
        "kwargs, match",
        [
            ({"kinds": "add"}, r"Invalid kinds: add\. Expected one of: adds, updates"),
            (
                {"statuses": ["failed", "error", "bad"]},
                r"Invalid statuses: bad, error\. Expected one of: succeeded",
            ),
        ],
        ids=["invalid-kind", "invalid-statuses"],
    )
    def test_filter_raises_when_value_is_invalid(
        self, mixed_status_result, kwargs, match
    ):
        with pytest.raises(InvalidParameterError, match=match):
            mixed_status_result.filter(**kwargs)


class TestApplyEditsResultMetadataFrame:
    @pytest.mark.parametrize(
        "result_fixture",
        ["mixed_status_result", "empty_apply_edits_result"],
        ids=["mixed", "empty"],
    )
    def test_core_columns_have_fixed_dtypes_when_built(self, request, result_fixture):
        result = request.getfixturevalue(result_fixture)

        frame = result._metadata_frame()

        core = frame.columns[: len(CORE_FRAME_DTYPES)]
        assert {c: str(frame[c].dtype) for c in core} == CORE_FRAME_DTYPES

    def test_rows_follow_adds_updates_deletes_order_when_built(
        self, mixed_status_result
    ):
        frame = mixed_status_result._metadata_frame()

        assert frame[["kind", "status", "object_id", "position"]].values.tolist() == [
            ["adds", "succeeded", 10, 0],
            ["adds", "failed", -1, 1],
            ["adds", "unknown", -1, 2],
            ["updates", "succeeded", 20, 0],
            ["updates", "failed", 21, 1],
            ["deletes", "succeeded", 30, 0],
        ]

    def test_position_is_null_when_item_has_none(self, rolled_back_result):
        frame = rolled_back_result._metadata_frame()

        assert frame["position"].isna().all()

    def test_error_columns_are_null_when_item_succeeded(self, mixed_status_result):
        frame = mixed_status_result._metadata_frame()

        assert frame.loc[0, "error_code":].isna().all()

    def test_error_values_are_flattened_when_outcome_unknown(self, mixed_status_result):
        frame = mixed_status_result._metadata_frame()

        assert frame.loc[2, "error_code":"error_outcome_unknown"].tolist() == [
            -1,
            "timed out",
            "ReadTimeout",
            True,
        ]


class TestApplyEditsResultErrorFrame:
    def test_extra_keys_become_snake_case_columns_when_present(
        self, rolled_back_result
    ):
        frame = rolled_back_result._metadata_frame()

        assert frame.loc[0, ["error_extended_code", "error_message"]].tolist() == [
            -2146,
            "Unable to complete operation.",
        ]
        assert frame.loc[0, "error_details"] == ESRI_ROLLBACK_ERROR["details"]

    @pytest.mark.parametrize(
        "error, expected",
        [
            (
                ESRI_ROLLBACK_ERROR,
                "Unable to complete operation. Operation rolled back. "
                "Setting of value for SITEGUID failed.",
            ),
            ({"code": 400, "message": "Only a message."}, "Only a message."),
            ({"code": 400, "details": ["First.", "Second."]}, "First. Second."),
            ({"code": 400, "description": "", "message": "Empty."}, "Empty."),
            ({"code": 400, "description": "Only desc."}, "Only desc."),
        ],
        ids=[
            "message-and-details",
            "message-only",
            "details-only",
            "empty-description",
            "description-only",
        ],
    )
    def test_description_is_filled_when_esri_sent_none(self, error, expected):
        items = [make_edit_result_item(-1, success=False, error=error)]

        frame = ApplyEditsResult._error_frame(items)

        assert frame.loc[0, "error_description"] == expected

    def test_description_is_null_when_no_text_is_available(self):
        items = [make_edit_result_item(-1, success=False, error={"code": 400})]

        frame = ApplyEditsResult._error_frame(items)

        assert pd.isna(frame.loc[0, "error_description"])

    def test_item_error_is_unchanged_when_frame_is_built(self, rolled_back_result):
        rolled_back_result._metadata_frame()

        assert rolled_back_result.add_results[0].error == ESRI_ROLLBACK_ERROR
