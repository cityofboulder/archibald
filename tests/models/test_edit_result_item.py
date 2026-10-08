import pytest

from archibald.exceptions import ArcGISError
from archibald.models.edit_result_item import EditResultItem


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
