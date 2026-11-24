import pytest

from archibald.exceptions import ArcGISError
from archibald.models.edit_result_item import EditResultItem
from tests.helpers import STATUS_URL, make_edit_result_item


class TestEditResultItem:
    def test_parses_success_item(self):
        item = {"objectId": 1, "globalId": "{ABC-123}", "success": True, "error": None}

        result = EditResultItem._from_esri(item)

        assert result.object_id == 1
        assert result.global_id == "{ABC-123}"
        assert result.success is True
        assert result.error is None

    def test_parses_failure_item(self):
        error = {"code": 1001, "description": "Insert failed."}
        item = {"objectId": 2, "globalId": None, "success": False, "error": error}

        result = EditResultItem._from_esri(item)

        assert result.success is False
        assert result.error == error

    def test_object_id_defaults_to_minus_one_when_absent(self):
        result = EditResultItem._from_esri({"success": True})

        assert result.object_id == -1

    def test_global_id_is_none_when_absent(self):
        result = EditResultItem._from_esri({"objectId": 1, "success": True})

        assert result.global_id is None

    def test_success_defaults_to_false_when_absent(self):
        result = EditResultItem._from_esri({"objectId": 1})

        assert result.success is False

    def test_error_is_none_when_absent(self):
        result = EditResultItem._from_esri({"objectId": 1, "success": True})

        assert result.error is None

    def test_success_coerced_to_bool(self):
        result = EditResultItem._from_esri({"objectId": 1, "success": 1})

        assert result.success is True
        assert type(result.success) is bool

    @pytest.mark.parametrize(
        "attr, esri_key, value",
        [
            ("object_id", "objectId", 42),
            ("global_id", "globalId", "{GUID-XYZ}"),
            ("success", "success", True),
            ("error", "error", {"code": 500, "description": "Server error"}),
        ],
        ids=["objectId", "globalId", "success", "error"],
    )
    def test_field_mapping(self, attr, esri_key, value):
        item = {"objectId": 0, "success": True, esri_key: value}

        result = EditResultItem._from_esri(item)

        assert getattr(result, attr) == value


class TestEditResultItemFromException:
    def test_builds_failed_item_without_ids_when_defaults_used(self):
        result = EditResultItem._from_exception(ValueError("boom"))

        assert result.object_id == -1
        assert result.global_id is None
        assert result.success is False

    def test_object_id_is_passed_through_when_provided(self):
        result = EditResultItem._from_exception(ValueError("boom"), object_id=7)

        assert result.object_id == 7

    @pytest.mark.parametrize(
        "exc, expected_code, expected_description, expected_exception",
        [
            (ValueError("boom"), -1, "boom", "ValueError"),
            (KeyError(), -1, "KeyError", "KeyError"),
            (
                ArcGISError(code=403, message="denied"),
                403,
                "ArcGIS error 403: denied",
                "ArcGISError",
            ),
        ],
        ids=["plain-exception", "empty-message", "exception-with-code"],
    )
    def test_error_dict_describes_exception(
        self, exc, expected_code, expected_description, expected_exception
    ):
        result = EditResultItem._from_exception(exc)

        assert result.error == {
            "code": expected_code,
            "description": expected_description,
            "exception": expected_exception,
            "outcome_unknown": False,
        }

    @pytest.mark.parametrize(
        "outcome_unknown",
        [True, False],
        ids=["outcome-unknown", "outcome-known"],
    )
    def test_error_dict_always_carries_outcome_unknown_flag(self, outcome_unknown):
        result = EditResultItem._from_exception(
            ValueError("boom"), outcome_unknown=outcome_unknown
        )

        assert result.error is not None
        assert result.error["outcome_unknown"] is outcome_unknown

    @pytest.mark.parametrize(
        "status_url, expected",
        [(STATUS_URL, {"status_url": STATUS_URL}), (None, {})],
        ids=["provided", "omitted"],
    )
    def test_error_dict_carries_status_url_only_when_provided(
        self, status_url, expected
    ):
        result = EditResultItem._from_exception(
            ValueError("boom"), status_url=status_url
        )

        assert result.error is not None
        assert {k: v for k, v in result.error.items() if k == "status_url"} == expected


class TestEditResultItemStatus:
    @pytest.mark.parametrize(
        "success, error, expected",
        [
            (True, None, "succeeded"),
            (False, {"code": 1001, "description": "Insert failed."}, "failed"),
            (False, {"code": -1, "outcome_unknown": False}, "failed"),
            (False, {"code": -1, "outcome_unknown": True}, "unknown"),
            (False, None, "failed"),
        ],
        ids=[
            "success",
            "esri-error",
            "outcome-known",
            "outcome-unknown",
            "failure-without-error",
        ],
    )
    def test_status_reflects_outcome_when_success_and_error_vary(
        self, success, error, expected
    ):
        item = make_edit_result_item(1, success=success, error=error)

        result = item.status

        assert result == expected


class TestEditResultItemRowLink:
    @pytest.mark.parametrize(
        "item",
        [
            EditResultItem._from_esri({"objectId": 1, "success": True}),
            EditResultItem._from_exception(ValueError("boom")),
            make_edit_result_item(1),
        ],
        ids=["from-esri", "from-exception", "constructor"],
    )
    def test_kind_and_position_are_none_when_not_set(self, item):
        assert item.kind is None
        assert item.position is None

    @pytest.mark.parametrize(
        "other",
        [
            make_edit_result_item(1, kind="updates", position=0),
            make_edit_result_item(1, kind="adds", position=1),
        ],
        ids=["different-kind", "different-position"],
    )
    def test_items_are_unequal_when_only_kind_or_position_differs(self, other):
        item = make_edit_result_item(1, kind="adds", position=0)

        assert item != other
