"""Tests for ApplyEditsResult."""

from __future__ import annotations

import pytest

from archibald.models.apply_edits_result import ApplyEditsResult
from tests.helpers import make_apply_edits_result, make_edit_result_item


class TestApplyEditsResultFromEsriResponse:
    def test_returns_correct_type(self):
        body: dict = {}

        result = ApplyEditsResult.from_esri_response(body)

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

        result = ApplyEditsResult.from_esri_response(body)

        items = getattr(result, attr)
        assert len(items) == 1
        assert items[0].object_id == 1

    def test_defaults_empty_when_key_absent(self):
        body: dict = {}

        result = ApplyEditsResult.from_esri_response(body)

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

        result = ApplyEditsResult.from_esri_response(body)

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

        merged = ApplyEditsResult.merge([r1, r2])

        assert [r.object_id for r in getattr(merged, attr)] == [1, 2]

    def test_merge_empty_list_returns_empty_result(self):
        merged = ApplyEditsResult.merge([])

        assert merged.add_results == []
        assert merged.update_results == []
        assert merged.delete_results == []

    def test_merge_single_item_list_is_identity(self):
        r = make_apply_edits_result(
            adds=[make_edit_result_item(1)],
            updates=[make_edit_result_item(2)],
            deletes=[make_edit_result_item(3)],
        )

        merged = ApplyEditsResult.merge([r])

        assert len(merged.add_results) == 1
        assert len(merged.update_results) == 1
        assert len(merged.delete_results) == 1

    def test_merge_preserves_total_item_count(self):
        results = [
            make_apply_edits_result(adds=[make_edit_result_item(i)]) for i in range(5)
        ]

        merged = ApplyEditsResult.merge(results)

        assert len(merged.add_results) == 5

    def test_merge_does_not_mutate_input_results(self):
        r1 = make_apply_edits_result(adds=[make_edit_result_item(1)])
        r2 = make_apply_edits_result(adds=[make_edit_result_item(2)])
        original_r1_adds = list(r1.add_results)

        ApplyEditsResult.merge([r1, r2])

        assert r1.add_results == original_r1_adds

    def test_merge_batch_with_empty_sublists_does_not_inflate_result(self):
        r1 = make_apply_edits_result(adds=[make_edit_result_item(1)])
        r2 = make_apply_edits_result()

        merged = ApplyEditsResult.merge([r1, r2])

        assert len(merged.add_results) == 1
        assert len(merged.update_results) == 0
        assert len(merged.delete_results) == 0
