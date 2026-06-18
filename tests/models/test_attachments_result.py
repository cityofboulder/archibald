import pandas as pd

from archibald.models.attachments_result import AddAttachmentsResult
from tests.helpers import make_attachment_result_item


class TestAddAttachmentsResult:
    def test_has_failures_property_is_false_when_all_succeed(self):
        result = AddAttachmentsResult(
            results=[
                make_attachment_result_item(1),
                make_attachment_result_item(2),
            ]
        )

        assert result.has_failures is False

    def test_has_failures_property_is_true_when_any_fails(self):
        result = AddAttachmentsResult(
            results=[
                make_attachment_result_item(1),
                make_attachment_result_item(2, success=False, error={"code": 400}),
            ]
        )

        assert result.has_failures is True

    def test_has_failures_property_is_false_when_empty(self):
        result = AddAttachmentsResult(results=[])

        assert result.has_failures is False

    def test_failed_property_returns_only_failures(self):
        ok = make_attachment_result_item(1)
        bad = make_attachment_result_item(2, success=False, error={"code": 400})
        result = AddAttachmentsResult(results=[ok, bad])

        assert result.failed == [bad]

    def test_failed_property_returns_empty_when_all_succeed(self):
        result = AddAttachmentsResult(results=[make_attachment_result_item(1)])

        assert result.failed == []


class TestAddAttachmentsResultToFrame:
    def test_returns_empty_dataframe_when_no_results(self):
        result = AddAttachmentsResult(results=[])

        df = result.to_frame()

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_columns_for_all_successes(self):
        result = AddAttachmentsResult(
            results=[
                make_attachment_result_item(1),
                make_attachment_result_item(2),
            ]
        )

        df = result.to_frame()

        assert list(df.columns) == ["object_id", "global_id", "success"]

    def test_values_for_successful_item(self):
        result = AddAttachmentsResult(
            results=[
                make_attachment_result_item(99, global_id="{ABC}"),
            ]
        )

        df = result.to_frame()

        assert df.loc[0, "object_id"] == 99
        assert df.loc[0, "global_id"] == "{ABC}"
        assert bool(df.loc[0, "success"]) is True

    def test_flattens_error_dict_into_prefixed_columns(self):
        result = AddAttachmentsResult(
            results=[
                make_attachment_result_item(
                    1, success=False, error={"code": 400, "description": "Bad request"}
                ),
            ]
        )

        df = result.to_frame()

        assert df.loc[0, "error_code"] == 400
        assert df.loc[0, "error_description"] == "Bad request"

    def test_error_columns_are_nan_for_successful_rows(self):
        result = AddAttachmentsResult(
            results=[
                make_attachment_result_item(1),
                make_attachment_result_item(
                    2, success=False, error={"code": 400, "description": "Bad"}
                ),
            ]
        )

        df = result.to_frame()

        assert pd.isna(df.loc[0, "error_code"])
        assert df.loc[1, "error_code"] == 400

    def test_preserves_row_order(self):
        result = AddAttachmentsResult(
            results=[
                make_attachment_result_item(10),
                make_attachment_result_item(20),
                make_attachment_result_item(30),
            ]
        )

        df = result.to_frame()

        assert df["object_id"].tolist() == [10, 20, 30]
